import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'/'deskfront'))
from commander_view import build


class CommanderViewChecks(unittest.TestCase):
    def test_keeps_unknown_and_task_identity_without_route_coordinates(self):
        task=dict(actor_id='green-2',command='support',support_for='green-1',target_id='red-1',
                  start_when='immediate',task_revision=9)
        context=dict(previous_plan=dict(tasks={'green-2':task}),region_opportunities=dict(
            query_status={'green-2':'unknown'},sampled_at={'green-2':None},
            route_options={'green-2':[dict(goal_region='side',goal_tags=['sampled_firing'],
                region_path=['start','side'],first_step=dict(status='ready',position=[.4,.5],risk=dict(status='unknown')))]}))
        result=build(context)
        self.assertEqual(result['previous_plan']['tasks']['green-2']['support_for'],'green-1')
        self.assertNotIn('task_revision',result['previous_plan']['tasks']['green-2'])
        options=result['maneuver_options']['green-2']
        self.assertEqual(options['query_status'],'unknown')
        self.assertEqual(options['goals'][0]['whole_route_risk'],'unknown')
        self.assertNotIn('position',options['goals'][0]['first_steps'][0])
        self.assertEqual(context['previous_plan']['tasks']['green-2']['task_revision'],9)

    def test_preserves_failure_and_actual_support_evidence(self):
        evidence=dict(recent_assigned_shot=False,native_lane='blocked')
        result=build(dict(execution={'g':dict(local_failure=dict(phase='failed',reason='blocked',duration_s=9),
            task_execution=dict(phase='reassess',reason='dependency_timeout'))},
            cooperation_board={'g':dict(fire_evidence=evidence)}))
        self.assertEqual(result['execution']['g']['failure']['reason'],'blocked')
        self.assertEqual(result['execution']['g']['cooperation']['fire_evidence'],evidence)
        self.assertEqual(result['execution']['g']['task']['phase'],'reassess')

    def test_explicit_living_roster_removes_dead_task_and_execution_context(self):
        context=dict(living_controlled_unit_ids=['green-2'],
            previous_plan=dict(tasks={'green-1':dict(command='flank'),
                                      'green-2':dict(command='support')}),
            execution={'green-1':dict(no_movement_seconds=30),
                       'green-2':dict(no_movement_seconds=2)},
            threat_forecast={'green-1':dict(sampled_at=3),
                             'green-2':dict(sampled_at=4)},
            region_opportunities=dict(route_options={'green-1':[],'green-2':[]}))
        result=build(context)
        self.assertEqual(result['living_controlled_unit_ids'],['green-2'])
        for key in ('previous_plan','execution','current_threats','maneuver_options'):
            rows=result[key]['tasks'] if key=='previous_plan' else result[key]
            self.assertEqual(set(rows),{'green-2'})
        self.assertIn('green-1',context['previous_plan']['tasks'])
