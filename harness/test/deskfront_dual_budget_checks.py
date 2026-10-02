import sys
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'deskfront'))
from human_squad import SharedRequestBudget

class DualBudgetTests(unittest.TestCase):
    def test_concurrent_factions_share_a_hard_total(self):
        budget = SharedRequestBudget(80)
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: budget.claim(), range(500)))
        self.assertEqual(sum(claims), 80)
        self.assertEqual(budget.used, 80)
        self.assertFalse(budget.claim())

if __name__ == '__main__': unittest.main()
