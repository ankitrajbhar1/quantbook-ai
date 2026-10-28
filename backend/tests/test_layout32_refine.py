from app.layout32_refine import refine_layout

def test_wrap_and_bullet():
    def b(t,y,x=60,n=0):
        return {'text':t,'bbox':[x,y,x+200,y+12],'original_order':n}
    d={'blocks':[b('• Linear exponential smoothing models all',10,n=1),
                 b('special cases of ARIMA models.',23,x=70,n=2),
                 b('• Another point',50,n=3)]}
    r=refine_layout(d)
    assert 'all special cases' in r['prose_text']
    assert len(r['segments']) == 2

def test_chart_markers_are_retained_separately():
    b=[{'text':'G','bbox':[30+i*3,30+i*3,35+i*3,38+i*3], 'original_order':i} for i in range(20)]
    b.append({'text':'Estimation and order selection','bbox':[30,200,260,215],'original_order':30})
    r=refine_layout({'blocks':b})
    assert r['diagnostics']['chart_text_blocks']==20
    assert 'Estimation' in r['prose_text']
    assert len(r['segments'])==21

def test_flowchart_warning_without_invented_edges():
    texts=['Select model','Use auto.arima()','Do residuals look like white noise?','yes','no']
    b=[{'text':t,'bbox':[40,10+i*20,280,25+i*20],'original_order':i} for i,t in enumerate(texts)]
    r=refine_layout({'blocks':b,'layout':'two_column_candidate'})
    assert 'possible_flowchart_reading_order_unreliable' in r['warnings']
