from catalog_json.reconciliation.compare import compare_facts, designation, property_label, unit_identity, value_identity
import json
import zipfile


def fact(side, name, value, **extra):
    return dict(side=side, kind='model_parameter', source_sha256='source',
                physical_pages=[78], owner='C3', name=name, value=value,
                unit='мм', condition='', fact_id=side+name, **extra)


def test_geometry_capitals_and_confusable_codes_stay_distinct():
    assert property_label('D') != property_label('d')
    assert property_label('Диаметр D1, мм', 'мм') != property_label('Диаметр d1, мм', 'мм')
    assert designation('C3') != designation('С3')
    assert designation('Ab') != designation('AB')
    assert unit_identity('МПа') != unit_identity('мПа')


def test_typed_scalar_representation_is_retained_as_a_case():
    left = fact('ours', 'D', 12)
    right = fact('oleg', 'D', '12,0')
    ledger, cases = compare_facts([left, right])
    assert ledger[0]['status'] == 'representation_difference'
    assert cases[0]['ours'][0]['value'] == 12
    assert cases[0]['oleg'][0]['value'] == '12,0'
    assert value_identity('0012') != value_identity(12)


def test_overlapping_observations_are_all_kept_and_disagreement_not_hidden():
    left = fact('ours', 'D', '12')
    right = fact('oleg', 'D', '12')
    duplicate = {**right, 'fact_id': 'second-window', 'value': '13'}
    ledger, cases = compare_facts([left, right, duplicate])
    assert ledger[0]['status'] == 'ambiguous_alignment'
    assert len(cases[0]['oleg']) == 2


def test_empty_source_location_is_not_turned_into_a_fake_page():
    left = fact('ours', 'D', '12')
    right = {**fact('oleg', 'D', '12'), 'physical_pages': []}
    ledger, _ = compare_facts([left, right])
    assert [x['status'] for x in ledger] == ['unmatched_ours_observation', 'unmatched_oleg_observation']


def test_parallel_manufacturers_do_not_borrow_each_others_values(tmp_path):
    from catalog_json.reconciliation.compare import load_facts
    source = 'a' * 64
    oleg = tmp_path / 'oleg'; oleg.mkdir()
    (oleg / 'sources.json').write_text(json.dumps({'sources': [{'id':'s','sha256':source}]}))
    def write_rows(name, rows):
        (oleg / (name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows))
    write_rows('product_groups', [{'id':'g','raw':{'title':'Comparison','evidence':[{'page':1}]}}])
    write_rows('products', [{'id':m,'source_id':'s','window_id':'w','group_id':'g',
                            'raw':{'designation':m,'evidence':[{'page':1}]}} for m in ('A-10','B-20')])
    write_rows('characteristics', [{'id':m+'-load','source_id':'s','window_id':'w','group_id':'g','product_id':m,
         'raw':{'name':'Load','raw_value':v,'unit':'кН','condition':'','evidence':[{'page':1}],
                'header_path':[{'role':'group','raw_text':brand}]}}
         for m,v,brand in [('A-10','12','Brand A'),('B-20','20','Brand B')]])
    write_rows('group_characteristics', [])
    columns=[{'id':'a','label':'Brand A','unit':None},
             {'id':'av','label':'Load','unit':'кН','group':'Brand A'},
             {'id':'b','label':'','unit':None,'group':'Brand B'},
             {'id':'bv','label':'Load','unit':'кН','group':'Brand B'}]
    table={'columns':columns,'rows':[{'cells':[{'column_id':c['id'],'value':v,'state':'value'}
                    for c,v in zip(columns,['A-10','12','B-20','20'])]}]}
    raw={'catalogs':[{'id':'test','source':{'sha256':source},'pages':[{'pdf_page':1,'candidate_sha256':'b'*64,
        'reviewed_current_content':True,'content':{'tables':[table]}}]}]}
    ours=tmp_path/'ours.zip'
    with zipfile.ZipFile(ours,'w') as z:z.writestr('all-catalogues-980-pages.json',json.dumps(raw))
    facts,_,_=load_facts(oleg,ours)
    parameters=[f for f in facts if f['side']=='ours' and f['kind']=='model_parameter']
    assert [(f['owner'],f['value'],f['owner_scope']) for f in parameters]==[('A-10','12','Brand A'),('B-20','20','Brand B')]
    ledger,_=compare_facts(facts)
    assert all(r['status']=='exact_agreement' for r in ledger if r['ours_fact_id'] in {f['fact_id'] for f in parameters})


def test_undeclared_manufacturer_scope_cannot_be_auto_accepted():
    left={**fact('ours','Load','12'),'owner_scope':'Brand A'}
    right=fact('oleg','Load','12',raw={})
    ledger,_=compare_facts([left,right])
    assert ledger[0]['status']=='ambiguous_alignment'
