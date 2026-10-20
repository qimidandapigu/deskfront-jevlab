"""Actual SDK scheduling and submit path with controlled native/provider facts.

No native process or real model call; native execution is verified separately.
"""
import copy
from pathlib import Path
import sys
import time
import unittest

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from weapon_behavior_checks import Personal
from survival_review import current, can_execute, notify


def install(f, *, ready=True):
    world, unit = f.c.world, f.members[0]
    world['map_index'] = 2
    world['world_growth'] = dict(mission=dict(index=2, operation_id='mission-2'))
    uid = unit['id']
    f.squad['assignment_tokens'][uid] = 'assignment-1'
    scope = dict(run_id=world['run_id'], map_index=2, mission_operation_id='mission-2',
        mission_index=2, navigation_revision=world['navigation_revision'],
        control_epoch=world['control_epochs'][f.c.team], assignment_token='assignment-1', weapon=unit['weapon'])
    unit.update(hp=30, max_hp=150, in_cover=True, survival_reason='low_health', suppression=.55)
    unit['combat']['cover_execution'] = dict(phase='failed', reason='shelter_ineffective',
        attempt_id='attempt-1', review_required=True, review_handoff=dict(token='failed-shelter-1',
            scope=scope, state='pending', decision_allowed=True, execution_allowed=ready,
            blocked_reason='' if ready else 'incoming_explosive'))
    return unit['combat']['cover_execution']['review_handoff']


def pump_done(f):
    for _ in range(300):
        if f.c.soldiers.pending and f.c.soldiers.pending['future'].done():
            return
        time.sleep(.001)
    raise AssertionError('controlled provider did not complete')


class Checks(unittest.TestCase):
    def setUp(self): self.f = Personal(coordinates=False)
    def tearDown(self): self.f.close()

    def test_low_health_failed_shelter_prepares_once_not_every_tick(self):
        f=self.f; install(f); f.launch()
        self.assertEqual(f.c.soldiers.calls,1)
        for _ in range(20): f.tick()
        self.assertEqual(len(f.game.requests),1)
        f.answer('continue_task')
        f.c.world['time']=30
        for _ in range(10): f.tick()
        self.assertEqual(f.c.soldiers.calls,1)
        self.assertEqual(f.state.commands,[])

    def test_current_ready_token_is_sent_with_real_submit(self):
        f=self.f; row=install(f); request=f.launch()
        self.assertIn('move_to_site:C1',request['questions']['action']['criteria'])
        self.assertEqual(request['state']['execution_evidence']['cover_execution']['review_handoff']['token'],row['token'])
        f.answer('move_to_site:C1')
        command=f.state.commands[-1]
        self.assertEqual(command['survival_review_token'],row['token'])
        self.assertEqual(command['candidate_query_id'],'controlled-native-query')
        self.assertEqual(command['intent'],'move_to_site')
        self.assertEqual(command['control_epoch'],3)
        self.assertEqual(f.c.soldiers.agents['green-1']['status'],'submitting')

    def test_public_attached_agent_control_uses_same_scoped_handoff(self):
        f=self.f;row=install(f)
        f.c.config['control_mode']='agent'
        f.c.world['control']['green']='agent'
        f.c.identity=('test-run',3,'agent')
        f.launch();f.answer('move_to_site:C1')
        self.assertEqual(len(f.state.commands),1)
        self.assertEqual(f.state.commands[0]['survival_review_token'],row['token'])
        self.assertEqual(f.state.commands[0]['control_epoch'],3)

    def test_hard_danger_can_prepare_but_result_waits_then_submits_same_response(self):
        f=self.f; row=install(f,ready=False); f.members[0]['survival_reason']='incoming_explosive'
        f.launch(); f.answer('rush_to_site:C1')
        self.assertEqual(f.state.commands,[])
        self.assertEqual(f.c.soldiers.calls,1)
        for _ in range(10): f.tick()
        self.assertEqual(f.state.commands,[])
        row.update(execution_allowed=True,blocked_reason='')
        f.members[0]['survival_reason']='low_health'; f.tick()
        self.assertEqual(len(f.state.commands),1)
        self.assertEqual(f.state.commands[0]['survival_review_token'],row['token'])
        self.assertEqual(f.c.soldiers.calls,1)

    def test_expired_reply_does_not_retain_permission(self):
        for change in ('run','map','mission','navigation','epoch','assignment','weapon','token','resolved'):
            with self.subTest(change=change):
                f=Personal(coordinates=False)
                try:
                    row=install(f);f.launch()
                    if change=='run': f.c.world['run_id']='another-run'
                    elif change=='map': f.c.world['map_index']=3
                    elif change=='mission': f.c.world['world_growth']['mission']['operation_id']='new-mission'
                    elif change=='navigation': f.c.world['navigation_revision']=2
                    elif change=='epoch': f.c.world['control_epochs']['green']=4
                    elif change=='assignment': f.squad['assignment_tokens']['green-1']='assignment-2'
                    elif change=='weapon': f.members[0]['weapon']='smg'
                    elif change=='token': row['token']='different-failure'
                    else: row['state']='resolved'
                    f.answer('move_to_site:C1')
                    self.assertEqual(f.state.commands,[])
                    self.assertEqual(f.c.soldiers.discarded,1)
                finally: f.close()

    def test_equivalent_teammate_order_keeps_current_token(self):
        f=self.f;install(f);f.launch();f.squad['order_id']='teammate-order-2'
        f.answer('move_to_site:C1')
        self.assertEqual(len(f.state.commands),1)
        self.assertEqual(f.state.commands[0]['order_id'],'teammate-order-2')

    def test_handoff_invalidates_pre_failure_response_before_any_action(self):
        f=self.f;f.launch();install(f)
        f.answer('move_to_site:C1')
        self.assertEqual(f.state.commands,[])
        self.assertEqual(f.c.soldiers.discarded,1)
        self.assertEqual(f.c.soldiers.calls,1) # original wall cooldown still applies
        f.c.clock=lambda:102.;f.tick()
        self.assertEqual(f.c.soldiers.calls,2)
        self.assertEqual(f.c.soldiers.pending['survival_handoff']['token'],'failed-shelter-1')

    def test_one_squad_wake_without_commander_escalation_or_generic_duplicate(self):
        f=self.f;install(f)
        before=dict(f.c.revision)
        f.c._update_progress(f.members)
        for _ in range(20): f.c._update_progress(f.members)
        self.assertEqual(f.c.revision['executor'],before['executor']+1)
        self.assertEqual(f.c.revision['commander'],before['commander'])
        self.assertFalse(f.c.unit_history['green-1'].get('local_execution_watch',{}).get('episode'))

    def test_effective_cover_has_no_new_wake(self):
        f=self.f;f.members[0].update(in_cover=True,survival_reason='',suppression=0)
        before=dict(f.c.revision)
        for _ in range(10): notify(f.c,f.members[0],f.squad)
        self.assertEqual(f.c.revision,before)

    def test_old_snapshot_still_uses_legacy_survival_gate(self):
        f=self.f;f.members[0].update(survival_reason='low_health',suppression=.55)
        f.tick()
        self.assertEqual(f.c.soldiers.calls,0)
        self.assertEqual(f.c.soldiers.agents['green-1']['deferred_reason'],'survival_before_request')

    def test_incomplete_or_malformed_native_permission_never_grants_bypass(self):
        for change in ('missing_world_identity','missing_scope','missing_assignment','flag_string','false_decision',
                       'numeric_bool','control_changed','wrong_faction'):
            with self.subTest(change=change):
                f=Personal(coordinates=False)
                try:
                    row=install(f)
                    if change=='missing_world_identity': del f.c.world['map_index']
                    elif change=='missing_scope': del row['scope']['weapon']
                    elif change=='missing_assignment': f.squad['assignment_tokens'].clear()
                    elif change=='flag_string': row['execution_allowed']='true'
                    elif change=='numeric_bool': row['scope']['navigation_revision']=True
                    elif change=='control_changed': f.c.world['control']['green']='game_ai'
                    elif change=='wrong_faction': f.members[0]['faction']='red'
                    else: row['decision_allowed']=False
                    f.tick();self.assertEqual(f.c.soldiers.calls,0)
                finally:f.close()

    def test_request_budget_not_consumed_or_marked_when_unavailable(self):
        f=self.f;install(f);f.c.config['max_requests']=0;f.tick()
        self.assertEqual(f.c.soldiers.calls,0)
        self.assertNotIn('reviewed_survival_token',f.c.soldiers.agents['green-1'])
        f.c.config['max_requests']=1;f.launch()
        self.assertEqual(f.c.soldiers.calls,1)

    def test_shared_budget_claim_before_episode_consumption(self):
        class Budget:
            allowed=False
            def claim(self):return self.allowed
        f=self.f;install(f);b=Budget();f.c.config['shared_request_budget']=b;f.tick()
        self.assertEqual(f.c.soldiers.calls,0)
        self.assertNotIn('reviewed_survival_token',f.c.soldiers.agents['green-1'])
        f.c.budget_exhausted=False;b.allowed=True;f.launch()
        self.assertEqual(f.c.soldiers.calls,1)

    def test_failed_model_request_does_not_repeat_same_failure_token(self):
        f=self.f;install(f);f.launch()
        f.game.requests[0]['future'].set_exception(RuntimeError('controlled-provider-error'))
        pump_done(f);f.tick();f.c.world['time']=30;f.c.clock=lambda:130.
        for _ in range(10):f.tick()
        self.assertEqual(f.c.soldiers.calls,1)

    def test_recovering_native_handoff_does_not_open_another_request(self):
        f=self.f;row=install(f);row['state']='recovering';f.tick()
        self.assertEqual(f.c.soldiers.calls,0)

    def test_ordinary_pressure_native_false_keeps_normal_request_path(self):
        f=self.f;f.members[0]['suppression']=.5
        f.members[0]['combat']['fire_reaction']=dict(decision_blocked=False)
        f.launch();f.answer('move_to_site:C1')
        self.assertEqual(len(f.state.commands),1)
        self.assertNotIn('survival_review_token',f.state.commands[0])

    def test_command_still_uses_original_candidate_binding_not_direct_coordinates(self):
        f=self.f;install(f);f.launch();f.answer('move_to_site:C1')
        self.assertNotIn('position',f.state.commands[0])
        self.assertEqual(f.state.commands[0]['site_id'],'C1')

    def test_continued_or_reported_decision_never_fake_moves(self):
        f=self.f;install(f);f.launch();f.answer('report_blocked')
        self.assertEqual(f.state.commands[0]['intent'],'report_blocked')
        self.assertNotIn('survival_review_token',f.state.commands[0])
        self.assertEqual(f.members[0]['position'],[0.,0.])

    def test_readiness_flags_cannot_change_request_identity(self):
        f=self.f;row=install(f,ready=False);request=copy.deepcopy(row)
        self.assertFalse(can_execute(request,current(f.c.world,f.members[0],f.c.team,f.squad)))
        row.update(execution_allowed=True,blocked_reason='')
        self.assertTrue(can_execute(request,current(f.c.world,f.members[0],f.c.team,f.squad)))
        row['token']='new-attempt'
        self.assertFalse(can_execute(request,current(f.c.world,f.members[0],f.c.team,f.squad)))


if __name__=='__main__':unittest.main(verbosity=2)
