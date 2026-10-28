from app.layout32_correct import correct_layout

def block(t,x,y,n):
    return {'text':t,'bbox':[x,y,x+20,y+10],'original_order':n}

def test_axis_ticks_separated_but_preserved():
    b=[block('Year',100,220,0)] + [block(str(1995+i*5),100+i*15,200, i+1) for i in range(5)]
    b.append(block('ARIMA vs ETS',50,450,9))
    r=correct_layout({'blocks':b})
    assert r['diagnostics']['axis_chart_text_blocks_added'] >= 5
    assert 'ARIMA vs ETS' in r['indexable_prose_text']
    assert len(r['source_blocks'])==len(b)

def test_formula_fragment_is_flagged_not_guessed():
    b=[block('±1.96/',30,20,0),block('√',30,35,1),block('T as for ACF',30,50,2)]
    r=correct_layout({'blocks':b})
    assert r['visual_review_required']
    assert r['formula_fragments'][0]['text']=='√'
    assert 'formula_fragments_visual_review_required' in r['warnings']

def test_flowchart_indexing_blocked():
    texts=['Select model','Use auto.arima()','Do residuals look like white noise?','yes','no']
    r=correct_layout({'blocks':[block(t,30,i*20,i) for i,t in enumerate(texts)],'layout':'two_column_candidate'})
    assert r['indexable_prose_text']==''
    assert r['visual_review_required']

def test_method_text_survives():
    b=[block('Simple exponential smoothing',30,10,0),block('ARIMA(0,1,1)',30,35,1)]
    r=correct_layout({'blocks':b})
    assert 'ARIMA(0,1,1)' in r['indexable_prose_text']
