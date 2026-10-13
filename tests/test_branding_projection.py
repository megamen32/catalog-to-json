"""Fast unit: source-bound branding captions may change representation; expected<1s, max5s."""
from catalog_json.schema import PageContent,TextBlock,Figure
from catalog_json.audit import compare_source
from catalog_json.observation_quotes import branding_quote_evidence
from test_observation_quotes import setup,BOX,QUOTE

def pages(label=QUOTE,kind='branding'):
    source=PageContent(title='Source',text_blocks=[],tables=[],figures=[Figure(title='Raster branding',description='',labels=[label])])
    candidate=PageContent(title='Candidate',text_blocks=[TextBlock(kind=kind,text=label)],tables=[],figures=[])
    return source,candidate

def test_exact_branding_caption_matches_only_with_explicit_source_evidence():
    source,candidate=pages()
    assert compare_source(source,candidate)
    assert not compare_source(source,candidate,branding_figure_quotes={0:{QUOTE}})
    candidate.text_blocks[0].text='ПРОИЗВОДСТВО HIGH-VOLTAGE INSULATORS'
    assert compare_source(source,candidate,branding_figure_quotes={0:{QUOTE}})

def test_branding_caption_cannot_be_rescued_from_ordinary_prose():
    source,candidate=pages(kind='paragraph')
    assert compare_source(source,candidate,branding_figure_quotes={0:{QUOTE}})

def test_engineering_figures_remain_strict_despite_mistagged_kind():
    for label in ['H±2','⌀140','274','50','4 отв.','М10','A','Б','H','≤80','III','I I I','Ⅲ','areaL²','length⁺','Lmax−Lmin','Lmax - Lmin']:
        source,candidate=pages(label)
        assert compare_source(source,candidate,branding_figure_quotes={0:{label}}),label

def test_source_caption_cannot_match_only_a_substring_or_wrong_figure():
    source,candidate=pages('INSTA');candidate.text_blocks[0].text='OTHER-INSTA'
    assert compare_source(source,candidate,branding_figure_quotes={0:{'INSTA'}})
    source,candidate=pages();assert compare_source(source,candidate,branding_figure_quotes={1:{QUOTE}})

def test_figure_brand_quote_has_exact_bbox_and_source_kind(tmp_path):
    t=setup(tmp_path);source,_=pages()
    proof=[{'figure_index':0,'label_index':0,'source_kind':'branding','box':BOX,'visible_quote':QUOTE,'basis':'text_layer','conflict':None}]
    records,errors=branding_quote_evidence(t,1,source,proof)
    assert not errors and records[0]['source_kind']=='branding'
    proof[0]['source_kind']='engineering'
    assert branding_quote_evidence(t,1,source,proof)[1]

def test_numeric_figure_cannot_declare_itself_brand_quote(tmp_path):
    t=setup(tmp_path);source,_=pages('H±2')
    proof=[{'figure_index':0,'label_index':0,'source_kind':'branding','box':BOX,'visible_quote':'H±2','basis':'vision','conflict':None}]
    assert branding_quote_evidence(t,1,source,proof)[1]


def test_interleaved_logo_words_and_split_blocks_are_not_missing_text():
    source,candidate=pages('ФОРЭНЕРГО FORENERGO производственное объединение manufacturing association')
    candidate.text_blocks=[TextBlock(kind='branding',text='FORENERGO manufacturing association'),
                           TextBlock(kind='branding',text='ФОРЭНЕРГО производственное объединение')]
    assert not compare_source(source,candidate,branding_figure_quotes={0:{source.figures[0].labels[0]}})
    source.text_blocks=[TextBlock(kind='branding',text=source.figures[0].labels[0])];source.figures=[]
    assert not compare_source(source,candidate)
    candidate.text_blocks[0].text='FORENERGO association'
    assert compare_source(source,candidate)


def test_branding_word_boundaries_multiplicity_and_engineering_stay_strict():
    from catalog_json.audit import branding_present
    assert not branding_present('INSTA',['OTHER-INSTA'])
    assert not branding_present('ООО ООО ИНСТА',['ООО ИНСТА'])
    source,candidate=pages('Н±2');candidate.text_blocks=[TextBlock(kind='branding',text='Н±2')]
    assert compare_source(source,candidate,branding_figure_quotes={0:{'Н±2'}})
    source.text_blocks=[TextBlock(kind='paragraph',text='изделие первое второе')];source.figures=[]
    candidate.text_blocks=[TextBlock(kind='branding',text='изделие второе первое')]
    assert compare_source(source,candidate)
