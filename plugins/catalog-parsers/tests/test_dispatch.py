"""Fast unit: native output initialization and tamper protection; expected <1s, max 5s."""
import hashlib,json
from pathlib import Path
import pytest
from catalog_parsers.dispatch import parse_external


def test_launcher_does_not_pollute_fresh_output_and_checks_reused_hashes(tmp_path,monkeypatch):
    source=tmp_path/'source.pdf';source.write_bytes(b'fixture')
    config=tmp_path/'executors.json';config.write_text(json.dumps({'img2table':{'python':'fixture-python','version':'2.0.0'}}))
    monkeypatch.setenv('CATALOG_PARSER_EXECUTORS',str(config))
    def execute(args,**kwargs):
        out=Path(args[args.index('--output')+1]);assert not list(out.iterdir())
        for name in ('candidate.json','raw.json'):(out/name).write_text('{}')
        receipt={'status':'completed','source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'physical_page':1,'package_version':'2.0.0','candidate_sha256':hashlib.sha256(b'{}').hexdigest(),'raw_sha256':hashlib.sha256(b'{}').hexdigest()}
        (out/'receipt.json').write_text(json.dumps(receipt))
    monkeypatch.setattr('catalog_parsers.dispatch.subprocess.run',execute)
    out=tmp_path/'run';assert parse_external(source,1,'img2table',out)['status']=='completed'
    assert (out/'executor.log').exists()
    assert parse_external(source,1,'img2table',out,resume=True)['status']=='completed'
    (out/'raw.json').write_text('altered')
    with pytest.raises(ValueError,match='tampered'):parse_external(source,1,'img2table',out,resume=True)
