# -*- coding: utf-8 -*-
"""Diagnóstico estatístico de picos locais em resultados de placa.

Este módulo não suaviza nem substitui esforços. A classificação serve apenas para
identificar concentrações locais potenciais e separar, quando o utilizador o confirma
explicitamente, o dimensionamento distribuído da verificação local de uma singularidade.
"""
from __future__ import annotations

import re
from typing import Iterable, Set

import pandas as pd

from .utils import safe_float


def canonical_node_id(value: object) -> str:
    if value is None:
        return ""
    s = str(value).strip()
    if not s:
        return ""
    try:
        f = float(s.replace(",", "."))
        if abs(f - round(f)) < 1e-9:
            return str(int(round(f)))
    except Exception:
        pass
    return s


def parse_node_spec(text: object) -> Set[str]:
    """Lê uma lista explícita de nós.

    Aceita separação por espaço, vírgula, ponto e vírgula ou quebra de linha.
    Não expande intervalos: a confirmação de singularidades deve ser deliberada nó a nó.
    """
    if text is None:
        return set()
    raw = str(text).strip()
    if not raw:
        return set()
    tokens = [t.strip() for t in re.split(r"[\s,;]+", raw) if t.strip()]
    return {canonical_node_id(t) for t in tokens if canonical_node_id(t)}


def _moment_magnitude(df: pd.DataFrame) -> pd.Series:
    cols = [c for c in (
        "MEd_x_sup_kNm_m", "MEd_x_inf_kNm_m", "MEd_y_sup_kNm_m", "MEd_y_inf_kNm_m"
    ) if c in df.columns]
    if not cols:
        return pd.Series([0.0] * len(df), index=df.index, dtype=float)
    return df[cols].apply(pd.to_numeric, errors="coerce").fillna(0.0).abs().max(axis=1)


def assess_panel_peak(grp: pd.DataFrame, ratio_threshold: float = 1.50) -> dict:
    """Caracteriza estatisticamente a concentração de esforços num painel.

    O critério base é max/P95, complementado por P99, extensão por número de nós e
    recorrência do pico no mesmo nó em diferentes combinações ELU.
    """
    if grp is None or grp.empty:
        return {
            "Pico_FEM": "Não", "Classificação_pico": "Sem dados", "Pico_ratio_max_P95": 0.0,
            "Pico_ratio_max_P99": 0.0, "Mmax_kNm_m": 0.0, "P95_kNm_m": 0.0,
            "P99_kNm_m": 0.0, "P95_nodal_kNm_m": 0.0, "P99_nodal_kNm_m": 0.0,
            "Nó_pico": "", "Caso_pico": "", "N_nós": 0,
            "N_nós_>=90%Mmax": 0, "Frac_nós_>=90%Mmax": 0.0,
            "N_candidatos_P99": 0, "Nós_candidatos_P99": "",
            "N_casos_mesmo_nó_>=80%Mmax": 0, "Recomendação_pico": "Sem dados suficientes."
        }

    g = grp.copy()
    if "Case_classification" in g.columns:
        gelu = g[g["Case_classification"].astype(str) == "ELU"].copy()
        if not gelu.empty:
            g = gelu

    mag = _moment_magnitude(g)
    mmax = safe_float(mag.max(), 0.0)
    p95 = safe_float(mag.quantile(0.95), 0.0)
    p99 = safe_float(mag.quantile(0.99), 0.0)
    ratio95 = mmax / p95 if p95 > 1e-9 else (1.0 if mmax <= 1e-9 else 999.0)
    ratio99 = mmax / p99 if p99 > 1e-9 else (1.0 if mmax <= 1e-9 else 999.0)

    idx = mag.idxmax() if len(mag) else g.index[0]
    rmax = g.loc[idx]
    peak_node = canonical_node_id(rmax.get("Node", rmax.get("node", "")))
    peak_case = str(rmax.get("Case", rmax.get("case", "")))

    if "Node" in g.columns:
        nodes = g["Node"].map(canonical_node_id)
    elif "node" in g.columns:
        nodes = g["node"].map(canonical_node_id)
    else:
        nodes = pd.Series([str(i) for i in g.index], index=g.index)

    node_max = mag.groupby(nodes, observed=True).max()
    n_nodes = int(len(node_max))
    p95_node = safe_float(node_max.quantile(0.95), 0.0) if n_nodes else 0.0
    p99_node = safe_float(node_max.quantile(0.99), 0.0) if n_nodes else 0.0
    candidate_nodes = node_max[node_max >= p99_node - 1e-9].sort_values(ascending=False) if p99_node > 1e-9 else pd.Series(dtype=float)
    candidate_txt = ", ".join(f"{idx} ({val:.1f})" for idx, val in candidate_nodes.head(12).items())
    n90 = int((node_max >= 0.90 * mmax - 1e-9).sum()) if mmax > 1e-9 else 0
    frac90 = n90 / n_nodes if n_nodes else 0.0

    same_node_mask = nodes.astype(str) == str(peak_node)
    n_cases_near = int((mag[same_node_mask] >= 0.80 * mmax - 1e-9).sum()) if mmax > 1e-9 else 0

    is_peak = bool(mmax > 1e-6 and ratio95 > float(ratio_threshold))
    if not is_peak:
        classification = "Sem pico local relevante"
        recommendation = "Sem concentração local relevante pelo critério estatístico adoptado."
    else:
        # A extensão por nós é apenas um indicador: sem coordenadas não existe suavização espacial.
        if frac90 <= 0.01 and n_cases_near <= 2:
            classification = "Pico local potencial — isolado"
            recommendation = (
                "Localizar o nó no modelo e confirmar apoio, carga concentrada, canto, abertura, ligação rígida ou singularidade de malha. "
                "Não substituir automaticamente o máximo por P95/P99."
            )
        elif frac90 <= 0.03:
            classification = "Pico local potencial — recorrente"
            recommendation = (
                "O pico está concentrado em poucos nós e repete-se em várias combinações. Confirmar se corresponde a uma descontinuidade física. "
                "Se for singularidade confirmada, separar armadura distribuída da verificação/pormenorização local."
            )
        else:
            classification = "Zona de esforço elevado — não tratar como singularidade automaticamente"
            recommendation = (
                "A solicitação elevada abrange uma fracção não desprezável dos nós; deve ser considerada representativa até existir avaliação espacial independente."
            )

    return {
        "Pico_FEM": "Sim" if is_peak else "Não",
        "Classificação_pico": classification,
        "Pico_ratio_max_P95": ratio95,
        "Pico_ratio_max_P99": ratio99,
        "Mmax_kNm_m": mmax,
        "P95_kNm_m": p95,
        "P99_kNm_m": p99,
        "P95_nodal_kNm_m": p95_node,
        "P99_nodal_kNm_m": p99_node,
        "N_candidatos_P99": int(len(candidate_nodes)),
        "Nós_candidatos_P99": candidate_txt,
        "Nó_pico": peak_node,
        "Caso_pico": peak_case,
        "N_nós": n_nodes,
        "N_nós_>=90%Mmax": n90,
        "Frac_nós_>=90%Mmax": frac90,
        "N_casos_mesmo_nó_>=80%Mmax": n_cases_near,
        "Recomendação_pico": recommendation,
    }


def build_peak_assessment(results: pd.DataFrame, ratio_threshold: float = 1.50) -> pd.DataFrame:
    if results is None or results.empty or "Panel" not in results.columns:
        return pd.DataFrame()
    rows = []
    for panel, grp in results.groupby("Panel", dropna=False, observed=True):
        row = {"Panel": panel}
        row.update(assess_panel_peak(grp, ratio_threshold=ratio_threshold))
        if "Singular_node_confirmed" in grp.columns:
            sing = grp[grp["Singular_node_confirmed"].astype(str) == "Sim"]
            sing_nodes = sorted({canonical_node_id(v) for v in sing.get("Node", pd.Series(dtype=object)) if canonical_node_id(v)})
            row["Nós_singulares_confirmados"] = ", ".join(sing_nodes)
            row["N_singulares_confirmados"] = len(sing_nodes)
            row["Util_local_singular_max"] = safe_float(sing.get("Local_peak_util_raw", pd.Series([0.0])).max(), 0.0) if not sing.empty else 0.0
            row["wk_wmax_local_singular_max"] = safe_float(sing.get("Local_peak_wk_ratio_raw", pd.Series([0.0])).max(), 0.0) if not sing.empty else 0.0
            row["Estado_local_singular"] = "Verificar localmente" if sing_nodes else "Não aplicável"
            row["Zona_singular_confirmada"] = "Sim" if sing_nodes else "Não"
        else:
            row["Nós_singulares_confirmados"] = ""
            row["N_singulares_confirmados"] = 0
            row["Util_local_singular_max"] = 0.0
            row["wk_wmax_local_singular_max"] = 0.0
            row["Estado_local_singular"] = "Não aplicável"
            row["Zona_singular_confirmada"] = "Não"
        rows.append(row)
    return pd.DataFrame(rows)


def build_peak_candidates(results: pd.DataFrame, panel: object, percentile: float = 0.99) -> pd.DataFrame:
    """Devolve nós candidatos a zona singular para um painel.

    A lista é puramente diagnóstica: contém os nós cujo máximo nodal de momento
    equivalente é superior ao percentil indicado. Nenhum nó é confirmado ou excluído
    automaticamente.
    """
    if results is None or results.empty or "Panel" not in results.columns:
        return pd.DataFrame()
    g = results[results["Panel"].astype(str) == str(panel)].copy()
    if g.empty:
        return pd.DataFrame()
    if "Case_classification" in g.columns:
        gelu = g[g["Case_classification"].astype(str) == "ELU"].copy()
        if not gelu.empty:
            g = gelu

    mag = _moment_magnitude(g)
    if "Node" in g.columns:
        node_ids = g["Node"].map(canonical_node_id)
    elif "node" in g.columns:
        node_ids = g["node"].map(canonical_node_id)
    else:
        node_ids = pd.Series([str(i) for i in g.index], index=g.index)

    work = pd.DataFrame({"Node_id": node_ids, "Mmag": mag}, index=g.index)
    work["Case"] = g.get("Case", g.get("case", "")).astype(str) if isinstance(g.get("Case", g.get("case", "")), pd.Series) else ""
    work = work[work["Node_id"].astype(str) != ""].copy()
    if work.empty:
        return pd.DataFrame()

    node_max = work.groupby("Node_id")["Mmag"].max()
    threshold = safe_float(node_max.quantile(float(percentile)), 0.0)
    if threshold <= 1e-9:
        return pd.DataFrame()
    candidates = node_max[node_max >= threshold - 1e-9].sort_values(ascending=False)
    panel_mmax = safe_float(node_max.max(), 0.0)
    confirmed = set()
    if "Singular_node_confirmed" in g.columns:
        sg = g[g["Singular_node_confirmed"].astype(str) == "Sim"]
        confirmed = {canonical_node_id(v) for v in sg.get("Node", pd.Series(dtype=object)) if canonical_node_id(v)}

    rows = []
    for node, val in candidates.items():
        idxs = work.index[work["Node_id"].astype(str) == str(node)]
        sub = work.loc[idxs]
        i_max = sub["Mmag"].idxmax()
        gov_case = str(sub.loc[i_max, "Case"])
        n_near = int((sub["Mmag"] >= 0.80 * float(val) - 1e-9).sum()) if float(val) > 1e-9 else 0
        rows.append({
            "Panel": panel,
            "Node": str(node),
            "Mmax_nodal_kNm_m": float(val),
            "Mmax_rel_panel": float(val) / panel_mmax if panel_mmax > 1e-9 else 0.0,
            "Caso_governante": gov_case,
            "N_casos_>=80%Mmax_nodal": n_near,
            "Confirmado_singular": "Sim" if str(node) in confirmed else "Não",
            "Critério_candidato": f">= P{int(round(float(percentile)*100))} nodal ({threshold:.1f} kNm/m)",
        })
    return pd.DataFrame(rows)


def enrich_peak_assessment_spatial(results: pd.DataFrame, peaks: pd.DataFrame, nodes: pd.DataFrame,
                                   local_radius_factor: float = 2.5) -> pd.DataFrame:
    """Acrescenta diagnóstico espacial local sem alterar qualquer esforço de cálculo.

    Compara o máximo nodal do painel com a mediana/P95 dos nós fisicamente vizinhos do nó crítico.
    A função nunca confirma singularidades, nunca substitui Mmax por percentis e nunca exclui nós.
    """
    if peaks is None or peaks.empty:
        return peaks
    out = peaks.copy()
    defaults = {
        "Pico_spatial_check": "Não avaliado", "N_vizinhos_locais": 0,
        "Raio_vizinhança_m": float("nan"), "Pico_ratio_max_mediana_local": float("nan"),
        "Pico_ratio_max_P95_local": float("nan"), "Classificação_espacial_pico": "Sem geometria",
        "Sensibilidade_malha": "Não avaliada", "Política_valor_dimensionamento": "RAW preservado",
        "Singularidade_automática": "Nunca",
    }
    for c, v in defaults.items():
        if c not in out.columns:
            out[c] = v
    if results is None or results.empty or nodes is None or nodes.empty or not {"node", "x", "y", "z"}.issubset(nodes.columns):
        return out

    lookup = {}
    for _, r in nodes.iterrows():
        nid = canonical_node_id(r.get("node", ""))
        if not nid:
            continue
        x = safe_float(r.get("x"), float("nan")); y = safe_float(r.get("y"), float("nan")); z = safe_float(r.get("z"), float("nan"))
        if all(pd.notna(v) for v in (x, y, z)):
            lookup[nid] = (float(x), float(y), float(z))

    for ix, pr in out.iterrows():
        panel = pr.get("Panel", "")
        peak_node = canonical_node_id(pr.get("Nó_pico", ""))
        if peak_node not in lookup:
            continue
        g = results[results["Panel"].astype(str) == str(panel)].copy()
        if g.empty:
            continue
        if "Case_classification" in g.columns:
            ge = g[g["Case_classification"].astype(str) == "ELU"].copy()
            if not ge.empty:
                g = ge
        if "Node" not in g.columns:
            continue
        mag = _moment_magnitude(g)
        ids = g["Node"].map(canonical_node_id)
        nodal = mag.groupby(ids).max()
        nodal = nodal[nodal.index.astype(str) != ""]
        known = [(nid, safe_float(val, 0.0), lookup[nid]) for nid, val in nodal.items() if nid in lookup]
        if len(known) < 3:
            continue
        px, py, pz = lookup[peak_node]
        # passo robusto por diferenças de coordenadas; suficiente para definir a vizinhança local
        xs = sorted({round(p[2][0], 6) for p in known}); ys = sorted({round(p[2][1], 6) for p in known})
        diffs = []
        if len(xs) > 1:
            dx = [b-a for a,b in zip(xs[:-1], xs[1:]) if b-a > 1e-6]
            if dx: diffs.append(float(pd.Series(dx).median()))
        if len(ys) > 1:
            dy = [b-a for a,b in zip(ys[:-1], ys[1:]) if b-a > 1e-6]
            if dy: diffs.append(float(pd.Series(dy).median()))
        mesh = min(diffs) if diffs else float("nan")
        if not pd.notna(mesh) or mesh <= 0:
            continue
        radius = float(local_radius_factor) * mesh
        local = []
        for nid, val, (x, y, z) in known:
            if abs(z-pz) <= max(0.15, 0.35*radius) and (x-px)**2 + (y-py)**2 <= radius**2 + 1e-12:
                local.append((nid, val))
        local_vals = [v for nid,v in local if nid != peak_node]
        peak_val = safe_float(nodal.get(peak_node, pr.get("Mmax_kNm_m", 0.0)), 0.0)
        if len(local_vals) < 2:
            continue
        med = safe_float(pd.Series(local_vals).median(), 0.0)
        p95 = safe_float(pd.Series(local_vals).quantile(0.95), 0.0)
        rmed = peak_val / med if med > 1e-9 else (999.0 if peak_val > 1e-9 else 1.0)
        rp95 = peak_val / p95 if p95 > 1e-9 else (999.0 if peak_val > 1e-9 else 1.0)
        global_ratio = safe_float(pr.get("Pico_ratio_max_P95", 0.0), 0.0)
        frac90 = safe_float(pr.get("Frac_nós_>=90%Mmax", 0.0), 0.0)
        if global_ratio <= 1.50 or rp95 <= 1.20:
            classification = "Distribuição espacial coerente — máximo suportado pela vizinhança"
            sens = "Baixa"
        elif rp95 >= 1.50 and frac90 <= 0.02:
            classification = "Concentração espacial forte — singularidade potencial a investigar"
            sens = "Elevada"
        else:
            classification = "Concentração espacial moderada — tratar como zona local até validação"
            sens = "Média"
        out.at[ix, "Pico_spatial_check"] = "Avaliado"
        out.at[ix, "N_vizinhos_locais"] = len(local_vals)
        out.at[ix, "Raio_vizinhança_m"] = radius
        out.at[ix, "Pico_ratio_max_mediana_local"] = rmed
        out.at[ix, "Pico_ratio_max_P95_local"] = rp95
        out.at[ix, "Classificação_espacial_pico"] = classification
        out.at[ix, "Sensibilidade_malha"] = sens
        out.at[ix, "Política_valor_dimensionamento"] = "RAW preservado; nenhum alisamento automático"
        out.at[ix, "Singularidade_automática"] = "Nunca — requer confirmação explícita do utilizador"
    return out
