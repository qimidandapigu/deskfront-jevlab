"""Thread-safe dashboard records used by the human squad runtime.

This module owns only request/event indexing primitives. It does not know about
models or the engine, so the controller can keep its scheduling responsibilities
separate without changing the public ``human_squad`` import surface.
"""

import copy
import threading

class CallLog:
    """Small dashboard index; full request/response/receipt records use Game.record."""
    def __init__(self):
        self.rows = []
        self.lock = threading.RLock()

    def append(self, row):
        with self.lock:
            value = dict(copy.deepcopy(row), id=len(self.rows) + 1)
            self.rows.append(value)
            return value['id']

    def list(self, before=None, unit='', run='', **_):
        with self.lock:
            rows = [r for r in reversed(self.rows) if (before is None or r['id'] < before)
                    and (not unit or r.get('unit_id') == unit) and (not run or r.get('run_id') == run)]
            return copy.deepcopy(dict(items=rows[:50], units=sorted({r.get('unit_id', '') for r in self.rows}),
                                      next_before=rows[49]['id'] if len(rows) > 50 else None))

    def get(self, ident):
        with self.lock:
            return copy.deepcopy(next((r for r in self.rows if r['id'] == ident), None))

    def since(self, after=0, limit=50):
        """Append-only export cursor; copy only newly appended full records."""
        if type(after) is not int or after < 0 or type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError('invalid_call_log_cursor')
        with self.lock:
            # IDs are the immutable, contiguous append positions. Public
            # list/get remain detached and retain their existing behavior.
            rows = self.rows[after:after + limit]
            return copy.deepcopy(dict(items=rows, next_after=rows[-1]['id'] if rows else after))

    def close(self):
        pass


class SharedRequestBudget:
    """One atomic request allowance for both faction controllers."""
    def __init__(self, limit):
        self.limit, self.used = limit, 0
        self.lock = threading.Lock()

    def claim(self):
        with self.lock:
            if self.used >= self.limit:
                return False
            self.used += 1
            return True


__all__ = ["CallLog", "SharedRequestBudget"]
