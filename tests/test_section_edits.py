"""Fast unit: partial section edits must not destroy a delivered page; expected<1s/max5s."""
import json
from catalog_json.tools import CatalogTools
from catalog_json.schema import Figure,TextBlock
from test_tools import pdf
from test_contract import content


def worker(tmp_path):
    t=CatalogTools(pdf(tmp_path),tmp_path/'out',model='test',contract_sha256='contract')
    t.render(1);t.direct(1);return t


def test_full_save_then_figure_edit_preserves_tables_text_and_metadata(tmp_path):
    t=worker(tmp_path);d=content();d.printed_page='76';d.text_blocks=[TextBlock(kind='paragraph',text='Complete original')];d.source_notes=['Source issue'];d.uncertainties=['Unresolved feature'];d.figures=[Figure(title='View',description='Original',labels=['H±2'])]
    assert t.save(1,d.model_dump_json(),'page')['saved']
    f=d.figures[0].model_copy(update={'description':'Source-grounded revised view'})
    assert t.section(1,'figures',0,f.model_dump_json())['saved']
    assert t.finalize(1,d.title)['saved']
    saved=json.loads((t.work(1)/'candidate-0.json').read_text())
    assert saved['tables']==d.model_dump()['tables'] and saved['text_blocks']==d.model_dump()['text_blocks']
    assert saved['printed_page']=='76' and saved['source_notes']==d.source_notes and saved['uncertainties']==d.uncertainties
    assert saved['figures'][0]['description']==f.description


def test_full_save_supersedes_older_draft_section(tmp_path):
    t=worker(tmp_path);d=content()
    stale=d.tables[0].model_copy(deep=True);stale.rows[0].cells[0].value=999
    assert t.section(1,'tables',0,stale.model_dump_json())['saved']
    assert t.save(1,d.model_dump_json(),'page')['saved']
    assert t.section(1,'figures',0,Figure(title='View',description='Only an edit',labels=[]).model_dump_json())['saved']
    assert t.finalize(1,d.title)['saved']
    assert json.loads((t.work(1)/'candidate-0.json').read_text())['tables']==d.model_dump()['tables']


def test_known_source_grid_cannot_be_saved_as_no_tables(tmp_path):
    t=worker(tmp_path);t.grids[1]=[{'row_count':2,'column_count':2,'expanded_rows':[['item1','10'],['item2','20']],'unknown_cells':[],'merged_cells':[]}]
    d=content();d.tables=[]
    result=t.save(1,d.model_dump_json(),'page')
    assert not result['saved'] and result['direct_grid_differences']


def test_repair_edit_can_preserve_an_explicitly_read_bound_prior_attempt(tmp_path):
    t=worker(tmp_path);d=content();d.text_blocks=[TextBlock(kind='paragraph',text='Retain source text')]
    assert t.save(1,d.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,attempt=1,model=t.model,contract_sha256=t.contract_sha256)
    r.render(1);r.direct(1);r.read(1,'page')
    assert r.section(1,'figures',0,Figure(title='View',description='Verified repair',labels=[]).model_dump_json())['saved']
    assert r.finalize(1,d.title)['saved']
    saved=json.loads((r.work(1)/'candidate-1.json').read_text())
    assert saved['tables']==d.model_dump()['tables'] and saved['text_blocks']==d.model_dump()['text_blocks']


def test_unbound_older_candidate_cannot_be_used_as_edit_baseline(tmp_path):
    t=worker(tmp_path);d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,attempt=1,model='different-model',contract_sha256=t.contract_sha256)
    r.render(1);r.direct(1);r.read(1,'page')
    assert 1 not in r.edit_baselines


def test_section_modified_outside_tool_is_rejected(tmp_path):
    t=worker(tmp_path);d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    assert t.section(1,'figures',0,Figure(title='View',description='Saved edit',labels=[]).model_dump_json())['saved']
    (t.work(1)/'sections-0/figures/0000.json').write_text(Figure(title='Unbound',description='',labels=[]).model_dump_json())
    assert not t.finalize(1,d.title)['saved']
    assert json.loads((t.work(1)/'candidate-0.json').read_text())==d.model_dump()


def test_unbound_read_does_not_silently_turn_partial_edit_into_empty_page(tmp_path):
    t=worker(tmp_path);d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,attempt=1,model='different',contract_sha256=t.contract_sha256)
    r.render(1);r.direct(1);r.read(1,'page')
    r.section(1,'figures',0,Figure(title='Edit',description='',labels=[]).model_dump_json())
    assert not r.finalize(1,d.title)['saved']
    assert not (r.work(1)/'candidate-1.json').exists()


def test_future_attempt_is_not_adopted_as_prior_baseline(tmp_path):
    t=worker(tmp_path);t.attempt=5;d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,attempt=1,model=t.model,contract_sha256=t.contract_sha256)
    r.render(1);r.direct(1);r.read(1,'page')
    assert not r.finalize(1,d.title)['saved']


def test_restored_old_full_save_is_not_the_current_baseline(tmp_path):
    t=worker(tmp_path);d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    old=(t.work(1)/'candidate-0.json').read_bytes();d.tables[0].rows[0].cells[0].value=20
    assert t.save(1,d.model_dump_json(),'page')['saved']
    (t.work(1)/'candidate-0.json').write_bytes(old)
    t.section(1,'figures',0,Figure(title='Edit',description='',labels=[]).model_dump_json())
    assert not t.finalize(1,d.title)['saved']


def test_explicit_new_construction_rebuilds_sections_without_unbound_copy(tmp_path):
    t=worker(tmp_path);d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,attempt=1,model='new',contract_sha256='new-contract')
    r.render(1);r.direct(1);r.read(1,'page')
    r.section(1,'tables',0,d.tables[0].model_dump_json())
    assert r.finalize(1,d.title,preserve_existing=False)['saved']
    assert json.loads((r.work(1)/'candidate-1.json').read_text())['tables']==d.model_dump()['tables']


def test_prior_read_baseline_rechecks_latest_save_before_finalize(tmp_path):
    t=worker(tmp_path);d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    old=(t.work(1)/'candidate-0.json').read_bytes()
    r=CatalogTools(t.source,t.output,attempt=1,model=t.model,contract_sha256=t.contract_sha256)
    r.render(1);r.direct(1);r.read(1,'page')
    d.tables[0].rows[0].cells[0].value=20
    assert t.save(1,d.model_dump_json(),'page')['saved']
    (t.work(1)/'candidate-0.json').write_bytes(old)
    r.section(1,'figures',0,Figure(title='Edit',description='',labels=[]).model_dump_json())
    assert not r.finalize(1,d.title)['saved']
    assert not (r.work(1)/'candidate-1.json').exists()


def test_missing_new_full_save_does_not_revive_prior_read_baseline(tmp_path):
    t=worker(tmp_path);d=content();assert t.save(1,d.model_dump_json(),'page')['saved']
    r=CatalogTools(t.source,t.output,attempt=1,model=t.model,contract_sha256=t.contract_sha256)
    r.render(1);r.direct(1);r.read(1,'page')
    d.tables[0].rows[0].cells[0].value=20
    assert r.save(1,d.model_dump_json(),'page')['saved']
    (r.work(1)/'candidate-1.json').unlink()
    r.section(1,'figures',0,Figure(title='Edit',description='',labels=[]).model_dump_json())
    assert not r.finalize(1,d.title)['saved']
    assert not (r.work(1)/'candidate-1.json').exists()
