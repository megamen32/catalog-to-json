"""Fast unit: interrupted storage must not acknowledge a committed page.

Detects the reboot failure that left an empty review and NUL journal tails.
Expected 1 second; maximum 10 seconds. Native transport is checked separately.
"""
import json
import os
import hashlib
import pytest

from catalog_json.tools import CatalogTools, write_json


def test_failed_storage_flush_preserves_previous_complete_snapshot(tmp_path, monkeypatch):
    path = tmp_path / 'review.json'
    before = {'verdict': 'revise', 'dimension': '147,5'}
    write_json(path, before)
    def storage_failure(fd):
        raise OSError('simulated storage flush failure')
    monkeypatch.setattr(os, 'fsync', storage_failure)
    with pytest.raises(OSError, match='storage flush failure'):
        write_json(path, {'verdict': 'pass', 'dimension': '14,75'})
    assert json.loads(path.read_text()) == before


def test_saved_snapshot_is_complete_and_utf8(tmp_path):
    path = tmp_path / 'nested' / 'candidate.json'
    value = {'designation': 'ОПН-П-35', 'dimension': '147,5', 'bound': '±2'}
    write_json(path, value)
    assert json.loads(path.read_bytes()) == value
    assert not path.with_suffix('.json.pending').exists()


def test_failed_journal_flush_does_not_grant_inspection(tmp_path, monkeypatch):
    from test_tools import pdf
    tools=CatalogTools(pdf(tmp_path),tmp_path/'output')
    def storage_failure(fd):
        raise OSError('simulated storage flush failure')
    monkeypatch.setattr(os,'fsync',storage_failure)
    with pytest.raises(OSError,match='storage flush failure'):
        tools.log(1,'view_page')
    assert 'view_page' not in tools.seen.get(1,set())


def test_audit_receipt_certifies_bytes_returned_during_atomic_update(tmp_path,monkeypatch):
    from test_tools import pdf
    tools=CatalogTools(pdf(tmp_path),tmp_path/'output')
    path=tools.work(1)/'external-audit.json'
    old={'source_sha256':tools.source_digest,'pdf_page':1,'findings':['old lead']}
    new={**old,'findings':['new lead']}
    write_json(path,old);old_digest=hashlib.sha256(path.read_bytes()).hexdigest()
    real_loads=json.loads;changed=False
    def replace_after_decode(raw,*args,**kwargs):
        nonlocal changed
        value=real_loads(raw,*args,**kwargs)
        if not changed and value==old:
            changed=True;write_json(path,new)
        return value
    monkeypatch.setattr(json,'loads',replace_after_decode)
    result=tools.external_audit(1)
    receipt=real_loads((tools.work(1)/'tools.jsonl').read_text().splitlines()[-1])
    assert result['findings']==old['findings'] and receipt['sha256']==old_digest
    assert hashlib.sha256(path.read_bytes()).hexdigest()!=old_digest
