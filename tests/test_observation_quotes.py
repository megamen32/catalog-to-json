"""Fast unit: blind branding must remain a source quote; expected <1s, max5s."""
import json
import pymupdf
from catalog_json.schema import PageContent,TextBlock
from catalog_json.tools import CatalogTools


BOX=[0.,0.,1.,1.]
QUOTE='PRODUCTION OF HIGH-VOLTAGE INSULATORS'

def setup(tmp_path,text=QUOTE):
    source=tmp_path/'source.pdf'
    with pymupdf.open() as d:
        p=d.new_page()
        if text:p.insert_text((30,50),text,fontsize=10)
        d.save(source)
    t=CatalogTools(source,tmp_path/'out',role='reviewer');t.render(1);t.region(1,BOX)
    return t

def observation(text=QUOTE,notes=None):
    return PageContent(title='Source',text_blocks=[TextBlock(kind='branding',text=text)],tables=[],figures=[],source_notes=notes or [])

def proof(text=QUOTE,basis='text_layer',conflict=None):
    return [{'block_index':0,'box':BOX,'visible_quote':text,'basis':basis,'conflict':conflict}]

def test_translated_branding_refused_before_blind_save(tmp_path):
    t=setup(tmp_path);wrong='ПРОИЗВОДСТВО HIGH-VOLTAGE INSULATORS'
    result=t.save(1,observation(wrong).model_dump_json(),'observation',literal_quotes=proof(wrong))
    assert not result['saved'];assert not (t.work(1)/'source-observation-0.json').exists()
    assert result['quote_evidence'][0]['text_layer_quote'].strip()==QUOTE

def test_literal_branding_and_quote_evidence_retained(tmp_path):
    t=setup(tmp_path);assert t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof())['saved']
    evidence=json.loads((t.work(1)/'source-observation-quotes-0.json').read_text())
    assert evidence['quotes'][0]['visible_quote']==QUOTE
    assert evidence['quotes'][0]['status']=='agree'


def test_quote_box_may_include_neighboring_page_number(tmp_path):
    t=setup(tmp_path,'100 '+QUOTE+' 101')
    result=t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof())
    assert result['saved']
    q=json.loads((t.work(1)/'source-observation-quotes-0.json').read_text())['quotes'][0]
    assert q['status']=='agree' and q['text_layer_quote'].strip()=='100 '+QUOTE+' 101'


def test_neighboring_text_cannot_hide_changed_or_partial_quote(tmp_path):
    for n,wrong in enumerate(['PRODUCTION OF HIGH-VOLTAGE INSULATOR',
                              'PRODUCTION OF INSULATORS',
                              'PRODUCTION OF HIGH+VOLTAGE INSULATORS',
                              'OF HIGH-VOLTAGE INSULATORS EXTRA']):
        root=tmp_path/str(n);root.mkdir();t=setup(root,'100 '+QUOTE+' 101')
        assert not t.save(1,observation(wrong).model_dump_json(),'observation',literal_quotes=proof(wrong))['saved']

def test_missing_quote_proof_and_wrong_block_quote_refused(tmp_path):
    t=setup(tmp_path)
    assert not t.save(1,observation().model_dump_json(),'observation')['saved']
    assert not t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof('Translated text'))['saved']

def test_native_layer_conflict_requires_explicit_note_and_vision(tmp_path):
    t=setup(tmp_path,'HIDDEN LEGACY WORDING');note='The original image differs from its hidden text layer.'
    assert not t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof(basis='vision',conflict=note))['saved']
    assert t.save(1,observation(notes=[note]).model_dump_json(),'observation',literal_quotes=proof(basis='vision',conflict=note))['saved']
    q=json.loads((t.work(1)/'source-observation-quotes-0.json').read_text())['quotes'][0]
    assert q['status']=='conflict' and q['visible_quote']==QUOTE and q['text_layer_quote'].strip()=='HIDDEN LEGACY WORDING'

def test_vector_quote_is_vision_evidence_not_native_mismatch(tmp_path):
    t=setup(tmp_path,'')
    assert not t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof())['saved']
    assert t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof(basis='vision'))['saved']

def test_branding_quote_requires_exact_region_and_valid_indices(tmp_path):
    t=setup(tmp_path);p=proof();p[0]['box']=[0.,0.,.5,.5]
    assert not t.save(1,observation().model_dump_json(),'observation',literal_quotes=p)['saved']
    for index in [True,1,-1]:
        p=proof();p[0]['block_index']=index
        assert not t.save(1,observation().model_dump_json(),'observation',literal_quotes=p)['saved']

def test_correction_uses_same_guard_and_keeps_blind_quote(tmp_path):
    t=setup(tmp_path);assert t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof())['saved']
    (t.work(1)/'candidate-0.json').write_text(observation().model_dump_json());t.read(1,'page');t.region(1,BOX)
    wrong='ПРОИЗВОДСТВО HIGH-VOLTAGE INSULATORS'
    assert not t.correct_observation(1,observation(wrong).model_dump_json(),'Reinspected quote',literal_quotes=proof(wrong))['saved']
    assert t.correct_observation(1,observation().model_dump_json(),'Original quote confirmed',literal_quotes=proof())['saved']
    assert (t.work(1)/'source-observation-quotes-0.json').exists()
    assert (t.work(1)/'source-observation-quotes-0-revision-1.json').exists()

def test_correction_quote_needs_fresh_matching_box(tmp_path):
    t=setup(tmp_path);assert t.save(1,observation().model_dump_json(),'observation',literal_quotes=proof())['saved']
    (t.work(1)/'candidate-0.json').write_text(observation().model_dump_json());t.read(1,'page')
    t.region(1,[0.,0.,.5,.5])
    assert not t.correct_observation(1,observation().model_dump_json(),'Other source region was reinspected',literal_quotes=proof())['saved']

def test_quote_guard_does_not_replace_numeric_or_figure_guards(tmp_path):
    from catalog_json.schema import Figure
    from catalog_json.audit import compare_source
    t=setup(tmp_path);source=observation();source.figures=[Figure(title='Drawing',description='',labels=['H±2'])]
    assert t.save(1,source.model_dump_json(),'observation',literal_quotes=proof())['saved']
    candidate=source.model_copy(deep=True);candidate.figures[0].labels=['H+2']
    assert any(d['path']=='figures[0].labels' for d in compare_source(source,candidate))

def test_observation_helper_changes_execution_contract(tmp_path,monkeypatch):
    from catalog_json.agents import AgentPair
    config=tmp_path/'config.yaml';config.write_text('{}')
    args=(config,'test-extractor','test-reviewer')
    first=AgentPair(*args).contract_digest;original=__import__('pathlib').Path.read_text
    def changed(path,*a,**kw):
        result=original(path,*a,**kw)
        return result+'\n# changed observer logic' if path.name=='observation_quotes.py' else result
    monkeypatch.setattr(__import__('pathlib').Path,'read_text',changed)
    assert AgentPair(*args).contract_digest!=first

def test_paged_quote_errors_cannot_look_like_successful_save(tmp_path,monkeypatch):
    t=setup(tmp_path)
    monkeypatch.setattr(t,'source_payload',lambda *args:{'paged':True,'artifact_id':'diagnostic-errors'})
    refused=t.save(1,observation().model_dump_json(),'observation')
    assert refused['paged'] and refused['saved'] is False and 'NOT saved' in refused['error']
    assert not (t.work(1)/'source-observation-0.json').exists()
