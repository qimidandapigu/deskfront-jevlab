import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from deskfront_test_paths import DESKFRONT_ROOT, DESKFRONT_TOOLS
sys.path.insert(0, str(ROOT / 'src' / 'deskfront'))
sys.path.insert(0, str(DESKFRONT_TOOLS))
from combat_command_validation import validate


class CombatCommandValidationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = DESKFRONT_ROOT / 'tools' / 'server.py'
        spec = importlib.util.spec_from_file_location('deskfront_native_server_validation', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        cls.native_validate = staticmethod(module.validate_command)

    def test_selected_site_passes_native_envelope_and_keeps_engine_fields(self):
        command = dict(action='soldier_order', faction='green', unit_ids=['green-2'],
                       squad_id='green-squad', order_id='order-1', intent='move_to_site',
                       site_id='C1', candidate_query_id='query-1',
                       run_id='run-1', seen_tick=5)
        self.assertEqual(self.native_validate(command, True), 'invalid_soldier_intent')
        self.assertIsNone(validate(command, True, self.native_validate))
        self.assertEqual(command['intent'], 'move_to_site')
        self.assertEqual(command['candidate_query_id'], 'query-1')
        self.assertEqual(validate(dict(command, site_id=''), True, self.native_validate), 'site_id_required')
        self.assertEqual(validate(dict(command, seen_tick='5'), True, self.native_validate), 'observation_required')

    def test_new_emotion_passes_and_dead_remains_engine_only(self):
        command = dict(action='unit_emotion', faction='green', unit_ids=['green-2'],
                       emotion='angry', run_id='run-1', seen_tick=5)
        self.assertEqual(self.native_validate(command, True), 'invalid_emotion')
        self.assertIsNone(validate(command, True, self.native_validate))
        self.assertEqual(command['emotion'], 'angry')
        self.assertEqual(validate(dict(command, emotion='dead'), True, self.native_validate), 'invalid_emotion')

    def test_satchel_passes_native_envelope_and_requires_real_target(self):
        command = dict(action='soldier_order', faction='green', unit_ids=['green-2'],
                       squad_id='green-squad', order_id='order-1', intent='satchel',
                       target_id='red-tank-1', run_id='run-1', seen_tick=5)
        self.assertEqual(self.native_validate(command, True), 'invalid_soldier_intent')
        self.assertIsNone(validate(command, True, self.native_validate))
        self.assertEqual(command['intent'], 'satchel')
        self.assertEqual(validate(dict(command, target_id=''), True, self.native_validate), 'target_required')
        self.assertEqual(validate(dict(command, seen_tick='5'), True, self.native_validate), 'observation_required')


if __name__ == '__main__':
    unittest.main()
