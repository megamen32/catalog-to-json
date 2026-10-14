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
    columns=[{'id':'a','label':'Brand\nA','unit':None},
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


def _header_pair():
    group='Остающееся напряжение (кВ), при грозовых импульсах тока длит. 8/20 величиной:'
    left={**fact('ours',group+' 2,5 кА','22,6'), 'unit':'кВ', 'condition':'2,5 кА',
          'column':{'label':group+' 2,5 кА','group':group,'qualifier':'2,5 кА','unit':'кВ'}}
    right={**fact('oleg','2,5 кА','22,6'), 'unit':'кВ',
           'condition':'при грозовых импульсах тока длит. 8/20 величиной 2,5 кА',
           'raw':{'origin':'table_cell','header_path':[
               {'role':'group','raw_text':group,'unit':'кВ','condition':''},
               {'role':'column','raw_text':'2,5 кА','unit':'','condition':'при грозовых импульсах тока длит. 8/20 величиной 2,5 кА'}]}}
    return left,right


def test_unique_explicit_header_address_links_without_discarding_conditions():
    left,right=_header_pair()
    ledger,cases=compare_facts([left,right])
    assert ledger[0]['oleg_fact_ids']==[right['fact_id']]
    assert ledger[0]['status']=='value_or_applicability_conflict'
    assert cases[0]['ours'][0]['condition']=='2,5 кА'
    assert cases[0]['oleg'][0]['condition']==right['condition']


def test_header_address_does_not_choose_a_subrow_or_overlapping_window_by_value():
    left,right=_header_pair()
    second={**left,'fact_id':'second-row','value':'99'}
    ledger,_=compare_facts([left,second,right])
    assert all(not r['oleg_fact_ids'] for r in ledger if r['ours_fact_id'])
    duplicate={**right,'fact_id':'other-window','value':'99'}
    ledger,_=compare_facts([left,right,duplicate])
    assert ledger[0]['oleg_fact_ids']==[]


def test_explicit_header_fallback_uses_same_designation_key_as_primary_matching():
    # Retained OPN p9: Oleg has two spaces before UHL1; our one-space
    # designation already matches in the normal index. The hierarchy fallback
    # must not manufacture unmatched fields for those same identical owners.
    left, right = _header_pair()
    left['owner'] = 'ОПН-П-6/7,2/10/0,8-III УХЛ1'
    right['owner'] = 'ОПН-П-6/7,2/10/0,8-III  УХЛ1'
    ledger, cases = compare_facts([left, right])
    assert ledger[0]['oleg_fact_ids'] == [right['fact_id']]
    assert cases[0]['ours'][0]['owner'].endswith('III УХЛ1')
    assert cases[0]['oleg'][0]['owner'].endswith('III  УХЛ1')
    # An additional variant/window remains ambiguous rather than being chosen
    # by value equality after owner whitespace is normalized.
    duplicate = {**right, 'fact_id': 'another-window', 'value': '99'}
    assert compare_facts([left, right, duplicate])[0][0]['oleg_fact_ids'] == []


def test_header_address_requires_literal_group_qualifier_unit_and_owner():
    left,right=_header_pair()
    variants=[{**right,'owner':'С3'}, {**right,'unit':'мВ'},
              {**right,'raw':{**right['raw'],'header_path':[{'role':'group','raw_text':'Other group'},right['raw']['header_path'][1]]}}]
    for variant in variants:
        assert compare_facts([left,variant])[0][0]['oleg_fact_ids']==[]
    changed={**left,'column':{**left['column'],'qualifier':'35 кА'}}
    assert compare_facts([changed,right])[0][0]['oleg_fact_ids']==[]


def test_same_voltage_leaf_is_not_same_parameter_armature311():
    left={**fact('ours','20 кВ','2,3'),'owner':35,'condition':'для СИП-3-20 кВ',
          'column':{'label':'20 кВ','unit':'мм','group':'Толщина изоляции','qualifier':'для СИП-3-20 кВ'}}
    right={**fact('oleg','20 кВ','11,3-11,7'),'owner':'35',
           'raw':{'header_path':[{'role':'group','raw_text':'Наружный диаметр жилы с изоляцией, мм'},
                                 {'role':'column','raw_text':'20 кВ'}]}}
    ledger,_=compare_facts([left,right])
    assert [r['status'] for r in ledger]==['unmatched_ours_observation','unmatched_oleg_observation']


def test_missing_property_parent_cannot_be_auto_accepted_on_leaf_only():
    left=fact('ours','20 кВ','2,3')
    right=fact('oleg','20 кВ','2,3',raw={'header_path':[{'role':'group','raw_text':'Толщина изоляции'},{'role':'column','raw_text':'20 кВ'}]})
    assert compare_facts([left,right])[0][0]['status']=='ambiguous_alignment'


def _small_input(tmp_path, table, *, models=(), characteristics=()):
    from catalog_json.reconciliation.compare import load_facts
    source='a'*64;oleg=tmp_path/'oleg';oleg.mkdir()
    (oleg/'sources.json').write_text(json.dumps({'sources':[{'id':'s','sha256':source}]}))
    data={'product_groups':[{'id':'g','raw':{'title':'Group','evidence':[{'page':1}]}}],
          'products':[{'id':m,'source_id':'s','window_id':'w','group_id':'g','raw':{'designation':m,'evidence':[{'page':1}]}} for m in models],
          'characteristics':list(characteristics),'group_characteristics':[]}
    for name,rows in data.items():(oleg/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows))
    raw={'catalogs':[{'id':'test','source':{'sha256':source},'pages':[{'pdf_page':1,'candidate_sha256':'b'*64,'reviewed_current_content':True,'content':{'tables':[table]}}]}]}
    ours=tmp_path/'ours.zip'
    with zipfile.ZipFile(ours,'w') as z:z.writestr('all-catalogues-980-pages.json',json.dumps(raw))
    return load_facts(oleg,ours)[0]


def test_contact_cells_are_retained_without_inferred_product_owner(tmp_path):
    cols=[{'id':'a','label':'Телефон','unit':None},{'id':'b','label':'E-mail','unit':None}]
    table={'title':'Контактная информация','columns':cols,'rows':[{'cells':[
        {'column_id':'a','value':'+7 (35134) 4-22-44 доб. (1116)','state':'value'},
        {'column_id':'b','value':'info@mzva.ru','state':'value'}]}]}
    facts=_small_input(tmp_path,table)
    assert len(facts)==2 and all(f['kind']=='table_context' and f['owner']=='' for f in facts)
    assert facts[0]['raw']['value']=='+7 (35134) 4-22-44 доб. (1116)'
    assert facts[0]['pointer'].endswith('/rows/0/cells/0')


def test_contact_values_in_unlabelled_table_do_not_become_product_anchors(tmp_path):
    table={'columns':[{'id':'x','label':'','unit':None}], 'rows':[{'cells':[{'column_id':'x','value':v,'state':'value'}]} for v in ['www.mzva.ru','https://example.org','info@mzva.ru','+7 (495) 780-51-65']]}
    facts=_small_input(tmp_path,table)
    assert len(facts)==4 and all(f['kind']=='table_context' for f in facts)


def test_contact_product_word_does_not_suppress_a_real_designation(tmp_path):
    table={'title':'Контактные зажимы','columns':[{'id':'x','label':'Обозначение','unit':None}], 'rows':[{'cells':[{'column_id':'x','value':'КС-20','state':'value'}]}]}
    facts=_small_input(tmp_path,table)
    assert facts[0]['kind']=='model_designation' and facts[0]['owner']=='КС-20'


def test_implicit_manufacturer_bands_do_not_borrow_hf207_small65(tmp_path):
    cols=[{'id':str(i),'label':name,'unit':unit,'group':None} for i,(name,unit) in enumerate([
        ('',None),('МЗВА-ЧЭМЗ',None),('Сечение, мм2 / Диаметр, мм',None),('Разрушающая нагрузка','кН'),
        ('АРМАТЕХ ВК',None),('Сечение, мм2 / Диаметр, мм',None),('Разрушающая нагрузка','кН')])]
    vals=['Хомут','HF207','–','10,0','–','–','–']
    table={'title':'Сравнение зажимов МЗВА-ЧЭМЗ и АРМАТЕХ ВК','columns':cols,
           'rows':[{'cells':[{'column_id':c['id'],'value':v,'state':'dash' if v=='–' else 'value'} for c,v in zip(cols,vals)]}]}
    characteristic={'id':'load','source_id':'s','window_id':'w','group_id':'g','product_id':'HF207',
         'raw':{'name':'Разрушающая нагрузка','raw_value':'10,0','unit':'кН','condition':'','evidence':[{'page':1}],
                'header_path':[{'role':'group','raw_text':'МЗВА-ЧЭМЗ'}]}}
    facts=_small_input(tmp_path,table,models=['HF207'],characteristics=[characteristic])
    ours=[f for f in facts if f['side']=='ours']
    assert ours[3]['owner']=='HF207' and ours[3]['owner_scope']=='МЗВА-ЧЭМЗ'
    assert ours[6]['owner']=='' and ours[6]['kind']=='table_context'
    assert ours[6]['raw']['value']=='–' and ours[6]['owner_scope']=='АРМАТЕХ ВК'
    ledger,_=compare_facts(facts)
    assert next(r for r in ledger if r['ours_fact_id']==ours[6]['fact_id'])['oleg_fact_ids']==[]


def test_header_unit_metadata_and_group_symbol_case_are_not_erased():
    left,right=_header_pair()
    wrong={**right,'raw':{**right['raw'],'header_path':[{**right['raw']['header_path'][0],'unit':'мВ'},right['raw']['header_path'][1]]}}
    assert compare_facts([left,wrong])[0][0]['oleg_fact_ids']==[]
    left={**fact('ours','H','10'),'column':{'group':'Диаметр D'}}
    right=fact('oleg','H','10',raw={'header_path':[{'role':'group','raw_text':'Диаметр d'}]})
    assert compare_facts([left,right])[0][0]['oleg_fact_ids']==[]


def test_numeric_product_code_is_not_classified_as_a_phone(tmp_path):
    table={'title':'Изделия','columns':[{'id':'x','label':'Обозначение','unit':None}], 'rows':[{'cells':[{'column_id':'x','value':'8-1234567890','state':'value'}]}]}
    facts=_small_input(tmp_path,table)
    assert facts[0]['kind']=='model_designation'
