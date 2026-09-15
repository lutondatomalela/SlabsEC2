# -*- coding: utf-8 -*-
"""Validação técnica e auditoria fail-safe do núcleo SlabsEC2.

Este módulo tem dois objectivos distintos:
1) executar casos de referência com formulações independentes das rotinas de projecto;
2) auditar resultados produzidos pelo núcleo e impedir estados OK contraditórios.

A validação automática não substitui uma validação independente de projecto, mas torna regressões
numéricas e inconsistências internas muito mais difíceis de passar despercebidas.
"""
from __future__ import annotations

import math
import re
from typing import Dict, List, Tuple
import pandas as pd
import numpy as np


def _fctm(fck: float) -> float:
    fcm = fck + 8.0
    return 0.30 * fck ** (2.0 / 3.0) if fck <= 50.0 else 2.12 * math.log(1.0 + fcm / 10.0)


def reference_fyd(fyk: float, gamma_s: float = 1.15) -> float:
    return float(fyk) / float(gamma_s)


def reference_fcd(fck: float, gamma_c: float = 1.50, alpha_cc: float = 1.0) -> float:
    return float(alpha_cc) * float(fck) / float(gamma_c)

def reference_block_parameters(fck: float) -> Tuple[float, float, float]:
    fck = max(0.0, min(float(fck), 90.0))
    if fck <= 50.0:
        return 0.80, 1.00, 3.50e-3
    lam = 0.80 - (fck - 50.0) / 400.0
    eta = 1.00 - (fck - 50.0) / 200.0
    eps_cu3 = (2.60 + 35.0 * ((90.0 - fck) / 100.0) ** 4) * 1e-3
    return lam, eta, eps_cu3


def reference_effective_depth(h: float, cnom: float, phi_this: float, phi_other: float) -> float:
    """Posição interior conservadora adoptada no SlabsEC2."""
    return max(float(h) - float(cnom) - float(phi_other) - float(phi_this) / 2.0, 1.0)


def reference_as_min_flexure(h: float, cnom: float, phi: float, fck: float, fyk: float) -> float:
    # EC2 9.3.1.1 / expressão geral de armadura mínima de flexão por faixa b=1 m.
    d = max(float(h) - float(cnom) - float(phi) / 2.0, 1.0)
    return max(0.26 * _fctm(float(fck)) / float(fyk) * 1000.0 * d, 0.0013 * 1000.0 * d)


def reference_as_required_rectangular(m_kNm_m: float, d_mm: float, fck: float, fyk: float,
                                      gamma_c: float = 1.5, gamma_s: float = 1.15,
                                      alpha_cc: float = 1.0) -> float:
    """Referência independente por compatibilidade de extensões (EC2 6.1)."""
    m = abs(float(m_kNm_m)) * 1e6
    if m <= 1e-12:
        return 0.0
    b = 1000.0
    fcd = reference_fcd(fck, gamma_c, alpha_cc)
    fyd = reference_fyd(fyk, gamma_s)
    lam, eta, eps_cu3 = reference_block_parameters(fck)
    A = eta * lam * b * fcd
    disc = float(d_mm) ** 2 - 2.0 * lam * m / max(A, 1e-12)
    if disc <= 0.0:
        return float("inf")
    x = (float(d_mm) - math.sqrt(disc)) / max(lam, 1e-12)
    if x <= 1e-12 or x >= float(d_mm):
        return float("inf")
    eps_s = eps_cu3 * (float(d_mm) - x) / x
    sigma_s = min(fyd, 200000.0 * eps_s)
    return A * x / max(sigma_s, 1e-12)


def reference_mrd(as_mm2_m: float, d_mm: float, fck: float, fyk: float,
                  gamma_c: float = 1.5, gamma_s: float = 1.15,
                  alpha_cc: float = 1.0) -> Tuple[float, float, float, float]:
    """MRd de referência com sigma_s=min(fyd, Es*eps_s)."""
    b = 1000.0
    As = max(float(as_mm2_m), 0.0)
    d = max(float(d_mm), 1e-12)
    fcd = reference_fcd(fck, gamma_c, alpha_cc)
    fyd = reference_fyd(fyk, gamma_s)
    lam, eta, eps_cu3 = reference_block_parameters(fck)
    A = eta * lam * b * fcd
    if As <= 1e-12:
        return 0.0, 0.0, d, 0.0
    x_y = As * fyd / max(A, 1e-12)
    eps_y = eps_cu3 * max(d - x_y, 0.0) / x_y if x_y > 1e-12 else float("inf")
    if x_y < d and eps_y >= fyd/200000.0 - 1e-12:
        x = x_y
    else:
        K = As * 200000.0 * eps_cu3
        x = (-K + math.sqrt(max(K*K + 4.0*A*K*d, 0.0))) / max(2.0*A, 1e-12)
        x = min(max(x, 1e-12), d*(1.0-1e-12))
    z = max(0.0, d - 0.5*lam*x)
    mrd = A*x*z/1e6
    return mrd, x, z, x/d


def reference_cracked_section(m_kNm_m: float, as_mm2_m: float, h_mm: float, cnom_mm: float,
                              phi_mm: float, d_mm: float, fck: float) -> Dict[str, float]:
    """Implementação de referência independente para EC2 7.3.4 (flexão simples, ELS-QP)."""
    m = abs(float(m_kNm_m)) * 1e6
    As = max(float(as_mm2_m), 0.0)
    Es = 200000.0
    fcm = float(fck) + 8.0
    Ecm = 22.0 * (fcm / 10.0) ** 0.3 * 1000.0
    alpha_e = Es / Ecm
    b = 1000.0
    aeAs = alpha_e * As
    disc = aeAs * aeAs + 2.0 * b * aeAs * float(d_mm)
    x = (-aeAs + math.sqrt(max(disc, 0.0))) / b
    x = min(max(x, 1e-9), float(d_mm) - 1e-9)
    Icr = b * x**3 / 3.0 + aeAs * (float(d_mm) - x) ** 2
    sigma_s = alpha_e * m * (float(d_mm) - x) / max(Icr, 1.0)
    hceff = min(2.5 * max(float(h_mm) - float(d_mm), 0.0),
                 max(float(h_mm) - x, 0.0) / 3.0,
                 float(h_mm) / 2.0)
    hceff = max(hceff, 1.0)
    Ac_eff = b * hceff
    rho = max(As / Ac_eff, 1e-12)
    k1, k2, k3, k4 = 0.8, 0.5, 3.4, 0.425
    # Para uma única família uniforme, espaçamento é introduzido externamente no teste;
    # aqui devolvemos os termos independentes que não dependem de s.
    fct_eff = _fctm(float(fck))
    kt = 0.4
    eps_term = (sigma_s - kt * fct_eff / rho * (1.0 + alpha_e * rho)) / Es
    eps_lower = 0.6 * sigma_s / Es
    eps_diff = max(eps_term, eps_lower, 0.0)
    return {
        "x_cr_mm": x, "I_cr_mm4": Icr, "sigma_s_MPa": sigma_s,
        "h_ceff_mm": hceff, "Ac_eff_mm2": Ac_eff, "rho_p_eff": rho,
        "alpha_e": alpha_e, "eps_diff": eps_diff,
    }


def reference_wk(m_kNm_m: float, as_mm2_m: float, h_mm: float, cnom_mm: float,
                 phi_mm: float, spacing_mm: float, d_mm: float, fck: float) -> Dict[str, float]:
    st = reference_cracked_section(m_kNm_m, as_mm2_m, h_mm, cnom_mm, phi_mm, d_mm, fck)
    k1, k2, k3, k4 = 0.8, 0.5, 3.4, 0.425
    rho = st["rho_p_eff"]
    # Recobrimento da família longitudinal considerada: para a posição interior adoptada,
    # c = h-d-phi/2 = c_nom + espessura da camada exterior.
    c_eff = max(float(h_mm) - float(d_mm) - float(phi_mm) / 2.0, float(cnom_mm))
    if float(spacing_mm) <= 5.0 * (c_eff + float(phi_mm) / 2.0) + 1e-9:
        sr = k3 * c_eff + k1 * k2 * k4 * float(phi_mm) / rho
    else:
        sr = 1.3 * max(float(h_mm) - st["x_cr_mm"], 0.0)
    wk = sr * st["eps_diff"]
    st.update({"sr_max_mm": sr, "wk_mm": wk, "c_eff_mm": c_eff, "phi_eq_mm": float(phi_mm)})
    return st


def audit_design_results(df: pd.DataFrame, *, phi_min: float, phi_max: float,
                         wmax_mm: float, wk_enabled: bool, as_max_mm2_m: float,
                         fck: float | None = None, fyk: float | None = None,
                         stress_check_enabled: bool = False, copy_data: bool = True) -> pd.DataFrame:
    """Auditoria fail-safe vectorizada das invariantes estruturais.

    As verificações são idênticas às da rotina linha-a-linha anterior, mas operações numéricas
    são avaliadas em arrays pandas. Apenas as raras linhas com falha constroem mensagens
    individuais. Isto é crítico para tabelas FEM com centenas de milhares de combinações.
    """
    if df is None or df.empty:
        return df
    out = df.copy() if copy_data else df
    n = len(out)
    idx = out.index
    cc = out.get("Case_classification", pd.Series("", index=idx)).astype(str)
    st = out.get("Status", pd.Series("", index=idx)).astype(str)
    relevant = out.get("Design_relevant", pd.Series("Sim", index=idx)).astype(str).ne("Não")
    ok_state = st.isin(["OK", "OK*"])
    fail = pd.Series(False, index=idx)
    notes = pd.Series("", index=idx, dtype=object)

    def append_issue(mask, message):
        nonlocal fail, notes
        mask = pd.Series(mask, index=idx).fillna(False).astype(bool)
        if not mask.any():
            return
        fail |= mask
        if isinstance(message, pd.Series):
            msg = message.reindex(idx).fillna("").astype(str)
        else:
            msg = pd.Series(str(message), index=idx)
        prev = notes.loc[mask]
        notes.loc[mask] = prev.where(prev.eq(""), prev + " | ") + msg.loc[mask]

    util = pd.to_numeric(out.get("util_M", pd.Series(float("nan"), index=idx)), errors="coerce")
    mask = cc.eq("ELU") & relevant & ok_state & util.gt(1.0 + 1e-8)
    if mask.any():
        msg = pd.Series("", index=idx); msg.loc[mask] = "estado " + st.loc[mask] + " incompatível com MEd/MRd=" + util.loc[mask].map(lambda v: f"{v:.4f}") + ">1"
        append_issue(mask, msg)

    wk_ratio = pd.to_numeric(out.get("ELS_wk_ratio", out.get("wk_ratio", pd.Series(float("nan"), index=idx))), errors="coerce")
    mask = cc.eq("ELS-QP") & bool(wk_enabled) & relevant & ok_state & wk_ratio.gt(1.0 + 1e-8)
    if mask.any():
        msg = pd.Series("", index=idx); msg.loc[mask] = "estado " + st.loc[mask] + " incompatível com wk/wmax=" + wk_ratio.loc[mask].map(lambda v: f"{v:.4f}") + ">1"
        append_issue(mask, msg)

    append_issue(cc.eq("ELU") & relevant & ok_state & out.get("Section_domain_valid", pd.Series("Sim", index=idx)).astype(str).ne("Sim"),
                 "estado ELU OK incompatível com secção resistente não resolvida")
    if stress_check_enabled:
        els_st = out.get("ELS_stress_status", pd.Series("", index=idx)).astype(str)
        append_issue(cc.eq("ELS-CHAR") & relevant & ok_state & els_st.isin(["Não conforme", "Verificar"]),
                     "estado OK incompatível com limitação de tensões ELS característica")
        append_issue(cc.eq("ELS-QP") & relevant & ok_state & els_st.eq("Verificar"),
                     "estado ELS-QP OK incompatível com sigma_c>0,45fck / fluência linear não demonstrada")
    append_issue(relevant & ok_state & out.get("Constructability_status", pd.Series("", index=idx)).astype(str).eq("Verificar"),
                 "estado OK incompatível com solução de armadura marcada para revisão construtiva")

    for lab, bkey, akey, pkey, btkey, atkey in (
        ("X+", "Asx+_base_mm2_m", "Asx+_add_mm2_m", "Asx+_prov_mm2_m", "X+_base", "X+_additional"),
        ("X-", "Asx-_base_mm2_m", "Asx-_add_mm2_m", "Asx-_prov_mm2_m", "X-_base", "X-_additional"),
        ("Y+", "Asy+_base_mm2_m", "Asy+_add_mm2_m", "Asy+_prov_mm2_m", "Y+_base", "Y+_additional"),
        ("Y-", "Asy-_base_mm2_m", "Asy-_add_mm2_m", "Asy-_prov_mm2_m", "Y-_base", "Y-_additional")):
        bv = pd.to_numeric(out.get(bkey, pd.Series(float("nan"), index=idx)), errors="coerce")
        av = pd.to_numeric(out.get(akey, pd.Series(float("nan"), index=idx)), errors="coerce")
        pv = pd.to_numeric(out.get(pkey, pd.Series(float("nan"), index=idx)), errors="coerce")
        tol = (pv.abs().clip(lower=1.0) * 1e-6).clip(lower=1e-5)
        valid = bv.notna() & av.notna() & pv.notna() & bv.gt(1e-9)
        append_issue(valid & ((bv + av - pv).abs() > tol), f"{lab}: As,base+As,ref difere de As,prov")
        # A modulação é constante por solução; analisar combinações textuais únicas, não cada linha.
        if btkey in out.columns and atkey in out.columns:
            pairs = out[[btkey, atkey]].fillna("").astype(str).drop_duplicates()
            bad_pairs = set()
            for br, ar in pairs.itertuples(index=False, name=None):
                if br in ("", "-") or ar in ("", "-"):
                    continue
                mb = re.search(r"//\s*(\d+(?:[.,]\d+)?)", br); ma = re.search(r"//\s*(\d+(?:[.,]\d+)?)", ar)
                if mb and ma and abs(float(mb.group(1).replace(",","."))-float(ma.group(1).replace(",","."))) > 1e-9:
                    bad_pairs.add((br, ar))
            if bad_pairs:
                pair_mask = pd.Series(False, index=idx)
                btxt = out[btkey].fillna("").astype(str); atxt = out[atkey].fillna("").astype(str)
                for br, ar in bad_pairs:
                    pair_mask |= btxt.eq(br) & atxt.eq(ar)
                append_issue(pair_mask, f"{lab}: base e reforço têm espaçamentos diferentes")

    # Revalidação independente de MRd por combinações únicas (As,d,MRd), normalmente 4 por painel.
    if fck is not None and fyk is not None:
        elu_rel = cc.eq("ELU") & relevant
        for lab, as_key, d_key, mrd_key in (
            ("X+", "Asx+_prov_mm2_m", "d_x_sup_mm", "MRd_x+_kNm_m"),
            ("X-", "Asx-_prov_mm2_m", "d_x_inf_mm", "MRd_x-_kNm_m"),
            ("Y+", "Asy+_prov_mm2_m", "d_y_sup_mm", "MRd_y+_kNm_m"),
            ("Y-", "Asy-_prov_mm2_m", "d_y_inf_mm", "MRd_y-_kNm_m")):
            if not all(k in out.columns for k in (as_key, d_key, mrd_key)):
                continue
            sub = out.loc[elu_rel, [as_key, d_key, mrd_key]].dropna().drop_duplicates()
            bad_keys = []
            for Asv, dv, reported in sub.itertuples(index=False, name=None):
                Asv=float(Asv); dv=float(dv); reported=float(reported)
                if dv <= 0: continue
                ref_mrd = reference_mrd(Asv, dv, float(fck), float(fyk))[0]
                if abs(reported-ref_mrd) > max(1e-5, 1e-6*max(abs(ref_mrd),1.0)):
                    bad_keys.append((Asv,dv,reported,ref_mrd))
            if bad_keys:
                av=pd.to_numeric(out[as_key],errors="coerce"); dvv=pd.to_numeric(out[d_key],errors="coerce"); rv=pd.to_numeric(out[mrd_key],errors="coerce")
                for Asv,dv,reported,ref_mrd in bad_keys:
                    mask = elu_rel & av.eq(Asv) & dvv.eq(dv) & rv.eq(reported)
                    append_issue(mask, f"{mrd_key} difere da revalidação independente {ref_mrd:.6g}")

    # Invariante fundamental: um estado ELU OK nunca pode ter As,prov < As,req na face/direção.
    for pkey, rkey in (
        ("Asx+_prov_mm2_m", "Asx+_req_mm2_m"), ("Asx-_prov_mm2_m", "Asx-_req_mm2_m"),
        ("Asy+_prov_mm2_m", "Asy+_req_mm2_m"), ("Asy-_prov_mm2_m", "Asy-_req_mm2_m")):
        if pkey in out.columns and rkey in out.columns:
            pv = pd.to_numeric(out[pkey], errors="coerce")
            rv = pd.to_numeric(out[rkey], errors="coerce")
            append_issue(cc.eq("ELU") & relevant & ok_state & pv.lt(rv - 1e-6), f"{pkey} < {rkey}")

    for key in ("Asx+_prov_mm2_m", "Asx-_prov_mm2_m", "Asy+_prov_mm2_m", "Asy-_prov_mm2_m"):
        if key in out.columns:
            val = pd.to_numeric(out[key], errors="coerce")
            append_issue(val.gt(as_max_mm2_m + 1e-6), f"{key} excede As,max={as_max_mm2_m:.1f} mm²/m")
    for key in ("phi_ctrl_x+_mm", "phi_ctrl_x-_mm", "phi_ctrl_y+_mm", "phi_ctrl_y-_mm"):
        if key in out.columns:
            val = pd.to_numeric(out[key], errors="coerce")
            append_issue(val.notna() & (val.lt(phi_min - 1e-9) | val.gt(phi_max + 1e-9)), f"{key} fora de Ø{phi_min:g}–Ø{phi_max:g}")

    out["Integrity_status"] = pd.Categorical(np.where(fail.to_numpy(), "Falha interna", "OK"))
    out["Integrity_note"] = notes.where(fail, "invariantes internas satisfeitas")
    if fail.any():
        out.loc[fail, "Status"] = "Não conforme"
        if "Verification_reason" in out.columns:
            old = out.loc[fail, "Verification_reason"].fillna("").astype(str)
            prefix = old.where(old.eq(""), old + " | ")
            out.loc[fail, "Verification_reason"] = prefix + "Falha de coerência interna: " + out.loc[fail, "Integrity_note"].astype(str)
        if "Recommended_action" in out.columns:
            out.loc[fail, "Recommended_action"] = "Não adoptar o resultado; rever dados e núcleo de cálculo antes de utilizar em projecto."
    return out

def _safe_num(v) -> float:
    try:
        if pd.isna(v):
            return float("nan")
        return float(v)
    except Exception:
        return float("nan")


def run_engineering_validation_suite() -> str:
    """Casos de referência de engenharia, independentes do autoteste funcional."""
    from .designer import SlabDesigner
    from .utils import bar_area_mm2

    checks: List[str] = []
    details: List[str] = []

    def ck(name: str, cond: bool, detail: str = ""):
        if not bool(cond):
            raise AssertionError(f"{name}: {detail or 'falhou'}")
        checks.append(name)
        if detail:
            details.append(f"{name}: {detail}")

    d = SlabDesigner(250, 30, "C30/37", 500, uls_cases="101-104", qp_cases="301-302",
                     wk_check_enabled=True, optimize_rebar=True, rebar_strategy="Substituir base",
                     phi_min_mm=8, phi_max_mm=16, deflection_unit="mm")

    # 1. Geometria e materiais.
    deff = d.layer_effective_depth("sup", "X", 12, 12)
    deff_ref = 250.0 - 30.0 - 12.0/2.0
    ck("V01 d camada exterior configurada", abs(deff - deff_ref) < 1e-10, f"d={deff:.3f} mm")
    amin_ref = reference_as_min_flexure(250, 30, 12, 30, 500)
    amin = d.slab_flexural_min_per_face(12)
    ck("V02 As,min flexão", abs(amin - amin_ref) / amin_ref < 1e-10, f"As,min={amin:.2f} mm²/m")

    # 2. Flexão: vários níveis de momento comparados com implementação independente.
    for j, m in enumerate((25.0, 50.0, 100.0, 150.0), start=3):
        ar = d.flexural_as_required(m, d_mm=deff)
        rr = reference_as_required_rectangular(m, deff, 30, 500)
        ck(f"V{j:02d} As,req M={m:g}", abs(ar - rr) / max(rr, 1.0) < 1e-10,
           f"calc={ar:.3f}; ref={rr:.3f} mm²/m")

    # 3. MRd e equilíbrio inverso.
    for j, As in enumerate((500.0, 1000.0, 2000.0), start=7):
        m1, x1, z1, xd1 = d.flexural_metrics(As, deff)
        m2, x2, z2, xd2 = reference_mrd(As, deff, 30, 500)
        ck(f"V{j:02d} MRd As={As:g}", abs(m1 - m2) / max(abs(m2), 1.0) < 1e-10,
           f"MRd={m1:.3f} kNm/m; x/d={xd1:.4f}")

    # 4. Simetria e monotonicidade.
    ck("V10 As,req monotónico", d.flexural_as_required(120, d_mm=deff) > d.flexural_as_required(80, d_mm=deff))
    ck("V11 sinal não altera As absoluto", abs(d.flexural_as_required(-80, d_mm=deff) - d.flexural_as_required(80, d_mm=deff)) < 1e-12)

    # 5. Escolha construtiva e limites.
    s = d.choose_rebar(900.0, max_spacing=400.0)
    ck("V12 solução simples suficiente", s.as_prov + 1e-9 >= 900.0 and s.phi <= 16.0)
    ck("V13 preferência s>=100 quando viável", s.spacing >= 100.0, s.text)
    slim = d.choose_rebar(9000.0, max_spacing=400.0)
    ck("V14 Ømax nunca excedido", slim.phi <= 16.0 + 1e-9 and slim.capacity_limited)

    # 6. Fendilhação: comparação independente exacta para família uniforme.
    sol = d.rebar_from_phi_spacing(12, 150)
    dc = d.layer_effective_depth("sup", "X", 12, 12)
    ref = reference_wk(35.0, sol.as_prov, 250, 30, 12, 150, dc, 30)
    calc = d.cracked_section_service_state(35.0, sol, d_mm=dc)
    for k, key in enumerate(("x_cr_mm", "sigma_s_MPa", "h_ceff_mm", "Ac_eff_mm2", "rho_p_eff", "sr_max_mm", "wk_mm"), start=15):
        a = float(calc[key]); b = float(ref[key])
        ck(f"V{k:02d} fendilhação {key}", abs(a - b) / max(abs(b), 1e-9) < 1e-10,
           f"calc={a:.6g}; ref={b:.6g}")
    ck("V21A recobrimento efectivo interior", abs(float(calc["c_eff_mm"]) - float(ref["c_eff_mm"])) < 1e-10,
       f"c_eff={float(calc['c_eff_mm']):.3f} mm")
    # Diâmetro equivalente EC2 7.12 para duas famílias intercaladas.
    comp = d.rebar_from_phi_spacing(10, 200)
    comp.base_text = "Ø10//200"; comp.add_text = "Ø8//200"; comp.text_override = "Ø10//200 + Ø8//200"
    phi_eq, s_eq, nf = d.rebar_crack_geometry(comp)
    phi_eq_ref = (10.0**2 + 8.0**2) / (10.0 + 8.0)
    ck("V21B diâmetro equivalente EC2 7.12", abs(phi_eq - phi_eq_ref) < 1e-12 and abs(s_eq - 100.0) < 1e-12,
       f"phi_eq={phi_eq:.6f} mm; s_eff={s_eq:.1f} mm")

    # v2.14.1: geometria física de Base + reforço e preservação da base configurada.
    db = SlabDesigner(250, 30, "C30/37", 500, uls_cases="101", phi_min_mm=8, phi_max_mm=16,
                      optimize_rebar=True, rebar_strategy="Base + reforços",
                      base_vertical_phi=10, base_vertical_spacing=200, base_horizontal_phi=12, base_horizontal_spacing=200)
    cphys = db.rebar_from_phi_spacing(10, 200)
    cphys.base_text="Ø10//200"; cphys.add_text="Ø16//200"; cphys.text_override="Ø10//200 + Ø16//200"
    cphys.as_base=bar_area_mm2(10)*1000/200; cphys.as_add=bar_area_mm2(16)*1000/200; cphys.as_prov=cphys.as_base+cphys.as_add
    gphys = db.rebar_layer_geometry(cphys)
    cref = (cphys.as_base*5.0 + cphys.as_add*8.0)/cphys.as_prov
    ck("V21C centróide composto ponderado", abs(gphys["centroid_from_layer_face_mm"]-cref) < 1e-12, f"cg={gphys['centroid_from_layer_face_mm']:.6f} mm")
    yphys = db.rebar_from_phi_spacing(12, 200)
    dphys = db.layer_effective_depth_from_solutions("sup", "X", cphys, yphys)
    ck("V21D d físico da solução composta", abs(dphys-(250-30-cref)) < 1e-12, f"d={dphys:.6f} mm")
    srational = db.optimize_rebar_solution(1200.0, 400.0, True, "X+")
    ck("V21E base preservada com reforço dominante", srational.base_text=="Ø10//200" and "+" in srational.text and "base fixa preservada" in srational.optimization_note, srational.text)

    # 7. Propriedades físicas esperadas de wk.
    sol_dense = d.rebar_from_phi_spacing(12, 100)
    w150 = d.cracked_section_service_state(35.0, sol, d_mm=dc)["wk_mm"]
    w100 = d.cracked_section_service_state(35.0, sol_dense, d_mm=dc)["wk_mm"]
    ck("V22 mais armadura reduz wk", w100 < w150, f"wk150={w150:.4f}; wk100={w100:.4f}")
    w_low = d.cracked_section_service_state(20.0, sol, d_mm=dc)["wk_mm"]
    w_high = d.cracked_section_service_state(50.0, sol, d_mm=dc)["wk_mm"]
    ck("V23 maior momento aumenta wk", w_high > w_low)

    # 8. Envelope completo e solução única por painel.
    rows = []
    for case, cls_scale in [("101 (C)", 1.00), ("102 (C)", 0.85), ("103 (C)", 0.75), ("104 (C)", 0.65),
                            ("301 (C)", 0.55), ("302 (C)", 0.50)]:
        for node, f in [(1, 1.0), (2, 0.72), (3, 0.45)]:
            rows.append(dict(panel="PV", node=str(node), case=case, case_id=case.split()[0],
                             mxx=0, myy=0, mxy=0,
                             mxx_wa_pos=85*cls_scale*f, mxx_wa_neg=55*cls_scale*f,
                             myy_wa_pos=70*cls_scale*f, myy_wa_neg=40*cls_scale*f,
                             qxx=0, qyy=0, nxx=0, nyy=0, nxy=0, ugz=0,
                             __moment_input_mode="direct_wa", __row_order=len(rows)))
    rdf = d.design_dataframe(pd.DataFrame(rows))
    rebar_cols = ["X+_rebar", "X-_rebar", "Y+_rebar", "Y-_rebar"]
    ck("V24 solução única painel", len(rdf[rebar_cols].drop_duplicates()) == 1)
    elu = rdf[rdf["Case_classification"] == "ELU"]
    qp = rdf[rdf["Case_classification"] == "ELS-QP"]
    ck("V25 todos ELU reavaliados", not elu.empty and (elu["util_M"] <= 1.0 + 1e-9).all())
    ck("V26 todos QP reavaliados", not qp.empty and (qp["ELS_wk_ratio"] <= 1.0 + 1e-9).all())
    ck("V27 integridade interna", set(rdf["Integrity_status"].astype(str)) == {"OK"})

    # 9. Casos patológicos fail-safe.
    bad = rdf.copy()
    ix = bad[bad["Case_classification"] == "ELU"].index[0]
    bad.at[ix, "Status"] = "OK"
    bad.at[ix, "util_M"] = 1.25
    audited = audit_design_results(bad, phi_min=8, phi_max=16, wmax_mm=0.30, wk_enabled=True, as_max_mm2_m=10000.0)
    ck("V28 falso OK ELU bloqueado", audited.at[ix, "Integrity_status"] == "Falha interna" and audited.at[ix, "Status"] == "Não conforme")

    iq = bad[bad["Case_classification"] == "ELS-QP"].index[0]
    bad2 = rdf.copy(); bad2.at[iq, "Status"] = "OK"; bad2.at[iq, "ELS_wk_ratio"] = 1.20
    audited2 = audit_design_results(bad2, phi_min=8, phi_max=16, wmax_mm=0.30, wk_enabled=True, as_max_mm2_m=10000.0)
    ck("V29 falso OK ELS bloqueado", audited2.at[iq, "Integrity_status"] == "Falha interna" and audited2.at[iq, "Status"] == "Não conforme")

    # 10. Solução impossível dentro de Ømax mantém não conformidade.
    dh = SlabDesigner(200, 35, "C30/37", 500, uls_cases="101", phi_min_mm=8, phi_max_mm=16,
                      optimize_rebar=True, rebar_strategy="Substituir base")
    hard = pd.DataFrame([dict(panel="PH", node="1", case="101 (C)", case_id="101", mxx=0, myy=0, mxy=0,
                              mxx_wa_pos=500.0, mxx_wa_neg=0, myy_wa_pos=0, myy_wa_neg=0,
                              qxx=0,qyy=0,nxx=0,nyy=0,nxy=0,ugz=0,__moment_input_mode="direct_wa",__row_order=0)])
    hr = dh.design_dataframe(hard)
    ck("V30 caso impossível não passa", str(hr.iloc[0]["Status"]) == "Não conforme" and float(hr.iloc[0]["util_M"]) > 1.0)
    ck("V31 caso impossível sinaliza limite", str(hr.iloc[0].get("Rebar_limit_reached", "")) == "Sim")

    # 11. v2.8 — domínio resistente, betão de alta resistência e ELS tensões.
    d60 = SlabDesigner(250, 30, "C60/75", 500, uls_cases="101", phi_min_mm=8, phi_max_mm=16)
    d60eff = d60.layer_effective_depth("sup", "X", 12, 12)
    ar60 = d60.flexural_as_required(120.0, d_mm=d60eff)
    rr60 = reference_as_required_rectangular(120.0, d60eff, 60.0, 500.0)
    ck("V32 bloco EC2 fck>50 As,req", abs(ar60-rr60)/max(rr60,1.0) < 1e-10, f"As60={ar60:.3f} mm²/m")
    m60 = d60.flexural_metrics(1800.0, d60eff)[0]
    mr60 = reference_mrd(1800.0, d60eff, 60.0, 500.0)[0]
    ck("V33 bloco EC2 fck>50 MRd", abs(m60-mr60)/max(mr60,1.0) < 1e-10, f"MRd60={m60:.3f} kNm/m")
    fs_over = d.flexural_section_state(10000.0, dc)
    ck("V34 compatibilidade de extensões para aço abaixo de fyd", fs_over["section_domain_valid"] == "Sim" and fs_over["steel_yields"] == "Não")
    ck("V35 compatibilidade não trunca MRd no início da não-cedência", float(fs_over["MRd_kNm_m"]) > float(fs_over["MRd_singly_lim_kNm_m"]) + 1e-9)

    # secção não fendilhada: wk deve ser exactamente zero abaixo de Mcr.
    low = d.cracked_section_service_state(1.0, sol, d_mm=dc)
    ck("V36 secção não fendilhada reconhecida", low.get("section_cracked") == "Não" and abs(float(low["wk_mm"])) < 1e-12, f"Mcr={low.get('Mcr_kNm_m',0):.3f}")

    stchar = d.service_stress_check_detail(35.0, sol, "ELS-CHAR", d_mm=dc)
    ck("V37 limite sigma_s característica", abs(float(stchar["sigma_s_lim_MPa"])-0.8*d.fyk) < 1e-12)
    stqp = d.service_stress_check_detail(35.0, sol, "ELS-QP", d_mm=dc)
    ck("V38 limite sigma_c QP", abs(float(stqp["sigma_c_qp_lim_MPa"])-0.45*d.fck) < 1e-12)
    sol_els = d.optimize_solution_for_service_stress(80.0, sol, d.slab_flexural_min_per_face(), 400.0, "X+", d_mm=dc)
    stchar_opt = d.service_stress_check_detail(80.0, sol_els, "ELS-CHAR", d_mm=dc)
    ck("V38A optimizador ELS característica", float(stchar_opt["sigma_s_MPa"]) <= float(stchar_opt["sigma_s_lim_MPa"]) + 1e-9, f"sigma_s={stchar_opt['sigma_s_MPa']:.3f} MPa")

    # Auditoria independente do MRd reportado: adulteração deve ser bloqueada.
    badm = rdf.copy()
    im = badm[badm["Case_classification"] == "ELU"].index[0]
    badm.at[im, "MRd_x+_kNm_m"] = float(badm.at[im, "MRd_x+_kNm_m"]) * 1.10
    audm = audit_design_results(badm, phi_min=8, phi_max=16, wmax_mm=0.30, wk_enabled=True,
                                as_max_mm2_m=10000.0, fck=30.0, fyk=500.0, stress_check_enabled=True)
    ck("V39 revalidação MRd independente", audm.at[im, "Integrity_status"] == "Falha interna")

    header = [
        "SlabsEC2 — Validação técnica do núcleo de armaduras",
        f"Resultado: {len(checks)}/{len(checks)} verificações de referência concluídas sem falhas.",
        "Âmbito: flexão ELU, domínio da secção, betões até C90/105, As,min, MRd, escolha Ø/s, ELS tensões, fendilhação ELS-QP, envelopes e invariantes fail-safe.",
        "Nota: esta bateria é complementar à validação manual/independente e não constitui certificação externa do software.",
        "",
    ]
    body = [f"- {x}" for x in checks]
    if details:
        body += ["", "Valores de controlo:"] + [f"  {x}" for x in details]
    return "\n".join(header + body)
