from app.shadow32_index import tokens, build, search

def test_tokens():
    assert 'arima' in tokens('Which ARIMA model?')

def test_shadow_isolated(tmp_path, monkeypatch):
    from app import shadow32_index
    def fake_preview(pdf, pages):
        return {'pages':[
            {'page_number':92,'indexing_safe':True,'warnings':[], 'chunks':[{'chunk_key':'p00092-s0000','content':'Holt method equivalent to ARIMA(0,2,2)','bbox':[1,2,3,4],'sha256':'abc'}]},
            {'page_number':79,'indexing_safe':False,'warnings':['flowchart'], 'chunks':[]}]}
    monkeypatch.setattr(shadow32_index,'preview_pdf',fake_preview)
    path=tmp_path/'shadow.sqlite'
    r=build('unused.pdf','doc',[92,79],path)
    assert r['stored_shadow_chunks']==1
    assert r['review_pages']==[79]
    assert search(path,'doc','Holt ARIMA',2)[0]['page_number']==92
    assert search(path,'other','Holt ARIMA',2)==[]

def test_math_quarantine(tmp_path, monkeypatch):
    from app import shadow32_index
    monkeypatch.setattr(shadow32_index,'preview_pdf',lambda pdf,pages:{'pages':[{'page_number':77,'indexing_safe':True,'warnings':[],'chunks':[{'chunk_key':'a','content':'AICc = AIC + 2(p+q)\n.\nT-p-q','bbox':[0,0,1,1],'sha256':'a'}]}]})
    r=build('unused','doc',[77],tmp_path/'s.sqlite')
    assert r['stored_shadow_chunks']==0 and r['review_pages']==[77]
