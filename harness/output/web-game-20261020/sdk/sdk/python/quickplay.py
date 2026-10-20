"""Quickplay Game Protocol v1 SDK. Standard library only; provider keys stay in harness."""
from concurrent.futures import Future, TimeoutError
import json
import queue
import sys
import threading
import uuid

PROTOCOL = 'quickplay-game/v1'


class Game:
    supports_answer_progress = True
    def __init__(self):
        message = json.loads(sys.stdin.readline())
        if message.get('type') != 'start' or message.get('protocol') != PROTOCOL:
            raise RuntimeError('quickplay_protocol_mismatch')
        self.session_id = message['sessionId']
        self.config = message['config']
        self.stopped = threading.Event()
        self.inputs = queue.Queue()
        self._pending = {}
        self._answer_queues = {}
        self._lock = threading.RLock()
        self._send(dict(type='ready', protocol=PROTOCOL))
        threading.Thread(target=self._read, daemon=True).start()

    def _send(self, message):
        with self._lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False, allow_nan=False) + '\n')
            sys.stdout.flush()

    def _read(self):
        try:
            for line in sys.stdin:
                message = json.loads(line)
                if message['type'] == 'stop':
                    break
                if message['type'] in ('input', 'action'):
                    self.inputs.put(message)
                elif message['type'] == 'response-progress':
                    with self._lock:
                        answers = self._answer_queues.get(message['id'])
                    if answers is not None:
                        answers.put((message['key'], message['answer']))
                elif message['type'] == 'response':
                    with self._lock:
                        pending = self._pending.pop(message['id'], None)
                    if pending:
                        if 'error' in message:
                            pending.set_exception(RuntimeError(message['error']))
                        else:
                            pending.set_result(dict(message['response'], requestId=message['id']))
        finally:
            self.stopped.set()
            with self._lock:
                for pending in self._pending.values():
                    pending.set_exception(RuntimeError('session_stopped'))
                self._pending.clear()

    def ask(self, state, questions, role=None, on_answer=None):
        """Return typed answers + usage/provenance + requestId for an engine receipt."""
        with self._lock:
            if self.stopped.is_set():
                raise RuntimeError('session_stopped')
            request_id = str(uuid.uuid4())
            pending = self._pending[request_id] = Future()
            answers = queue.Queue()
            if on_answer is not None: self._answer_queues[request_id] = answers
            self._send(dict(type='request', id=request_id, state=state, questions=questions,
                            **({'role': role} if role else {}), **({'progress': True} if on_answer is not None else {})))
        def drain():
            while not answers.empty():
                key, answer = answers.get_nowait()
                on_answer(key, answer)
        try:
            if on_answer is None: return pending.result()
            while True:
                drain()
                try:
                    result = pending.result(timeout=.025)
                    drain()
                    return result
                except TimeoutError:
                    if pending.done(): raise
        finally:
            if on_answer is not None:
                with self._lock: self._answer_queues.pop(request_id, None)

    def publish(self, observation, payload=None):
        if not self.stopped.is_set():
            self._send(dict(type='state', observation=observation, payload=payload))

    def record(self, record):
        if not self.stopped.is_set():
            self._send(dict(type='record', record=record))

    def finish(self, outcome, error=None):
        if not self.stopped.is_set():
            self._send(dict(type='end', outcome=outcome, **({'error': error} if error else {})))
            self.stopped.wait(2)
