"""Execution validation against the original destination, not a refreshed shortlist."""
import json
import time
import uuid
from pathlib import Path

def validate_move(spatial_path, state, unit, position, timeout=.8):
    root=Path(spatial_path).parent
    token=uuid.uuid4().hex
    request=dict(id=token,run_id=state['run_id'],unit_id=unit['id'],position=position)
    try:
        temporary=root/('move-check-'+token+'.tmp')
        temporary.write_text(json.dumps(request),encoding='utf-8')
        temporary.replace(root/'move-check-request.json')
        marker=root/('move-check-'+token+'.id.tmp')
        marker.write_text(token,encoding='ascii')
        marker.replace(root/'move-check-request.id')
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                result=json.loads((root/'move-check-response.json').read_text(encoding='utf-8'))
                if result.get('id')==token and result.get('run_id')==state['run_id']:return result
            except (OSError,ValueError):pass
            time.sleep(.015)
    except OSError:pass
    return dict(valid=False,reason='native_validation_timeout',id=token)
