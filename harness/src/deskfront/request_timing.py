"""Wall-clock request timing including SDK/transport/provider, excluding local validation."""
import time

def measured_ask(game,context,questions,samples):
    start=time.monotonic();wall=time.time();response=None;error=None
    try:
        response=game.ask(context,questions,role='commander')
        return response
    except Exception as exc:
        error=type(exc).__name__
        raise
    finally:
        row=dict(type='commander-request-timing',started_unix=wall,finished_unix=time.time(),elapsed_ms=round((time.monotonic()-start)*1000,2),state_time=context.get('time'),request_id=(response or {}).get('requestId'),status='error' if error else 'returned',error_type=error)
        samples.append(row)
        game.record(row)

def summary(samples):
    ok=[r['elapsed_ms'] for r in samples if r['status']=='returned']
    return dict(requests=len(samples),returned=len(ok),failed=len(samples)-len(ok),average_ms=round(sum(ok)/len(ok),2) if ok else None,min_ms=min(ok) if ok else None,max_ms=max(ok) if ok else None,last_ms=samples[-1]['elapsed_ms'] if samples else None,basis='wall-clock SDK request round trip, not pure model generation')
