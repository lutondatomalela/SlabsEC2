# -*- coding: utf-8 -*-
import math
import pandas as pd
import numpy as np
from .designer import SlabDesigner
from .importers import canonical_case_id, clean_dataframe
from .combinations import parse_case_spec, format_case_ids, CombinationSpecError
from .diagnostics import assess_mxy_dominance, select_worst_els_wk_issue
from .peaks import parse_node_spec, assess_panel_peak, build_peak_candidates, build_peak_assessment, enrich_peak_assessment_spatial
from .geometry.importers import clean_geometry_dataframe
from .geometry.context import (
    enrich_peak_assessment_with_geometry, build_geometry_peak_diagnostic,
    merge_geometry_peak_context_into_summary,
)
from .geometry.local_design import build_geometry_local_design, merge_local_design_into_summary
from .spatial import build_spatial_rebar_zones
from .traceability import build_governing_traceability


def run_core_regression_tests() -> str:
    """Bateria curta de regressão do núcleo de cálculo e classificação de combinações.

    Não substitui validação independente/manual; detecta regressões numéricas e de lógica entre versões.
    """
    checks = []

    def ck(name, cond, detail=""):
        if not bool(cond):
            raise AssertionError(f"{name}: {detail or 'falhou'}")
        checks.append(name)

    # Parser de combinações/ranges.
    ids = parse_case_spec("101-117 201para216")
    ck("intervalos compactos", len(ids) == 33 and ids[0] == "101" and ids[-1] == "216")
    ck("intervalo 'a'", parse_case_spec("301 a 303") == ["301", "302", "303"])
    ck("formatação compacta", format_case_ids(ids) == "101-117 201-216")
    ck("casos isolados", parse_case_spec("101, 105; 220") == ["101", "105", "220"])
    try:
        parse_case_spec("117-101")
        descending_rejected = False
    except CombinationSpecError:
        descending_rejected = True
    ck("intervalo descendente rejeitado", descending_rejected)

    d = SlabDesigner(
        250, 30, "C30/37", 500,
        wk_check_enabled=True,
        qp_cases="303-304",
        frequent_cases="302",
        characteristic_cases="301",
        uls_cases="101-102",
        optimize_rebar=True,
        rebar_strategy="Substituir base",
        deflection_unit="mm",
    )
    ck("As zero", abs(d.flexural_as_required(0.0)) < 1e-9)
    ck("As,min positiva", d.slab_flexural_min_per_face() > 0.0)
    dc = d.layer_effective_depth("sup", "X", 12, 12)
    ck("d camada exterior configurada", abs(dc - (250-30-6)) < 1e-9, f"d={dc}")
    dcy = d.layer_effective_depth("sup", "Y", 12, 12)
    ck("d camada interior configurada", abs(dcy - (250-30-12-6)) < 1e-9, f"d={dcy}")
    ck("classificação ELU", d.classify_case("101 (C)") == "ELU")
    ck("classificação ELS-CHAR", d.classify_case("301 (C)") == "ELS-CHAR")
    ck("classificação ELS-FREQ", d.classify_case("302 (C)") == "ELS-FREQ")
    ck("classificação ELS-QP múltipla", d.classify_case("304 (C)") == "ELS-QP")
    ck("classificação Outro", d.classify_case("999") == "Outro")
    ck("parser nós singulares", parse_node_spec("2821, 3045; 4001") == {"2821", "3045", "4001"})

    # Detector de picos: um máximo isolado deve ser apenas sinalizado, nunca suavizado.
    peak_rows = []
    for i in range(1, 101):
        peak_rows.append({
            "Panel": "PX", "Node": str(i), "Case": "101 (C)", "Case_classification": "ELU",
            "MEd_x_sup_kNm_m": 500.0 if i == 1 else 50.0 + (i % 5),
            "MEd_x_inf_kNm_m": 0.0, "MEd_y_sup_kNm_m": 0.0, "MEd_y_inf_kNm_m": 0.0,
        })
    pa = assess_panel_peak(pd.DataFrame(peak_rows), ratio_threshold=1.50)
    ck("pico isolado detectado", pa["Pico_FEM"] == "Sim" and "isolado" in pa["Classificação_pico"].lower())
    ck("pico bruto preservado", abs(pa["Mmax_kNm_m"] - 500.0) < 1e-9)


    # Candidatos P99 e diagnóstico MXY robusto.
    cdf = build_peak_candidates(pd.DataFrame(peak_rows), "PX", percentile=0.99)
    ck("candidatos P99 disponíveis", not cdf.empty and str(cdf.iloc[0]["Node"]) == "1")
    ck("candidato não confirmado automaticamente", set(cdf["Confirmado_singular"].astype(str)) == {"Não"})

    mxy_rows = pd.DataFrame({
        "Case_classification": ["ELU"] * 100,
        "MXX_kNm_m": [0.001] + [50.0] * 99,
        "MYY_kNm_m": [0.001] + [40.0] * 99,
        "MXY_kNm_m": [0.2] + [10.0] * 99,
    })
    md = assess_mxy_dominance(mxy_rows)
    ck("MXY robusto sem quociente artificial", 0.15 < md["MXY_ratio_robust"] < 0.30, str(md))
    ck("MXY diagnóstico estatístico", md["MXY_diagnostic_available"] == "Sim")

    # v2.8.3: regressão do erro ``single positional indexer is out-of-bounds``.
    # O diagnóstico deve funcionar mesmo quando só existem linhas ELS/wk ``Não conforme``
    # e nenhuma linha ``Verificar``.
    wk_only_fail = pd.DataFrame([
        {"ELS_wk_status": "Não conforme", "ELS_wk_ratio": 1.15, "Case": "302 (C)"},
        {"ELS_wk_status": "Não conforme", "ELS_wk_ratio": 1.32, "Case": "303 (C)"},
    ])
    wk_issue = select_worst_els_wk_issue(wk_only_fail)
    ck("diagnóstico wk sem iloc vazio", wk_issue is not None and str(wk_issue["Case"]) == "303 (C)")
    wk_mixed = pd.DataFrame([
        {"ELS_wk_status": "Verificar", "ELS_wk_ratio": 9.0, "Case": "301 (C)"},
        {"ELS_wk_status": "Não conforme", "ELS_wk_ratio": 1.01, "Case": "302 (C)"},
    ])
    wk_issue2 = select_worst_els_wk_issue(wk_mixed)
    ck("diagnóstico wk prioriza Não conforme", wk_issue2 is not None and str(wk_issue2["Case"]) == "302 (C)")

    # Limites de armadura: nunca ultrapassar Ømax silenciosamente.
    dlim = SlabDesigner(250, 30, "C30/37", 500, phi_min_mm=8, phi_max_mm=16, uls_cases="101")
    slim = dlim.choose_rebar(9000.0, max_spacing=400.0)
    ck("Ømax respeitado em caso sem solução", slim.phi <= 16.0 + 1e-9, f"phi={slim.phi}")
    ck("limite de capacidade sinalizado", slim.capacity_limited and slim.as_prov < 9000.0)

    # v2.14.1: Base + reforços mantém a base invariável, mesmo quando o reforço domina a base.
    dbase = SlabDesigner(
        250, 30, "C30/37", 500, phi_min_mm=8, phi_max_mm=16, uls_cases="101",
        optimize_rebar=True, rebar_strategy="Base + reforços",
        base_vertical_phi=10, base_vertical_spacing=200,
        base_horizontal_phi=10, base_horizontal_spacing=200,
    )
    sb = dbase.optimize_rebar_solution(700.0, 400.0, True, "X+")
    ck("Base+reforço usa uma única família adicional", sb.base_text == "Ø10//200" and sb.add_text.count("+") == 0 and not any(tok in sb.add_text for tok in ("2Ø", "3Ø", "4Ø", "5Ø")), sb.text)
    ck("Base+reforço mantém o espaçamento da base", sb.add_text.endswith("//200") and "//200 + " in sb.text and sb.text.endswith("//200"), sb.text)
    ck("Base+reforço cobre As", sb.as_prov >= 700.0 - 1e-9 and not sb.capacity_limited, f"{sb.text}; As={sb.as_prov}")
    sb_unif = dbase.optimize_rebar_solution(1200.0, 400.0, True, "X+")
    ck("Base+reforço dominante preserva a base", sb_unif.base_text == "Ø10//200" and "+" in sb_unif.text and sb_unif.as_prov >= 1200.0 - 1e-9 and "base fixa preservada" in sb_unif.optimization_note, sb_unif.text)
    sb_lim = dbase.optimize_rebar_solution(9000.0, 400.0, True, "X+")
    ck("Base+reforço insuficiente fica Não-forçado", sb_lim.capacity_limited and sb_lim.as_prov < 9000.0 and not any(tok in sb_lim.text for tok in ("2Ø", "3Ø", "4Ø", "5Ø")), sb_lim.text)
    comp_diff = dbase.rebar_from_phi_spacing(10, 200)
    comp_diff.base_text = "Ø10//200"; comp_diff.add_text = "Ø16//100"; comp_diff.text_override = "Ø10//200 + Ø16//100"
    phi_eq_diff, s_eff_diff, _ = dbase.rebar_crack_geometry(comp_diff)
    ck("phi_eq ponderado por densidade de barras", 14.0 < phi_eq_diff < 15.0 and abs(s_eff_diff-100.0) < 1e-9, f"phi_eq={phi_eq_diff}, s_eff={s_eff_diff}")

    # Geometria física da solução composta: centróide ponderado e d correspondente.
    comp = dbase.rebar_from_phi_spacing(10, 200)
    comp.base_text = "Ø10//200"; comp.add_text = "Ø16//200"; comp.text_override = "Ø10//200 + Ø16//200"
    comp.as_base = math.pi*10**2/4*1000/200; comp.as_add = math.pi*16**2/4*1000/200; comp.as_prov = comp.as_base + comp.as_add
    gcomp = dbase.rebar_layer_geometry(comp)
    expected_centroid = (comp.as_base*5.0 + comp.as_add*8.0)/comp.as_prov
    ck("centróide real de armadura composta", abs(gcomp["centroid_from_layer_face_mm"]-expected_centroid) < 1e-9, str(gcomp))
    other = dbase.rebar_from_phi_spacing(12, 200)
    dcomp = dbase.layer_effective_depth_from_solutions("sup", "X", comp, other)
    ck("d usa centróide real da solução exterior", abs(dcomp-(250-30-expected_centroid)) < 1e-9, f"d={dcomp}")

    overlap_rejected = False
    try:
        SlabDesigner(250, 30, "C30/37", 500, uls_cases="101-110", qp_cases="110")
    except CombinationSpecError:
        overlap_rejected = True
    ck("sobreposição de classes rejeitada", overlap_rejected)

    s1 = d.rebar_from_phi_spacing(12, 200)
    s2 = d.rebar_from_phi_spacing(12, 100)
    w1 = d.crack_check_detail(35.0, s1, "superior", "X", d_mm=dc)["wk_mm"]
    w2 = d.crack_check_detail(35.0, s2, "superior", "X", d_mm=dc)["wk_mm"]
    ck("wk finito", math.isfinite(w1) and w1 >= 0.0)
    ck("mais As reduz wk", w2 <= w1 + 1e-12, f"wk1={w1}, wk2={w2}")
    st = d.cracked_section_service_state(35.0, s1, d_mm=dc)
    ck("secção fendilhada x", 0.0 < st["x_cr_mm"] < dc)
    ck("Ac,eff coerente", st["Ac_eff_mm2"] > 0.0 and st["rho_p_eff"] > 0.0)

    rows = []
    cases = [
        ("101 (C)", 1.00),
        ("102 (C)", 0.80),
        ("301 (C)", 0.70),
        ("302 (C)", 0.65),
        ("303 (C)", 0.58),
        ("304 (C)", 0.55),
    ]
    for case, scale in cases:
        for node, f in [(1, 1.0), (2, 0.7), (3, 0.4)]:
            rows.append(dict(
                panel="P1", node=str(node), case=case, case_id=canonical_case_id(case),
                mxx=0, myy=0, mxy=0,
                mxx_wa_pos=70*scale*f, mxx_wa_neg=30*scale*f,
                myy_wa_pos=45*scale*f, myy_wa_neg=20*scale*f,
                qxx=0, qyy=0, nxx=0, nyy=0, nxy=0, ugz=-0.2,
                __moment_input_mode="direct_wa", __row_order=len(rows)
            ))
    rdf = d.design_dataframe(pd.DataFrame(rows))
    ck("solução única painel", len(rdf[["X+_rebar", "X-_rebar", "Y+_rebar", "Y-_rebar"]].drop_duplicates()) == 1)
    ck("solução mínima e adoptada auditáveis", all(c in rdf.columns for c in ["X+_minimum_valid", "X-_minimum_valid", "Y+_minimum_valid", "Y-_minimum_valid"]))
    ck("construtibilidade auditável", "Constructability_status" in rdf.columns and "Constructability_note" in rdf.columns)
    hs = pd.DataFrame([
        {"Panel":"A","X+_rebar":"Ø12//150","X-_rebar":"Ø12//150","Y+_rebar":"Ø12//150","Y-_rebar":"Ø12//150",
         "Asx+_prov_mm2_m":753.9822369,"Asx-_prov_mm2_m":753.9822369,"Asy+_prov_mm2_m":753.9822369,"Asy-_prov_mm2_m":753.9822369},
        {"Panel":"B","X+_rebar":"Ø12//125","X-_rebar":"Ø12//125","Y+_rebar":"Ø12//125","Y-_rebar":"Ø12//125",
         "Asx+_prov_mm2_m":904.7786842,"Asx-_prov_mm2_m":904.7786842,"Asy+_prov_mm2_m":904.7786842,"Asy-_prov_mm2_m":904.7786842},
    ])
    hso = d.add_cross_panel_harmonization_suggestions(hs, max_extra_ratio=1.21)
    ck("harmonização entre painéis é só sugestão", str(hso[hso["Panel"]=="A"].iloc[0]["X+_harmonization_suggestion"]) == "Ø12//125" and str(hso[hso["Panel"]=="A"].iloc[0]["X+_rebar"]) == "Ø12//150")
    ck("todos ELU verificados", (rdf[rdf["Case_classification"] == "ELU"]["util_M"] <= 1.0 + 1e-9).all())
    ck("todos ELS-QP verificados", (rdf[rdf["Case_classification"] == "ELS-QP"]["ELS_wk_ratio"] <= 1.0 + 1e-9).all())
    ck("ELS frequente informativa", set(rdf[rdf["Case_classification"] == "ELS-FREQ"]["Status"].astype(str)) == {"Informativo"})
    char_statuses = set(rdf[rdf["Case_classification"] == "ELS-CHAR"]["Status"].astype(str))
    ck("ELS característica com tensões", char_statuses.issubset({"OK", "OK*", "Verificar", "Não conforme"}) and bool(char_statuses), str(char_statuses))
    ck("painel reavaliado", set(rdf["Panel_solution_verified_all_cases"].astype(str)) == {"Sim"})

    # Exclusão manual de singularidade: afecta apenas o envelope distribuído e mantém o pico auditável.
    ds = SlabDesigner(
        250, 30, "C30/37", 500, uls_cases="101", singular_nodes="1",
        phi_min_mm=8, phi_max_mm=16, optimize_rebar=True, rebar_strategy="Substituir base"
    )
    srows = []
    for node, m in [(1, 500.0), (2, 55.0), (3, 45.0), (4, 35.0)]:
        srows.append(dict(
            panel="PS", node=str(node), case="101 (C)", case_id="101", mxx=0, myy=0, mxy=0,
            mxx_wa_pos=m, mxx_wa_neg=0, myy_wa_pos=0, myy_wa_neg=0,
            qxx=0, qyy=0, nxx=0, nyy=0, nxy=0, ugz=0,
            __moment_input_mode="direct_wa", __row_order=len(srows)
        ))
    sr = ds.design_dataframe(pd.DataFrame(srows))
    sing = sr[sr["Node"].astype(str) == "1"].iloc[0]
    dist = sr[sr["Node"].astype(str) != "1"]
    ck("singularidade excluída só por confirmação", sing["Singular_node_confirmed"] == "Sim" and sing["Design_relevant"] == "Não")
    ck("pico local permanece auditável", float(sing["Local_peak_util_raw"]) > 1.0 and sing["Local_peak_status"] == "Não conforme local")
    ck("envelope distribuído independente do pico confirmado", (dist["util_M"] <= 1.0 + 1e-9).all())

    # v2.8: domínio resistente e limitação de tensões ELS.
    fs_ok = d.flexural_section_state(1500.0, dc)
    ck("domínio secção normal válido", fs_ok["section_domain_valid"] == "Sim")
    fs_over = d.flexural_section_state(10000.0, dc)
    ck("compatibilidade resolve secção com aço abaixo de fyd", fs_over["section_domain_valid"] == "Sim" and fs_over["steel_yields"] == "Não")
    ck("MRd não truncado artificialmente na cedência", float(fs_over["MRd_kNm_m"]) > float(fs_over["MRd_singly_lim_kNm_m"]) + 1e-9)
    st_char = d.service_stress_check_detail(35.0, s1, "ELS-CHAR", d_mm=dc)
    ck("ELS característica tensão aço calculada", st_char["sigma_s_MPa"] >= 0.0 and st_char["sigma_s_lim_MPa"] == 0.8*d.fyk)
    sol_stress = d.optimize_solution_for_service_stress(80.0, s1, d.slab_flexural_min_per_face(), 400.0, "X+", d_mm=dc)
    st_char_opt = d.service_stress_check_detail(80.0, sol_stress, "ELS-CHAR", d_mm=dc)
    ck("optimização ELS característica cumpre sigma_s", st_char_opt["sigma_s_MPa"] <= st_char_opt["sigma_s_lim_MPa"] + 1e-9 and sol_stress.as_prov >= s1.as_prov)
    st_qp = d.service_stress_check_detail(35.0, s1, "ELS-QP", d_mm=dc)
    ck("ELS-QP limite fluência linear", abs(st_qp["sigma_c_qp_lim_MPa"] - 0.45*d.fck) < 1e-12)

    # v2.10.0: geometria opcional — importação/limpeza e enriquecimento sem alterar o pico bruto.
    geo_nodes = clean_geometry_dataframe(pd.DataFrame({
        "Node":[1,2,25], "X (m)":[0.0,0.0,1.0], "Y (m)":[0.0,0.0,1.0], "Z (m)":[0.0,3.0,3.0], "Support":["Fixed","",""],
    }), "nodes")
    ck("geometria opcional nós", len(geo_nodes)==3 and set(geo_nodes.columns)=={"node","x","y","z","support"})
    geo_members = clean_geometry_dataframe(pd.DataFrame({
        "Member":[1,2], "Node 1":[1,2], "Node 2":[2,25], "Structure object":["Column","Beam"]
    }), "members")
    ck("geometria opcional vigas/pilares", len(geo_members)==2 and set(geo_members["structure_object"])=={"Column","Beam"})
    geo_walls = clean_geometry_dataframe(pd.DataFrame({
        "Panel/Node/Case":["18/25/101 (C)","18/25/102 (C)","18/2/101 (C)"]
    }), "walls")
    ck("geometria opcional paredes deduplicadas", len(geo_walls)==2 and set(geo_walls["node"])=={"25","2"})
    geo_open = clean_geometry_dataframe(pd.DataFrame({
        "Tipo":["Segmento"]*4, "X (m)":[2,3,3,2], "Y (m)":[2,2,3,3], "Z (m)":[3,3,3,3]
    }), "openings", default_contour="Abertura 1")
    ck("geometria opcional contorno", len(geo_open)==4 and geo_open["contour"].nunique()==1)
    pk0 = pd.DataFrame([{
        "Panel":"P", "Nó_pico":"25", "Mmax_kNm_m":500.0, "Pico_FEM":"Sim",
        "Pico_ratio_max_P95":5.0, "Nós_candidatos_P99":"25 (500.0), 2 (420.0)"
    }])
    pke = enrich_peak_assessment_with_geometry(pk0, geo_nodes, geo_members, geo_walls, geo_open)
    ck("pico enriquecido sem alterar Mmax", pke.iloc[0]["Geo_disponível"]=="Sim" and abs(float(pke.iloc[0]["Mmax_kNm_m"])-500.0)<1e-12)
    ck("geometria classifica zona local", str(pke.iloc[0]["Tipo_zona_local"]) != "Sem geometria" and str(pke.iloc[0]["Confiança_contexto"]) in {"Alta","Média","Baixa"})
    ck("geometria não altera pico bruto", abs(float(pke.iloc[0]["Mmax_kNm_m"])-float(pk0.iloc[0]["Mmax_kNm_m"])) < 1e-12)
    gd = build_geometry_peak_diagnostic(pke)
    ck("geometria gera diagnóstico profissional", len(gd)==1 and gd.iloc[0]["Origem"]=="Geometria opcional / Picos FEM")
    sm = merge_geometry_peak_context_into_summary(pd.DataFrame([{"Panel":"P","Status":"Não conforme"}]), pke)
    ck("geometria acrescenta contexto ao resumo sem mudar estado", sm.iloc[0]["Status"]=="Não conforme" and "Tipo_zona_local" in sm.columns)


    # v2.12.0: contexto geométrico pode separar armadura distribuída/local, sem alterar o envelope bruto.
    nodes_local=[]; nid=1
    grid=[i*0.25-1.25 for i in range(11)]
    for xx in grid:
        for yy in grid:
            nodes_local.append((nid,xx,yy,3.0,"")); nid += 1
    nodes_local += [(1000,0.0,0.0,0.0,""),(1001,0.0,0.0,6.0,"")]
    geo_nodes_local = clean_geometry_dataframe(pd.DataFrame(nodes_local, columns=["Node","X (m)","Y (m)","Z (m)","Support"]), "nodes")
    geo_members_local = clean_geometry_dataframe(pd.DataFrame([[1,1000,1001,"Column"]], columns=["Member","Node 1","Node 2","Structure object"]), "members")
    lrows=[]
    for node,xx,yy,zz,supp in nodes_local[:121]:
        rr=(xx*xx+yy*yy)**0.5
        mm=190.0 if rr < 0.01 else (105.0 if rr <= 0.40 else 45.0)
        for case,scale in [("101 (C)",1.0),("302 (C)",0.40)]:
            lrows.append(dict(panel="PL", node=str(node), case=case, case_id=canonical_case_id(case),
                mxx=0,myy=0,mxy=0,mxx_wa_pos=mm*scale,mxx_wa_neg=0,myy_wa_pos=0.7*mm*scale,myy_wa_neg=0,
                qxx=0,qyy=0,nxx=0,nyy=0,nxy=0,ugz=0,__moment_input_mode="direct_wa",__row_order=len(lrows)))
    dl = SlabDesigner(250,30,"C30/37",500,uls_cases="101",qp_cases="302",wk_check_enabled=True,phi_min_mm=8,phi_max_mm=16,optimize_rebar=True,rebar_strategy="Substituir base")
    lr = dl.design_dataframe(pd.DataFrame(lrows))
    lp = build_peak_assessment(lr, ratio_threshold=1.5)
    lpe = enrich_peak_assessment_with_geometry(lp, geo_nodes_local, geo_members_local, pd.DataFrame(), pd.DataFrame())
    ld = build_geometry_local_design(lr, lpe, geo_nodes_local, geo_members_local, pd.DataFrame(), pd.DataFrame(), dl, enabled=True, zone_factor=2.0)
    ck("dimensionamento local geométrico aplicado", len(ld)==1 and ld.iloc[0]["Aplicado"]=="Sim")
    ck("dimensionamento local preserva Mmax bruto", abs(float(ld.iloc[0]["Mmax_bruto_kNm_m"])-float(lp.iloc[0]["Mmax_kNm_m"])) < 1e-12)
    ck("dimensionamento local separa armaduras", str(ld.iloc[0]["X+_distribuído"]) != "" and str(ld.iloc[0]["X+_local"]) != "")
    ck("zona automática não produz OK definitivo", str(ld.iloc[0]["Status_projeto_geom"]) in {"Verificar","Não conforme"})
    sm2 = merge_local_design_into_summary(pd.DataFrame([{"Panel":"PL","Status_global":"Não conforme","Motivo_estado":"raw","Acção_recomendada":"raw"}]), ld)
    ck("resumo preserva estado RAW", sm2.iloc[0]["Status_global_RAW"]=="Não conforme" and "Status_projeto_geom" in sm2.columns)

    # v2.13.0: parâmetros EC2 avançados têm efeito real, são consistentes entre verificações
    # e deixam de existir coeficientes parciais ocultos/fixos no corte de referência.
    d_std = SlabDesigner(250,30,"C30/37",500,gamma_c=1.50,gamma_s=1.15,alpha_cc=1.00,uls_cases="101")
    d_gc = SlabDesigner(250,30,"C30/37",500,gamma_c=1.40,gamma_s=1.15,alpha_cc=1.00,uls_cases="101")
    ck("v2.13 γc altera fcd", d_gc.cp["fcd"] > d_std.cp["fcd"] and abs(d_std.gamma_c-1.50)<1e-12)
    d_eff_adv = 200.0
    as_std_gc = d_std.flexural_as_required(100.0, d_mm=d_eff_adv)
    as_low_gc = d_gc.flexural_as_required(100.0, d_mm=d_eff_adv)
    ck("v2.13 γc altera As ELU", as_low_gc < as_std_gc)
    dtest = 200.0
    as_test = 1200.0
    ck("v2.13 γc usado em VRdc", d_gc.shear_vrdc_kN_per_m(as_test,dtest) > d_std.shear_vrdc_kN_per_m(as_test,dtest))
    d_gs = SlabDesigner(250,30,"C30/37",500,gamma_s=1.10,uls_cases="101")
    ck("v2.13 γs altera fyd", d_gs.fyd > d_std.fyd and abs(d_gs.gamma_s-1.10)<1e-12)
    ck("v2.13 γs altera As ELU", d_gs.flexural_as_required(100.0,d_mm=d_eff_adv) < as_std_gc)
    d_acc = SlabDesigner(250,30,"C30/37",500,alpha_cc=0.85,uls_cases="101")
    ck("v2.13 αcc altera fcd", d_acc.cp["fcd"] < d_std.cp["fcd"] and abs(d_acc.alpha_cc-0.85)<1e-12)
    ck("v2.13 αcc altera As ELU", d_acc.flexural_as_required(100.0,d_mm=d_eff_adv) > as_std_gc)
    d_els = SlabDesigner(250,30,"C30/37",500,stress_k1=0.55,stress_k2=0.40,stress_k3=0.75,uls_cases="101")
    ck("v2.13 k1 k2 k3 alteram limites ELS", abs(d_els.stress_limits["sigma_c_char_lim_MPa"]-0.55*d_els.fck)<1e-12 and abs(d_els.stress_limits["sigma_c_qp_linear_creep_lim_MPa"]-0.40*d_els.fck)<1e-12 and abs(d_els.stress_limits["sigma_s_char_lim_MPa"]-0.75*d_els.fyk)<1e-12)
    d_ag20 = SlabDesigner(250,30,"C30/37",500,aggregate_mm=20,uls_cases="101")
    d_ag32 = SlabDesigner(250,30,"C30/37",500,aggregate_mm=90,uls_cases="101")
    sag = d_ag20.rebar_from_phi_spacing(10,100)
    ok20 = d_ag20.base_solution_is_valid(sag, 250.0)[0]
    ok32 = d_ag32.base_solution_is_valid(sag, 250.0)[0]
    ck("v2.13 dg entra na construtibilidade", ok20 and not ok32)

    # v2.14.0: Wood-Armer raw auditável, zonamento espacial e rastreabilidade.
    wa = d_std.wood_armer_detail(20.0, -5.0, 8.0)
    ck("v2.15 Wood-Armer optimizado quatro momentos", abs(wa["X+"]-28.0)<1e-12 and abs(wa["X-"]-0.0)<1e-12 and abs(wa["Y+"]-3.0)<1e-12 and abs(wa["Y-"]-8.2)<1e-12)
    ck("v2.15 Wood-Armer contribuição Mxy auditável", abs(wa["X+_mxy"]-8.0)<1e-12 and abs(wa["Y-_mxy"]-3.2)<1e-12)
    raw14 = pd.DataFrame([dict(panel="W",node="1",case="101",case_id="101",mxx=20,myy=-5,mxy=8,qxx=0,qyy=0,nxx=0,nyy=0,nxy=0,ugz=0,__moment_input_mode="raw_plate")])
    rw14 = d_std.design_dataframe(raw14)
    ck("v2.15 raw aplica Wood-Armer uma vez", str(rw14.iloc[0]["WA_transformation_applied"])=="Sim" and abs(float(rw14.iloc[0]["MEd_x_sup_kNm_m"])-28.0)<1e-12)
    direct14 = pd.DataFrame([dict(panel="D",node="1",case="101",case_id="101",mxx=0,myy=0,mxy=0,mxx_wa_pos=30,mxx_wa_neg=4,myy_wa_pos=12,myy_wa_neg=6,qxx=0,qyy=0,nxx=0,nyy=0,nxy=0,ugz=0,__moment_input_mode="direct_wa")])
    rd14 = d_std.design_dataframe(direct14)
    ck("v2.14 equivalentes importados não duplicam Wood-Armer", str(rd14.iloc[0]["WA_transformation_applied"])=="Não" and abs(float(rd14.iloc[0]["MEd_x_sup_kNm_m"])-30.0)<1e-12)

    dbsp = SlabDesigner(250,30,"C30/37",500,uls_cases="101",qp_cases="302",wk_check_enabled=True,phi_min_mm=8,phi_max_mm=16,
                        optimize_rebar=True,rebar_strategy="Base + reforços",
                        base_vertical_phi=12,base_vertical_spacing=200,base_horizontal_phi=12,base_horizontal_spacing=200)
    lrsp = dbsp.design_dataframe(pd.DataFrame(lrows))
    sp14 = build_spatial_rebar_zones(lrsp, geo_nodes_local, dbsp)
    ck("v2.14.1 zonamento espacial produz base global", not sp14.empty and (sp14["Tipo_zona"].astype(str)=="Base distribuída").any())
    zb14 = sp14[sp14["Tipo_zona"].astype(str)=="Base distribuída"].iloc[0]
    ck("v2.14.1 base espacial permanece configurada", str(zb14["X+_base"])=="Ø12//200" and str(zb14["Y+_base"])=="Ø12//200" and abs(float(zb14["Frac_nós"])-1.0)<1e-12)
    zr14 = sp14[sp14["Tipo_zona"].astype(str)=="Reforço local automático"]
    ck("v2.14.1 reforços espaciais mantêm base", zr14.empty or ((zr14["X+_base"].astype(str)=="Ø12//200") & (zr14["Y+_base"].astype(str)=="Ø12//200")).all())
    ck("v2.14.1 zonas locais não são pontuais", zr14.empty or int(zr14["N_nós"].min()) >= 4)

    tr14 = build_governing_traceability(rw14)
    ck("v2.14 rastreabilidade ELU por face", not tr14.empty and set(tr14["Face_direção"])=={"X+","X-","Y+","Y-"})
    ck("v2.14 rastreabilidade preserva raw", abs(float(tr14.iloc[0]["MXY_raw"])-8.0)<1e-12 and str(tr14.iloc[0]["WA_transformation_applied"])=="Sim")

    ps14 = enrich_peak_assessment_spatial(lr, build_peak_assessment(lr, ratio_threshold=1.5), geo_nodes_local)
    ck("v2.14 pico espacial mantém política RAW", not ps14.empty and str(ps14.iloc[0]["Política_valor_dimensionamento"]).startswith("RAW"))
    ck("v2.14 pico não vira singularidade automaticamente", str(ps14.iloc[0]["Singularidade_automática"]).startswith("Nunca"))

    # v2.15.1: regressão do caso real que fazia um máximo nodal localizado impor Ø25/Ø32
    # à totalidade do painel. A política P99 separa apenas o envelope distribuído e mantém RAW.
    p151_rows = []
    for node in range(1, 201):
        m = 250.0 if node == 1 else 100.0
        p151_rows.append(dict(
            panel="P151", node=str(node), case="101 (C)", case_id="101",
            mxx=0, myy=0, mxy=0, mxx_wa_pos=m, mxx_wa_neg=0, myy_wa_pos=0, myy_wa_neg=0,
            qxx=0, qyy=0, nxx=0, nyy=0, nxy=0, ugz=0,
            __moment_input_mode="direct_wa", __row_order=node-1
        ))
    d151 = SlabDesigner(
        250, 30, "C30/37", 500, uls_cases="101", wk_check_enabled=False, stress_check_enabled=False,
        optimize_rebar=True, rebar_strategy="Base + reforços",
        base_vertical_phi=12, base_vertical_spacing=200, base_horizontal_phi=12, base_horizontal_spacing=200,
        distributed_peak_policy="P99 nodal + RAW local", phi_min_mm=10, phi_max_mm=32
    )
    r151 = d151.design_dataframe(pd.DataFrame(p151_rows))
    p151_peak = r151[r151["Node"].astype(str)=="1"].iloc[0]
    p151_dist = r151[r151["Node"].astype(str)!="1"]
    dist_rebar = str(p151_dist.iloc[0]["X+_rebar"])
    ck("v2.15.1 P99 separa pico localizado", str(p151_peak.get("Auto_peak_local_node","Não"))=="Sim" and str(p151_peak.get("Excluded_from_distributed_envelope","Não"))=="Sim")
    ck("v2.15.1 P99 preserva MEd RAW", abs(float(p151_peak["MEd_x_sup_kNm_m"])-250.0)<1e-12)
    ck("v2.15.1 P99 não sobredimensiona malha distribuída", all(x not in dist_rebar for x in ("Ø20", "Ø25", "Ø32")), dist_rebar)
    ck("v2.15.1 pico local fica Verificar", str(p151_peak["Status"])=="Verificar")

    d151_raw = SlabDesigner(
        250, 30, "C30/37", 500, uls_cases="101", wk_check_enabled=False, stress_check_enabled=False,
        optimize_rebar=True, rebar_strategy="Base + reforços",
        base_vertical_phi=12, base_vertical_spacing=200, base_horizontal_phi=12, base_horizontal_spacing=200,
        distributed_peak_policy="RAW integral", phi_min_mm=10, phi_max_mm=32
    )
    r151_raw = d151_raw.design_dataframe(pd.DataFrame(p151_rows))
    ck("v2.15.1 RAW integral desactiva separação", not (r151_raw.get("Auto_peak_local_node", pd.Series(dtype=str)).astype(str)=="Sim").any())
    ck("v2.15.1 RAW integral mantém máximo no envelope", str(r151_raw.iloc[0]["X+_rebar"]) != dist_rebar or str(r151_raw.iloc[0].get("Rebar_limit_reached","Não"))=="Sim")

    # Campos opcionais ausentes são zeros internos apenas por conveniência numérica, nunca
    # apresentados como se tivessem sido fornecidos pelo modelo FEM.
    cin = clean_dataframe(pd.DataFrame({
        "Panel":["1"], "Node":["1"], "Case":["101"],
        "MXX+":[30.0], "MXX-":[5.0], "MYY+":[20.0], "MYY-":[4.0]
    }))
    ck("v2.15.1 distingue Q ausente de zero", bool(cin.iloc[0]["__provided_qxx"]) is False and float(cin.iloc[0]["qxx"])==0.0)
    ck("v2.15.1 distingue UGZ ausente de zero", bool(cin.iloc[0]["__provided_ugz"]) is False and float(cin.iloc[0]["ugz"])==0.0)
    prep151 = d151._prepare_preliminary_dataframe_fast(cin)
    ck("v2.15.1 reporta opcionais não fornecidos", str(prep151.iloc[0]["QXX_input_status"])=="Não fornecido" and str(prep151.iloc[0]["UGZ_input_status"])=="Não fornecido")

    # O caminho vectorizado de grandes datasets deve reproduzir as mesmas equações do caminho
    # detalhado, e não uma aproximação numérica distinta.
    test_sol = d151.optimize_rebar_solution(1500.0, 200.0, True, "X+")
    test_d = d151.layer_effective_depth_from_solutions("sup", "X", test_sol, test_sol)
    test_m = np.array([0.0, 10.0, 40.0, 80.0, 120.0])
    arr_svc = d151._service_state_arrays(test_m, test_sol, test_d)
    ref_svc = [d151.cracked_section_service_state(float(m), test_sol, d_mm=test_d) for m in test_m]
    ck("v2.15.1 ELS vectorizado reproduz sigma_s", max(abs(arr_svc["sigma_s"][i]-ref_svc[i]["sigma_s_MPa"]) for i in range(len(test_m))) < 1e-10)
    ck("v2.15.1 ELS vectorizado reproduz wk", max(abs(arr_svc["wk"][i]-ref_svc[i]["wk_mm"]) for i in range(len(test_m))) < 1e-10)
    arr_as = d151._flexural_as_required_array(test_m, test_d)
    ref_as = np.array([d151.flexural_as_required(float(m), d_mm=test_d) for m in test_m])
    ck("v2.15.1 As vectorizado reproduz núcleo", np.allclose(arr_as, ref_as, rtol=1e-12, atol=1e-9))

    d151_large = SlabDesigner(
        250, 30, "C30/37", 500, uls_cases="101", wk_check_enabled=False, stress_check_enabled=False,
        optimize_rebar=True, rebar_strategy="Base + reforços",
        base_vertical_phi=12, base_vertical_spacing=200, base_horizontal_phi=12, base_horizontal_spacing=200,
        distributed_peak_policy="P99 nodal + RAW local", phi_min_mm=10, phi_max_mm=32
    )
    d151_large._large_dataset_mode = True
    pre_large = d151_large._prepare_preliminary_dataframe_fast(pd.DataFrame(p151_rows))
    r151_large = d151_large._harmonize_panel_results_large(pre_large)
    ck("v2.15.1 caminho massivo preserva linhas", len(r151_large)==len(p151_rows) and set(r151_large["Integrity_status"].astype(str))=={"OK"})
    ck("v2.15.1 caminho massivo mantém solução distribuída", str(r151_large.iloc[1]["X+_rebar"])==dist_rebar and str(r151_large.iloc[0]["Auto_peak_local_node"])=="Sim")

    # v2.15.2: o diagnóstico global de wk ignora correctamente linhas locais excluídas.
    wk_local_only = pd.DataFrame([
        {"Case_classification":"ELS-QP", "ELS_wk_status":"Não conforme", "ELS_wk_ratio":2.5, "Design_relevant":"Não", "Excluded_from_distributed_envelope":"Sim"},
        {"Case_classification":"ELS-QP", "ELS_wk_status":"OK", "ELS_wk_ratio":0.8, "Design_relevant":"Sim", "Excluded_from_distributed_envelope":"Não"},
    ])
    ck("v2.15.2 wk local não contamina diagnóstico global", select_worst_els_wk_issue(wk_local_only) is None)

    # Combinação Outro no mesmo nó de um pico automático permanece estritamente informativa.
    p152_rows = list(p151_rows) + [dict(
        panel="P151", node="1", case="204 (C)", case_id="204",
        mxx=0, myy=0, mxy=0, mxx_wa_pos=999.0, mxx_wa_neg=0, myy_wa_pos=0, myy_wa_neg=0,
        qxx=0, qyy=0, nxx=0, nyy=0, nxy=0, ugz=0, __moment_input_mode="direct_wa", __row_order=9999
    )]
    r152_other = d151.design_dataframe(pd.DataFrame(p152_rows))
    oth204 = r152_other[r152_other["Case_classification"].astype(str)=="Outro"]
    ck("v2.15.2 Outro permanece Informativo em nó local", not oth204.empty and set(oth204["Status"].astype(str))=={"Informativo"})

    # Fecho simultâneo X/Y: a própria armadura seleccionada define d e deve voltar a verificar MRd.
    d152_close = SlabDesigner(
        250, 30, "C30/37", 500, uls_cases="101", wk_check_enabled=False, stress_check_enabled=False,
        optimize_rebar=True, rebar_strategy="Base + reforços",
        base_vertical_phi=12, base_vertical_spacing=200, base_horizontal_phi=12, base_horizontal_spacing=200,
        distributed_peak_policy="RAW integral", phi_min_mm=10, phi_max_mm=32
    )
    base_x = d152_close.base_solution_for_direction(False)
    base_y = d152_close.base_solution_for_direction(True)
    gu = pd.DataFrame({"MEd_x_sup_kNm_m":[130.0], "MEd_y_sup_kNm_m":[130.0]})
    bx, by = d152_close._close_panel_face_pair("+", base_x, base_y, gu, pd.DataFrame(), pd.DataFrame(), 200.0, 200.0, False, True, d152_close.crack_min_as_per_face())
    dx = d152_close.layer_effective_depth_from_solutions("sup", "X", bx, by)
    dy = d152_close.layer_effective_depth_from_solutions("sup", "Y", by, bx)
    ux = 130.0 / d152_close.flexural_section_state(bx.as_prov, dx)["MRd_kNm_m"]
    uy = 130.0 / d152_close.flexural_section_state(by.as_prov, dy)["MRd_kNm_m"]
    ck("v2.15.2 fecho final MEd/MRd com d físico", max(ux, uy) <= 1.0 + 1e-9, f"ux={ux:.4f}; uy={uy:.4f}; {bx.text}; {by.text}")

    # Ultrapassar 0,45fck em QP é aviso sobre o modelo de fluência, não falha automática.
    d153_stress = SlabDesigner(250, 30, "C30/37", 500, uls_cases="101", wk_check_enabled=False, stress_check_enabled=True)
    sol153 = d153_stress.rebar_from_phi_spacing(12.0, 200.0)
    # Momento elevado o suficiente para ultrapassar o limiar de sigma_c em QP, mantendo o teste apenas semântico.
    st153 = d153_stress.service_stress_check_detail(200.0, sol153, "ELS-QP")
    ck("v2.15.3 sigma_c QP é aviso OK*", st153["Status"] in ("OK", "OK*"), str(st153))

    # Sem combinação Base+reforço capaz de fechar ELU, a base não pode aparecer como solução adoptada.
    d153_lim = SlabDesigner(
        250, 30, "C30/37", 500, uls_cases="101", wk_check_enabled=False, stress_check_enabled=False,
        optimize_rebar=True, rebar_strategy="Base + reforços", phi_min_mm=10, phi_max_mm=12,
        base_vertical_phi=12, base_vertical_spacing=200, base_horizontal_phi=12, base_horizontal_spacing=200,
        distributed_peak_policy="RAW integral"
    )
    lxx=d153_lim.base_solution_for_direction(False); lyy=d153_lim.base_solution_for_direction(True)
    bxlim, bylim = d153_lim._close_panel_face_pair("+", lxx, lyy, pd.DataFrame({"MEd_x_sup_kNm_m":[500.0],"MEd_y_sup_kNm_m":[500.0]}), pd.DataFrame(), pd.DataFrame(), 200.0, 200.0, False, True, d153_lim.crack_min_as_per_face())
    ck("v2.15.3 sem solução Base+reforço é explícito", bxlim.capacity_limited and bylim.capacity_limited and "SEM SOLUÇÃO" in bxlim.text and "SEM SOLUÇÃO" in bylim.text)

    return f"{len(checks)} testes concluídos: OK\n" + "\n".join(f"- {x}" for x in checks)
