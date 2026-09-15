# -*- coding: utf-8 -*-
from __future__ import annotations

"""Dimensionamento local assistido por contexto geométrico opcional.

Princípio de segurança:
- os resultados FEM brutos nunca são alterados;
- a rotina apenas separa uma zona local geometricamente identificada do restante painel;
- a zona local é dimensionada para os próprios máximos brutos que contém;
- a zona distribuída é dimensionada para os máximos das linhas fora da zona local;
- uma zona automática nunca conduz a ``OK`` definitivo: quando ambas as zonas verificam,
  o estado de projecto é ``Verificar`` até confirmação do engenheiro.

Sem conectividade dos elementos de placa, a largura da zona é uma heurística geométrica
baseada na malha local e no elemento estrutural de referência. Não é uma largura normativa.
"""

import math
from typing import Dict, Iterable, Optional, Tuple

import pandas as pd

from ..models import RebarSolution
from ..peaks import canonical_node_id
from ..utils import safe_float
from .context import _node_lookup, _point_segment_distance, _wall_plan_segments


LOCAL_ZONE_TYPES = {
    "Junto a pilar",
    "Sobre/junto a viga",
    "Extremidade de viga",
    "Junto a parede",
    "Extremidade de parede",
    "Bordo de abertura/negativo",
    "Canto de abertura/negativo",
}


def _same_level_nodes(nodes: pd.DataFrame, pz: float, tol: float = 0.15) -> pd.DataFrame:
    if nodes is None or nodes.empty:
        return pd.DataFrame(columns=["node", "x", "y", "z"])
    out = nodes.copy()
    for c in ("x", "y", "z"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    out = out.dropna(subset=[c for c in ("x", "y", "z") if c in out.columns])
    if math.isfinite(pz) and "z" in out.columns:
        out = out[(out["z"] - pz).abs() <= tol]
    return out


def _member_points(members: pd.DataFrame, lookup: Dict[str, dict], member_id: str):
    if members is None or members.empty:
        return None
    g = members[members.get("member", pd.Series(dtype=object)).astype(str) == str(member_id)]
    if g.empty:
        return None
    r = g.iloc[0]
    a = lookup.get(canonical_node_id(r.get("node1", "")))
    b = lookup.get(canonical_node_id(r.get("node2", "")))
    if not a or not b:
        return None
    return a, b


def _wall_segment(walls: pd.DataFrame, lookup: Dict[str, dict], wall_id: str, pz: float):
    for panel, a, b in _wall_plan_segments(walls, lookup, pz):
        if str(panel) == str(wall_id):
            return a, b
    return None


def _opening_points(openings: pd.DataFrame, contour: str, pz: float):
    if openings is None or openings.empty or "contour" not in openings.columns:
        return []
    g = openings[openings["contour"].astype(str) == str(contour)].copy()
    if g.empty:
        return []
    if "sequence" in g.columns:
        g = g.sort_values("sequence")
    pts = []
    for r in g.itertuples():
        x = safe_float(getattr(r, "x", float("nan")), float("nan"))
        y = safe_float(getattr(r, "y", float("nan")), float("nan"))
        z = safe_float(getattr(r, "z", float("nan")), float("nan"))
        if all(math.isfinite(v) for v in (x, y, z)) and (not math.isfinite(pz) or abs(z - pz) <= 0.50):
            pts.append((x, y, z))
    return pts


def _opening_distance(x: float, y: float, pts) -> float:
    if len(pts) < 2:
        return float("inf")
    ds = []
    for i in range(len(pts) - 1):
        ds.append(_point_segment_distance(x, y, pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]))
    if len(pts) >= 3 and (pts[0][0], pts[0][1]) != (pts[-1][0], pts[-1][1]):
        ds.append(_point_segment_distance(x, y, pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]))
    return min(ds) if ds else float("inf")


def _zone_radius(peak: pd.Series, factor: float) -> float:
    mesh = safe_float(peak.get("Malha_local_estimada_m", float("nan")), float("nan"))
    dref = safe_float(peak.get("Dist_referência_m", float("nan")), float("nan"))
    if not math.isfinite(mesh) or mesh <= 1e-6:
        mesh = 0.25
    # O raio é deliberadamente conservador e transparente. Nunca inferior a 0,35 m.
    r = max(float(factor) * mesh, 0.35)
    if math.isfinite(dref):
        r = max(r, dref + 1.25 * mesh)
    # Impede que uma heurística automática transforme grande parte do painel numa "zona local".
    return min(r, 1.50)


def identify_local_zone_nodes(
    peak: pd.Series,
    nodes: pd.DataFrame,
    members: pd.DataFrame,
    walls: pd.DataFrame,
    openings: pd.DataFrame,
    factor: float = 2.5,
) -> Tuple[set, float, str]:
    """Devolve IDs de nós pertencentes à zona local automática e o raio/banda usados."""
    if nodes is None or nodes.empty:
        return set(), float("nan"), "sem tabela geral de nós"
    zone = str(peak.get("Tipo_zona_local", ""))
    if zone not in LOCAL_ZONE_TYPES:
        return set(), float("nan"), f"tipo de zona '{zone}' não habilitado para dimensionamento automático"
    conf = str(peak.get("Confiança_contexto", ""))
    if conf not in {"Alta", "Média"}:
        return set(), float("nan"), "confiança geométrica insuficiente"

    px = safe_float(peak.get("Pico_X_m", float("nan")), float("nan"))
    py = safe_float(peak.get("Pico_Y_m", float("nan")), float("nan"))
    pz = safe_float(peak.get("Pico_Z_m", float("nan")), float("nan"))
    if not all(math.isfinite(v) for v in (px, py, pz)):
        return set(), float("nan"), "coordenadas do pico indisponíveis"

    ref = str(peak.get("Elemento_referência", "") or "")
    radius = _zone_radius(peak, factor)
    same = _same_level_nodes(nodes, pz)
    if same.empty:
        return set(), radius, "sem nós no mesmo nível"
    lookup = _node_lookup(nodes)

    mask = pd.Series(False, index=same.index)
    criterion = ""

    if zone == "Junto a pilar" and ref:
        pts = _member_points(members, lookup, ref)
        if pts:
            a, b = pts
            cx = 0.5 * (a["x"] + b["x"]); cy = 0.5 * (a["y"] + b["y"])
            dist = ((same["x"] - cx) ** 2 + (same["y"] - cy) ** 2) ** 0.5
            mask = dist <= radius
            criterion = f"raio {radius:.3f} m em torno do eixo do pilar {ref}"
    elif zone in {"Sobre/junto a viga", "Extremidade de viga"} and ref:
        pts = _member_points(members, lookup, ref)
        if pts:
            a, b = pts
            if zone == "Extremidade de viga":
                da = math.hypot(px - a["x"], py - a["y"]); db = math.hypot(px - b["x"], py - b["y"])
                q = a if da <= db else b
                dist = ((same["x"] - q["x"]) ** 2 + (same["y"] - q["y"]) ** 2) ** 0.5
                mask = dist <= radius
                criterion = f"raio {radius:.3f} m na extremidade da viga {ref}"
            else:
                dist = same.apply(lambda r: _point_segment_distance(r["x"], r["y"], a["x"], a["y"], b["x"], b["y"]), axis=1)
                mask = dist <= radius
                criterion = f"banda ±{radius:.3f} m em torno da viga {ref}"
    elif zone in {"Junto a parede", "Extremidade de parede"} and ref:
        seg = _wall_segment(walls, lookup, ref, pz)
        if seg:
            a, b = seg
            if zone == "Extremidade de parede":
                da = math.hypot(px - a[0], py - a[1]); db = math.hypot(px - b[0], py - b[1])
                q = a if da <= db else b
                dist = ((same["x"] - q[0]) ** 2 + (same["y"] - q[1]) ** 2) ** 0.5
                mask = dist <= radius
                criterion = f"raio {radius:.3f} m na extremidade da parede {ref}"
            else:
                dist = same.apply(lambda r: _point_segment_distance(r["x"], r["y"], a[0], a[1], b[0], b[1]), axis=1)
                mask = dist <= radius
                criterion = f"banda ±{radius:.3f} m em torno da parede {ref}"
    elif zone in {"Bordo de abertura/negativo", "Canto de abertura/negativo"} and ref:
        pts = _opening_points(openings, ref, pz)
        if pts:
            if zone == "Canto de abertura/negativo":
                q = min(pts, key=lambda p: math.hypot(px - p[0], py - p[1]))
                dist = ((same["x"] - q[0]) ** 2 + (same["y"] - q[1]) ** 2) ** 0.5
                mask = dist <= radius
                criterion = f"raio {radius:.3f} m no canto do contorno {ref}"
            else:
                dist = same.apply(lambda r: _opening_distance(r["x"], r["y"], pts), axis=1)
                mask = dist <= radius
                criterion = f"banda ±{radius:.3f} m no bordo do contorno {ref}"

    ids = {canonical_node_id(v) for v in same.loc[mask, "node"] if canonical_node_id(v)}
    peak_id = canonical_node_id(peak.get("Nó_pico", ""))
    if peak_id:
        ids.add(peak_id)
    return ids, radius, criterion or "critério geométrico indisponível"


def _critical_rows(subset: pd.DataFrame) -> pd.DataFrame:
    if subset is None or subset.empty:
        return pd.DataFrame()
    idx = set()
    mapping = [
        ("ELU", "MEd_x_sup_kNm_m"), ("ELU", "MEd_x_inf_kNm_m"),
        ("ELU", "MEd_y_sup_kNm_m"), ("ELU", "MEd_y_inf_kNm_m"),
        ("ELS-QP", "MEd_x_sup_kNm_m"), ("ELS-QP", "MEd_x_inf_kNm_m"),
        ("ELS-QP", "MEd_y_sup_kNm_m"), ("ELS-QP", "MEd_y_inf_kNm_m"),
        ("ELS-CHAR", "MEd_x_sup_kNm_m"), ("ELS-CHAR", "MEd_x_inf_kNm_m"),
        ("ELS-CHAR", "MEd_y_sup_kNm_m"), ("ELS-CHAR", "MEd_y_inf_kNm_m"),
    ]
    for cls, col in mapping:
        if col not in subset.columns or "Case_classification" not in subset.columns:
            continue
        g = subset[subset["Case_classification"].astype(str) == cls]
        if not g.empty:
            idx.add(g[col].fillna(-1.0).idxmax())
    if not idx:
        idx.add(subset.index[0])
    return subset.loc[sorted(idx)]


def _status_from_rows(rows: pd.DataFrame) -> str:
    if rows is None or rows.empty:
        return "Não avaliado"
    vals = set(rows.get("Status", pd.Series(dtype=str)).astype(str))
    if "Não conforme" in vals:
        return "Não conforme"
    if "Verificar" in vals or "Não avaliado" in vals:
        return "Verificar"
    if "OK*" in vals:
        return "OK*"
    return "OK"


def _eval_solution(designer, subset: pd.DataFrame, sols: Dict[str, RebarSolution]) -> Tuple[str, float, float, pd.DataFrame]:
    crit = _critical_rows(subset)
    if crit.empty:
        return "Não avaliado", float("nan"), float("nan"), pd.DataFrame()
    ev = pd.DataFrame([designer._apply_fixed_panel_solution(r.to_dict(), sols) for _, r in crit.iterrows()])
    status = _status_from_rows(ev)
    util = safe_float(ev.get("util_M", pd.Series([float("nan")])).max(), float("nan"))
    wk = safe_float(ev.get("ELS_wk_ratio", pd.Series([float("nan")])).max(), float("nan"))
    return status, util, wk, ev


def _composite_from_distributed(designer, dist: RebarSolution, deficit: float, max_spacing: float) -> Optional[RebarSolution]:
    if deficit <= 1e-9 or dist.phi <= 0 or dist.spacing <= 0:
        return dist
    add = designer.choose_compatible_additional_rebar(deficit, dist, max_spacing)
    if add.capacity_limited or add.as_prov + 1e-9 < deficit:
        return None
    txt = f"{dist.text} + {add.text}"
    return RebarSolution(
        phi=max(dist.phi, add.phi), spacing=dist.spacing,
        as_prov=dist.as_prov + add.as_prov,
        text_override=txt, base_text=dist.text, add_text=add.text,
        as_base=dist.as_prov, as_add=add.as_prov,
        optimization_note="reforço local adicional com a mesma modulação da armadura distribuída",
        constructability_status="OK",
        constructability_note="uma única família local adicional, com o mesmo espaçamento da malha distribuída",
        reinforcement_ratio_add_base=add.as_prov / max(dist.as_prov, 1e-9),
    )


def _local_final_solutions(designer, dist_sols, local_target_sols, local_subset):
    # Primeiro tenta reforço local adicional simples sobre a malha distribuída.
    x_is_main = not designer.local_y_is_vertical
    y_is_main = designer.local_y_is_vertical
    smax = {
        "X+": designer.max_spacing_for_direction(x_is_main), "X-": designer.max_spacing_for_direction(x_is_main),
        "Y+": designer.max_spacing_for_direction(y_is_main), "Y-": designer.max_spacing_for_direction(y_is_main),
    }
    base_plus = bool(getattr(designer, "optimize_rebar", False)) and "substituir" not in str(getattr(designer, "rebar_strategy", "")).lower()
    proposals = {}
    limited_labels = []
    composite_labels = []
    for lab in ("X+", "X-", "Y+", "Y-"):
        d = dist_sols[lab]
        t = local_target_sols[lab]
        deficit = max(0.0, t.as_prov - d.as_prov)
        c = _composite_from_distributed(designer, d, deficit, smax[lab])
        if c is None:
            # Em Base + reforços, o target já preserva a base configurada; nunca se troca por uma
            # malha local independente. Se for insuficiente, ficará explicitamente limitado.
            proposals[lab] = t
            limited_labels.append(lab)
        else:
            proposals[lab] = c
            if deficit > 1e-9:
                composite_labels.append(lab)
    st, util, wk, ev = _eval_solution(designer, local_subset, proposals)
    if st != "Não conforme":
        if limited_labels and composite_labels:
            mode = f"Base fixa + reforço em {', '.join(composite_labels)}; capacidade da família adicional atingida em {', '.join(limited_labels)}." if base_plus else f"Solução mista em {', '.join(composite_labels + limited_labels)}."
        elif limited_labels:
            mode = f"Base fixa preservada; capacidade do reforço adicional atingida em {', '.join(limited_labels)}." if base_plus else f"Solução local directa em {', '.join(limited_labels)}."
        elif composite_labels:
            mode = f"Reforço local adicional com a mesma modulação da base em {', '.join(composite_labels)}."
        else:
            mode = "A base distribuída já verifica a zona local; sem reforço adicional."
        return proposals, st, util, wk, mode
    if base_plus:
        return proposals, st, util, wk, "Base fixa preservada, mas a solução Base + reforço disponível não verifica esta zona; rever a base ou os limites de armadura."
    # Apenas na estratégia de substituição é admissível recorrer à solução local total.
    st2, util2, wk2, _ = _eval_solution(designer, local_subset, local_target_sols)
    return local_target_sols, st2, util2, wk2, "Malha local total independente; reforço simples sobre a base distribuída não foi suficiente."


def build_geometry_local_design(
    results: pd.DataFrame,
    peaks: pd.DataFrame,
    nodes: pd.DataFrame,
    members: pd.DataFrame,
    walls: pd.DataFrame,
    openings: pd.DataFrame,
    designer,
    enabled: bool = False,
    zone_factor: float = 2.5,
) -> pd.DataFrame:
    """Cria proposta de armadura distribuída + local preservando o envelope FEM bruto."""
    if not enabled or results is None or results.empty or peaks is None or peaks.empty or nodes is None or nodes.empty:
        return pd.DataFrame()
    rows = []
    saved_singular = set(getattr(designer, "singular_node_ids", set()))
    # O módulo local deve dimensionar inclusive os nós previamente marcados como singulares;
    # eles podem sair do envelope distribuído, mas nunca desaparecem da verificação local.
    designer.singular_node_ids = set()
    try:
        for _, pk in peaks.iterrows():
            if str(pk.get("Pico_FEM", "Não")) != "Sim" or str(pk.get("Geo_disponível", "Não")) != "Sim":
                continue
            panel = str(pk.get("Panel", ""))
            g = results[results["Panel"].astype(str) == panel].copy()
            if g.empty or "Node" not in g.columns:
                continue
            local_ids, radius, criterion = identify_local_zone_nodes(pk, nodes, members, walls, openings, factor=zone_factor)
            panel_nodes = {canonical_node_id(v) for v in g["Node"] if canonical_node_id(v)}
            local_ids &= panel_nodes
            n_panel_nodes = len(panel_nodes)
            n_local_nodes = len(local_ids)
            frac = n_local_nodes / max(n_panel_nodes, 1)
            apply_reason = ""
            applicable = True
            if n_local_nodes < 2:
                applicable = False; apply_reason = "zona automática contém menos de 2 nós do painel"
            elif frac > 0.35:
                applicable = False; apply_reason = f"zona automática abrange {frac:.1%} dos nós do painel; deixa de ser local"
            local_mask = g["Node"].map(lambda v: canonical_node_id(v) in local_ids)
            glocal = g[local_mask].copy()
            gdist = g[~local_mask].copy()
            if gdist.empty:
                applicable = False; apply_reason = "não restam nós para o envelope distribuído"

            if not applicable:
                rows.append({
                    "Panel": panel, "Aplicado": "Não", "Tipo_zona_local": pk.get("Tipo_zona_local", ""),
                    "Elemento_referência": pk.get("Elemento_referência", ""), "Confiança": pk.get("Confiança_contexto", ""),
                    "Raio_ou_banda_m": radius, "Critério_zona": criterion, "N_nós_painel": n_panel_nodes,
                    "N_nós_locais": n_local_nodes, "Frac_nós_locais": frac,
                    "Status_projeto_geom": "Não avaliado", "Motivo_projeto_geom": apply_reason,
                    "Nota_segurança": "Envelope FEM bruto preservado; sem alteração da proposta de projecto.",
                })
                continue

            dist_sols = designer._panel_solution_from_envelope(gdist)
            local_target = designer._panel_solution_from_envelope(glocal)
            dist_status, dist_util, dist_wk, _ = _eval_solution(designer, gdist, dist_sols)
            local_sols, local_status, local_util, local_wk, local_mode = _local_final_solutions(designer, dist_sols, local_target, glocal)

            if "Não conforme" in {dist_status, local_status}:
                project_status = "Não conforme"
                motive = "A armadura distribuída e/ou a zona local não verificam com os limites configurados."
            elif "Verificar" in {dist_status, local_status, "Verificar"}:
                # Zona automática nunca é aprovada sem confirmação do projectista.
                project_status = "Verificar"
                motive = (
                    "Envelope distribuído e zona local foram dimensionados separadamente, mas a extensão da zona foi inferida automaticamente. "
                    "Confirmar a faixa/localização antes de adoptar a solução em projecto."
                )
            else:
                project_status = "Verificar"
                motive = "Soluções verificam numericamente; confirmar a zona local automática antes de adopção em projecto."

            row = {
                "Panel": panel, "Aplicado": "Sim", "Tipo_zona_local": pk.get("Tipo_zona_local", ""),
                "Natureza": pk.get("Natureza_pico_geométrica", ""), "Elemento_referência": pk.get("Elemento_referência", ""),
                "Confiança": pk.get("Confiança_contexto", ""), "Nó_pico": pk.get("Nó_pico", ""), "Caso_pico": pk.get("Caso_pico", ""),
                "Mmax_bruto_kNm_m": pk.get("Mmax_kNm_m", float("nan")), "Pico_ratio_max_P95": pk.get("Pico_ratio_max_P95", float("nan")),
                "Raio_ou_banda_m": radius, "Critério_zona": criterion, "N_nós_painel": n_panel_nodes,
                "N_nós_locais": n_local_nodes, "Frac_nós_locais": frac,
                "Status_distribuído": dist_status, "Util_ELU_distribuído": dist_util, "wk_wmax_distribuído": dist_wk,
                "Status_local": local_status, "Util_ELU_local": local_util, "wk_wmax_local": local_wk,
                "Status_projeto_geom": project_status, "Motivo_projeto_geom": motive,
                "Modo_reforço_local": local_mode,
                "Nota_segurança": (
                    "Os esforços FEM brutos não foram modificados. A armadura local verifica os máximos brutos da zona; "
                    "a armadura distribuída é obtida apenas fora dessa zona. A largura automática é heurística e requer confirmação do engenheiro."
                ),
            }
            for lab in ("X+", "X-", "Y+", "Y-"):
                row[f"{lab}_distribuído"] = dist_sols[lab].text
                row[f"As_{lab}_distribuído_mm2_m"] = dist_sols[lab].as_prov
                row[f"{lab}_local"] = local_sols[lab].text
                row[f"As_{lab}_local_mm2_m"] = local_sols[lab].as_prov
                add = max(0.0, local_sols[lab].as_prov - dist_sols[lab].as_prov)
                row[f"As_{lab}_incremento_local_mm2_m"] = add
            rows.append(row)
    finally:
        designer.singular_node_ids = saved_singular
    return pd.DataFrame(rows)


def merge_local_design_into_summary(summary: pd.DataFrame, local: pd.DataFrame) -> pd.DataFrame:
    """Integra o estado de projecto geométrico sem apagar o estado bruto original."""
    if summary is None or summary.empty or local is None or local.empty or "Panel" not in summary.columns:
        return summary
    applied = local[local.get("Aplicado", "Não").astype(str) == "Sim"].copy()
    if applied.empty:
        return summary
    # Se houver mais do que uma zona por painel, governa o estado mais severo e concatena referências.
    rank = {"Não conforme": 4, "Verificar": 3, "OK*": 2, "OK": 1, "Não avaliado": 0}
    rows = []
    for p, g in applied.groupby("Panel", dropna=False):
        gg = g.copy(); gg["__rank"] = gg["Status_projeto_geom"].astype(str).map(rank).fillna(0)
        gov = gg.loc[gg["__rank"].idxmax()]
        rows.append({
            "Panel": p,
            "Status_projeto_geom": gov.get("Status_projeto_geom", "Verificar"),
            "Motivo_projeto_geom": gov.get("Motivo_projeto_geom", ""),
            "N_zonas_locais": len(g),
            "Zonas_locais": " | ".join(dict.fromkeys(g["Tipo_zona_local"].astype(str))),
            "Armadura_distribuída_X+": gov.get("X+_distribuído", ""),
            "Armadura_distribuída_X-": gov.get("X-_distribuído", ""),
            "Armadura_distribuída_Y+": gov.get("Y+_distribuído", ""),
            "Armadura_distribuída_Y-": gov.get("Y-_distribuído", ""),
            "Armadura_local_X+": gov.get("X+_local", ""),
            "Armadura_local_X-": gov.get("X-_local", ""),
            "Armadura_local_Y+": gov.get("Y+_local", ""),
            "Armadura_local_Y-": gov.get("Y-_local", ""),
        })
    geo = pd.DataFrame(rows)
    out = summary.copy()
    if "Status_global_RAW" not in out.columns:
        out["Status_global_RAW"] = out.get("Status_global", "")
        out["Motivo_estado_RAW"] = out.get("Motivo_estado", "")
        out["Acção_recomendada_RAW"] = out.get("Acção_recomendada", "")
    else:
        # Reprocessamento após nova importação geométrica: regressa primeiro ao estado bruto.
        out["Status_global"] = out["Status_global_RAW"]
        if "Motivo_estado_RAW" in out.columns:
            out["Motivo_estado"] = out["Motivo_estado_RAW"]
        if "Acção_recomendada_RAW" in out.columns:
            out["Acção_recomendada"] = out["Acção_recomendada_RAW"]
    local_cols = [c for c in geo.columns if c != "Panel"]
    out = out.drop(columns=[c for c in local_cols if c in out.columns], errors="ignore")
    out = out.merge(geo, on="Panel", how="left")
    mask = out["Status_projeto_geom"].notna()
    out.loc[mask, "Status_global"] = out.loc[mask, "Status_projeto_geom"]
    out.loc[mask, "Motivo_estado"] = out.loc[mask, "Motivo_projeto_geom"]
    out.loc[mask, "Acção_recomendada"] = (
        "Confirmar a extensão da zona local automática e adoptar a malha distribuída + reforço/malha local indicada. "
        "O envelope FEM bruto permanece disponível nas colunas *_RAW e na avaliação de picos."
    )
    return out


def build_local_design_diagnostic(local: pd.DataFrame) -> pd.DataFrame:
    if local is None or local.empty:
        return pd.DataFrame()
    rows = []
    for _, r in local.iterrows():
        if str(r.get("Aplicado", "Não")) != "Sim":
            continue
        st = str(r.get("Status_projeto_geom", "Verificar"))
        sev = "Alta" if st == "Não conforme" else "Média"
        rows.append({
            "Painel": r.get("Panel", ""), "Severidade": sev,
            "Problema": (
                f"Dimensionamento local geométrico: {r.get('Tipo_zona_local','')}; "
                f"distribuído={r.get('Status_distribuído','')}; local={r.get('Status_local','')}."
            ),
            "Acção recomendada": str(r.get("Motivo_projeto_geom", "")),
            "Origem": "Dimensionamento local geométrico",
        })
    return pd.DataFrame(rows)
