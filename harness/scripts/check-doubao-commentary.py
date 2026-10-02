"""One real TTS request; reads ignored .env and never prints credentials."""
import base64
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
for line in (ROOT / '.env').read_text(encoding='utf-8-sig').splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        name, value = line.split('=', 1)
        os.environ.setdefault(name.strip(), value.strip().strip('\"\''))

text = '注意右侧！绿队正在接近侧面的掩体。这次能不能打开局面，就看正面的队友能否稳住火力了。'
payload = {'user': {'uid': 'quickplay-commentary-probe'}, 'req_params': {
    'text': text, 'speaker': os.environ['DOUBAO_TTS_SPEAKER'],
    'audio_params': {'format': 'mp3', 'sample_rate': 24000},
}}
request = urllib.request.Request(
    'https://openspeech.bytedance.com/api/v3/tts/unidirectional',
    data=json.dumps(payload).encode(), method='POST', headers={
        'Content-Type': 'application/json',
        'X-Api-Key': os.environ['DOUBAO_TTS_API_KEY'],
        'X-Api-Resource-Id': os.environ['DOUBAO_TTS_RESOURCE_ID'],
        'X-Api-Request-Id': str(uuid.uuid4()),
    })
started = time.monotonic()
chunks = []
first_audio_ms = None
completed = False
try:
    with urllib.request.urlopen(request, timeout=40) as response:
        for line in response:
            if not line.strip():
                continue
            event = json.loads(line)
            if event.get('code') not in (0, 20000000):
                print(json.dumps({'ok': False, 'provider_code': event.get('code'),
                                  'message': str(event.get('message', ''))[:400]}, ensure_ascii=False))
                raise SystemExit(1)
            if event.get('data'):
                chunks.append(base64.b64decode(event['data'], validate=True))
                if first_audio_ms is None:
                    first_audio_ms = round((time.monotonic() - started) * 1000)
            if event.get('code') == 20000000:
                completed = True
except urllib.error.HTTPError as error:
    print(json.dumps({'ok': False, 'http_status': error.code,
                     'detail': error.read(2048).decode(errors='replace').replace(os.environ['DOUBAO_TTS_API_KEY'], '[redacted]')}, ensure_ascii=False))
    raise SystemExit(1)
except (urllib.error.URLError, TimeoutError):
    print('{"ok":false,"error":"network_or_timeout"}')
    raise SystemExit(1)
if not completed or not chunks:
    raise SystemExit('TTS stream incomplete or empty; no audio saved')
out = ROOT / 'logs' / 'commentary-voice'
out.mkdir(parents=True, exist_ok=True)
(out / 'sample.mp3').write_bytes(b''.join(chunks))
report = {'ok': True, 'speaker': payload['req_params']['speaker'], 'text': text,
          'first_audio_ms': first_audio_ms, 'total_ms': round((time.monotonic()-started)*1000),
          'bytes': sum(map(len, chunks)), 'audio': str(out / 'sample.mp3'),
          'scope': 'Synthetic commentary text; not live battle commentary or playback latency.'}
(out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
