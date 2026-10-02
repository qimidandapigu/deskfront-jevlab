"""Regression for actual response -> strict game validation -> submission boundary."""
import copy
import sys
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src/deskfront'))
sys.path.insert(0,str(DESKFRONT_TOOLS))
from deskfront_tactics_checks import unit
from deskfront_world_pipeline_checks import Game
from team_executor import TeamExecutor
from world.director import WorldDirector, MacroBridge


class ExecutionChecks(unittest.TestCase):
    def resolve(self, command):
        u=unit('green-1')
        state=dict(run_id='r',tick=10,units=[u],bounds=[-2,-2,3,3],
            control={'green':'lm'},control_epochs={'green':1})
        detail=dict(command=command,requires_precise_arrival=True)
        payload=dict(state=dict(executors={'green-1':dict(command_candidates={'selected':command},
            command_details={'selected':detail})}))
        coord=SimpleNamespace(team='green',version=1,budget_exhausted=False,game=Mock())
        c=SimpleNamespace(coordination=coord,units={},used=1,metrics={},
            config=dict(max_requests=100),call_log=Mock(),origin='quickplay_jev',
            state=SimpleNamespace(lock=threading.Lock(),state=state),execution_records={})
        def submit(s,u,decision,origin,now,tick,selection):
            c.execution_records[(u['id'],tick)]=dict(status='submitted',command_id=None)
        c._submit=Mock(side_effect=submit)
        future=Future();future.set_result(dict(answers={'green-1':dict(type='choice',choice='selected',confidence=1,probabilities={'selected':1})}))
        ex=TeamExecutor(c,'green-1');ex.next_at=100
        ex.pending=dict(future=future,payload=payload,id=1,members=['green-1'],run='r',
            tick=10,epoch=1,version=1,started=10)
        with patch('team_executor.time.monotonic',return_value=10.2):ex.tick(state,{},0)
        return c

    def test_internal_key_reaches_receipt_matching_not_game_schema(self):
        c=self.resolve(dict(action='move',intent='advance',position=[.2,.2]))
        c._submit.assert_called_once()
        args,kwargs=c._submit.call_args
        self.assertNotIn('_choice_key',args[2])
        self.assertEqual(kwargs['selection']['key'],'selected')
        self.assertTrue(kwargs['selection']['candidate']['requires_precise_arrival'])

    def test_unknown_game_fields_remain_rejected_and_reason_visible(self):
        c=self.resolve(dict(action='move',intent='advance',position=[.2,.2],unsupported=True))
        c._submit.assert_not_called()
        row=c.call_log.update.call_args.kwargs['unit_executions']['green-1']
        self.assertEqual(row['validation_error'],'invalid_decision_fields')


class OpeningChecks(unittest.TestCase):
    def setUp(self):
        self.game=Game();self.commands=[]
        self.s=dict(run_id='r',tick=1,time=0,paused=False,units=[dict(id=str(i),faction='green',hp=50,max_hp=50) for i in range(4)],
            world_growth=dict(enabled=True,revision=0,phase='ready',completed=[],options=['gate_north_books_depth_wide']))
        self.state=SimpleNamespace(lock=threading.Lock(),state=self.s,instance_id='i',updated=time.monotonic(),results={})
        self.state.submit=lambda c:(self.commands.append(copy.deepcopy(c)) or (202,dict(id='opening')))
        self.d=WorldDirector(MacroBridge(self.state,self.game),self.game);self.d.observe(self.s)

    def test_empty_start_uses_two_agents_without_deepseek(self):
        self.assertFalse(self.commands)
        self.assertFalse(self.d.analyze())
        self.d.step(dict(run_id='r',instance_id='i'))
        self.assertEqual(self.game.calls,[None,None,None])
        self.assertEqual(len(self.commands),1)
        self.assertEqual((self.commands[0]['friendly_count'],self.commands[0]['enemy_count']),(0,4))
        self.assertEqual(self.commands[0]['assembly_kind'],'region_graph_v1')
        with self.assertRaisesRegex(ValueError,'world_submission_pending'):
            self.d.step(dict(run_id='r',instance_id='i'))

    def test_paused_start_does_not_request_models(self):
        self.s['paused']=True
        with self.assertRaisesRegex(ValueError,'world_not_ready'):
            self.d.step(dict(run_id='r',instance_id='i'))
        self.assertFalse(self.game.calls)

if __name__=='__main__':unittest.main()
