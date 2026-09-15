# -*- coding: utf-8 -*-
"""Auditoria determinística adicional da v2.15.3.

Esta bateria verifica invariantes e caminhos de entrada distintos dos testes funcionais correntes.
Não constitui certificação externa.
"""
from __future__ import annotations

from .version import APP_VERSION

import math
import random
import pandas as pd

from .designer import SlabDesigner
from .importers import clean_dataframe
from .validation import audit_design_results


def _close(a, b, tol=1e-9):
    return abs(float(a)-float(b)) <= tol * max(1.0, abs(float(a)), abs(float(b)))


def _wa_ref(mx, my, txy):
    def branch(a, b, t):
        q=abs(t)
        rx=a+q; ry=b+q
        if rx < 0.0:
            return 0.0, max(0.0, b-t*t/a) if abs(a)>1e-14 else max(0.0, ry)
        if ry < 0.0:
            return max(0.0, a-t*t/b) if abs(b)>1e-14 else max(0.0, rx), 0.0
        return max(0.0,rx), max(0.0,ry)
    xp,yp=branch(mx,my,txy)
    xn,yn=branch(-mx,-my,txy)
    return xp,xn,yp,yn


def run_audit() -> str:
    checks=0
    failures=[]
    def check(cond, msg):
        nonlocal checks
        checks += 1
        if not cond:
            failures.append(msg)

    dsg=SlabDesigner(250,30,"C30/37",500,uls_cases="101",qp_cases="203",characteristic_cases="205",
                     wk_check_enabled=True,optimize_rebar=True,rebar_strategy="Base + reforços",
                     base_vertical_phi=12,base_vertical_spacing=200,base_horizontal_phi=12,base_horizontal_spacing=200,
                     top_outer_axis="X",bottom_outer_axis="Y",positive_moment_face="Superior")

    # 1. Wood-Armer: casos fechados + 1000 amostras aleatórias contra implementação independente.
    samples=[(20,-5,8),(-20,5,8),(10,10,0),(0,0,12),(35,-50,-7),(-2,-3,20)]
    rng=random.Random(2150)
    samples += [(rng.uniform(-150,150),rng.uniform(-150,150),rng.uniform(-80,80)) for _ in range(1000)]
    for i,(mx,my,t) in enumerate(samples):
        got=dsg.wood_armer_detail(mx,my,t)
        ref=_wa_ref(mx,my,t)
        for lab,val in zip(("X+","X-","Y+","Y-"),ref):
            check(_close(got[lab],val,1e-10),f"WA {i} {lab}: {got[lab]} != {val}")
            check(got[lab] >= -1e-12,f"WA {i} {lab} negativo")

    # 2. Caminho vectorizado RAW = rotina escalar WA, e convenção de sinais configurável.
    rows=[]
    for i in range(250):
        rows.append(dict(panel="P1",node=str(i+1),case="101",mxx=rng.uniform(-100,100),myy=rng.uniform(-100,100),mxy=rng.uniform(-40,40)))
    c=clean_dataframe(pd.DataFrame(rows))
    pre=dsg._prepare_preliminary_dataframe_fast(c)
    for i,row in c.iterrows():
        ref=dsg.wood_armer_detail(row.mxx,row.myy,row.mxy)
        for col,key in [("MEd_x_sup_kNm_m","X+"),("MEd_x_inf_kNm_m","X-"),("MEd_y_sup_kNm_m","Y+"),("MEd_y_inf_kNm_m","Y-")]:
            check(_close(pre.iloc[i][col],ref[key],1e-10),f"RAW vector {i} {col}")
    dsg_inv=SlabDesigner(250,30,"C30/37",500,uls_cases="101",positive_moment_face="Inferior")
    pre_inv=dsg_inv._prepare_preliminary_dataframe_fast(c.head(20))
    for i,row in c.head(20).iterrows():
        ref=dsg_inv.wood_armer_detail(row.mxx,row.myy,row.mxy)
        check(_close(pre_inv.loc[i,"MEd_x_sup_kNm_m"],ref["X-"]),f"sinal RAW invertido Xsup {i}")
        check(_close(pre_inv.loc[i,"MEd_x_inf_kNm_m"],ref["X+"]),f"sinal RAW invertido Xinf {i}")

    # 3. Ordem física das malhas e As,min dependente de d.
    check(_close(dsg.layer_effective_depth("sup","X",12,12),214.0),"d sup X exterior")
    check(_close(dsg.layer_effective_depth("sup","Y",12,12),202.0),"d sup Y interior")
    check(_close(dsg.layer_effective_depth("inf","Y",12,12),214.0),"d inf Y exterior")
    check(_close(dsg.layer_effective_depth("inf","X",12,12),202.0),"d inf X interior")
    check(dsg.slab_flexural_min_for_d(214)>dsg.slab_flexural_min_for_d(202),"As,min deve crescer com d")

    # 4. Importação fail-safe.
    valid_raw=clean_dataframe(pd.DataFrame([dict(panel="1",node="1",case="101",mxx=1,myy=2,mxy=3)]))
    check(str(valid_raw.iloc[0]["__moment_input_mode"])=="raw_plate","RAW completo aceite")
    valid_eq=clean_dataframe(pd.DataFrame([dict(panel="1",node="1",case="101",**{"mxx+":1,"mxx-":2,"myy+":3,"myy-":4})]))
    check(str(valid_eq.iloc[0]["__moment_input_mode"])=="direct_wa","equivalentes completos aceites")
    bads=[
        pd.DataFrame([dict(panel="1",node="1",case="101",mxx=1,myy=2)]),
        pd.DataFrame([dict(panel="1",node="1",case="101",**{"mxx+":1,"mxx-":2,"myy+":3})]),
        pd.DataFrame([dict(panel="1",node="1",case="101",mxx=1,myy=2,mxy=3,**{"mxx+":1,"mxx-":2,"myy+":3,"myy-":4})]),
    ]
    for j,b in enumerate(bads):
        try:
            clean_dataframe(b); ok=False
        except ValueError:
            ok=True
        check(ok,f"entrada ambígua/incompleta {j} deve falhar")

    # 5. Grelha/base fixa e reforço dominante permitido sem substituir a base.
    base=dsg.rebar_from_phi_spacing(12,200)
    ok,_=dsg.base_solution_is_valid(base,200); check(ok,"base Ø12/200 válida")
    for phi,s in [(8,200),(14,200),(12,250),(12,75)]:
        b=dsg.rebar_from_phi_spacing(phi,s)
        ok,_=dsg.base_solution_is_valid(b,400)
        check(not ok,f"base inválida aceite Ø{phi}/{s}")
    sol=dsg.optimize_rebar_solution(2200,200,True,"X+")
    check(sol.base_text=="Ø12//200","base global não preservada")
    check(sol.as_prov+1e-9>=sol.as_base,"As final inferior à base")
    check(sol.spacing in dsg.allowed_spacing_candidates,"espaçamento final fora da grelha")

    # 6. N de membrana: a conversão é explícita e o resultado ELU não pode ser OK.
    dm=SlabDesigner(250,30,"C30/37",500,uls_cases="101",membrane_unit="N/mm",optimize_rebar=False)
    md=clean_dataframe(pd.DataFrame([dict(panel="1",node="1",case="101",mxx=10,myy=8,mxy=0,nxx=100)]))
    rr=dm.design_dataframe(md)
    check(_close(rr.iloc[0]["NXX_kN_m"],100.0),"conversão N/mm -> kN/m")
    check(str(rr.iloc[0]["Status"])=="Verificar","N-M não implementado deve devolver Verificar")

    # 7. Auditoria bloqueia falsos OK quando As,prov < As,req e quando As,prov > As,max.
    fake=pd.DataFrame([dict(Case_classification="ELU",Status="OK",Design_relevant="Sim",
        **{"Asx+_req_mm2_m":1000.0,"Asx+_prov_mm2_m":500.0,"Asx-_req_mm2_m":100.0,"Asx-_prov_mm2_m":500.0,
           "Asy+_req_mm2_m":100.0,"Asy+_prov_mm2_m":500.0,"Asy-_req_mm2_m":100.0,"Asy-_prov_mm2_m":500.0,
           "MRd_x+_kNm_m":100.0,"MRd_x-_kNm_m":100.0,"MRd_y+_kNm_m":100.0,"MRd_y-_kNm_m":100.0,
           "MEd_x_sup_kNm_m":10.0,"MEd_x_inf_kNm_m":10.0,"MEd_y_sup_kNm_m":10.0,"MEd_y_inf_kNm_m":10.0})])
    aud=audit_design_results(fake,phi_min=10,phi_max=32,wmax_mm=.3,wk_enabled=False,as_max_mm2_m=10000,fck=30,fyk=500,copy_data=True)
    check(str(aud.iloc[0]["Status"])=="Não conforme","auditoria não bloqueou Asprov<Asreq")

    # 8. Pequeno fluxo completo: todas as linhas preservadas e sem false OK de As.
    allrows=[]
    for node in range(1,21):
        allrows.append(dict(panel="A",node=str(node),case="101",mxx=20+node,myy=10+0.5*node,mxy=(-1)**node*3))
        allrows.append(dict(panel="A",node=str(node),case="203",mxx=12+0.4*node,myy=6+0.2*node,mxy=(-1)**node*2))
        allrows.append(dict(panel="A",node=str(node),case="205",mxx=15+0.3*node,myy=8+0.1*node,mxy=(-1)**node*2.5))
    full=clean_dataframe(pd.DataFrame(allrows))
    out=dsg.design_dataframe(full)
    check(len(out)==len(full),"fluxo completo perdeu linhas")
    for lab in ("x+","x-","y+","y-"):
        req=f"As{lab}_req_mm2_m" if lab.startswith('x') else f"As{lab}_req_mm2_m"
    pairs=[("Asx+_req_mm2_m","Asx+_prov_mm2_m"),("Asx-_req_mm2_m","Asx-_prov_mm2_m"),
           ("Asy+_req_mm2_m","Asy+_prov_mm2_m"),("Asy-_req_mm2_m","Asy-_prov_mm2_m")]
    mask=out["Case_classification"].astype(str).eq("ELU") & out["Status"].astype(str).isin(["OK","OK*"])
    for req,prov in pairs:
        check(bool((out.loc[mask,prov]+1e-8 >= out.loc[mask,req]).all()),f"falso OK em {prov}")

    if failures:
        raise AssertionError("Auditoria v2.15 falhou:\n"+"\n".join(failures[:50]))
    return f"SlabsEC2 {APP_VERSION} — auditoria determinística adicional: {checks}/{checks} controlos OK."

if __name__ == "__main__":
    print(run_audit())
