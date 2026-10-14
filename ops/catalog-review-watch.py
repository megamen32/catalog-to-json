#!/usr/bin/env python3
"""Half-hour wake of the exact catalogue owner through the existing Herder API."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.tmp/catalog-review-watch'
THREAD = os.environ['CATALOG_REVIEW_THREAD_ID']
if not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', THREAD):
    raise ValueError('An exact native catalogue owner session is required')
URL = 'http://127.0.0.1:18787'
LIMIT = 65536


def save(data):
    temp = STATE / 'last.json.new'
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    temp.replace(STATE / 'last.json')


def session_state():
    with urllib.request.urlopen(URL + '/api/sessions/codex/' + THREAD, timeout=5) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise RuntimeError('Native session metadata exceeded budget')
    session = json.loads(raw)['session']
    meta = session.get('meta', {})
    if (session.get('id') != THREAD or session.get('harness') != 'codex'
            or meta.get('nativeSessionId') != THREAD or meta.get('transport') != 'codex-app-server'):
        return 'unknown'
    if (meta.get('humanStopHeld') is not False or session.get('needsPermission')
            or session.get('status') in {'stopped', 'needs_input'}
            or '/archived_sessions/' in str(meta.get('path', ''))):
        return 'waiting_for_human'
    if session.get('status') == 'running':
        return 'active_work'
    if session.get('status') != 'idle':
        return 'unknown'
    if meta.get('nativeLastTurn', {}).get('status') in {'interrupted', 'failed'}:
        return 'waiting_for_human'
    return 'idle'


def deliver(prompt, input_id):
    # Direct user mandate: wake this same catalogue task every30min. Never
    # override a later human stop: both preceding reads must permit delivery.
    arguments = {'sessionId': THREAD, 'harness': 'codex', 'mode': 'queue',
                 'humanRequested': True, 'inputId': input_id, 'message': prompt}
    body = {'jsonrpc': '2.0', 'id': input_id, 'method': 'tools/call',
            'params': {'name': 'send_message', 'arguments': arguments}}
    request = urllib.request.Request(URL + '/mcp', data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream'})
    with urllib.request.urlopen(request, timeout=15) as response:
        raw = response.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise RuntimeError('Native delivery receipt exceeded budget')
    packets = [json.loads(line[5:]) for line in raw.splitlines() if line.startswith(b'data:')]
    if not packets:
        packets = [json.loads(raw)]
    for packet in packets:
        if packet.get('error'):
            raise RuntimeError('Native delivery rejected')
        result = packet.get('result', {})
        text = '\n'.join(c.get('text', '') for c in result.get('content', []) if c.get('type') == 'text')
        match = re.search(r'Native admission receipt: (\{[^\n]+\})', text)
        if match:
            receipt = json.loads(match.group(1))
            if receipt.get('admitted') is True and receipt.get('inputId') == input_id and receipt.get('turnId'):
                return receipt
    raise RuntimeError('Native admission not proven; do not replay')


def main():
    if os.uname().nodename != 'roomhacker-server-100':
        raise RuntimeError('Use the canonical server100 owner transport')
    os.umask(0o077)
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'producer.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        previous = json.loads((STATE / 'last.json').read_text()) if (STATE / 'last.json').exists() else {}
        state = session_state()
        result = {'observed_unix': time.time(), 'session_id': THREAD, 'status': state,
                  'previous_delivery': previous.get('previous_delivery')}
        if state != 'idle' or '--check' in sys.argv:
            save(result)
            print(json.dumps(result, ensure_ascii=False))
            return
        prompt = (ROOT / 'ops/catalog-review-watch.prompt.txt').read_text()
        slot = int(time.time() // 1800)
        input_id = 'catalog-review-' + hashlib.sha256((THREAD + str(slot) + prompt).encode()).hexdigest()
        prior = result['previous_delivery'] or {}
        if prior.get('status') == 'unknown' or prior.get('input_id') == input_id:
            result['status'] = 'delivery_unresolved' if prior.get('status') == 'unknown' else 'already_admitted'
        elif session_state() == 'idle':
            result['previous_delivery'] = {'input_id': input_id, 'status': 'unknown', 'attempted_unix': time.time()}
            save(result)  # An uncertain external delivery must never be replayed.
            receipt = deliver(prompt, input_id)
            result['previous_delivery'].update(status='admitted', receipt=receipt)
            result['status'] = 'started'
        else:
            result['status'] = 'state_changed'
        save(result)
        print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
