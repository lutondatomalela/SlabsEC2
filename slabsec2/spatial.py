# -*- coding: utf-8 -*-
"""Optimização espacial de armaduras para a v2.14.

A rotina mantém como referência fail-safe a solução uniforme já verificada pelo núcleo.
Quando existem coordenadas dos nós, procura uma solução distribuída mais económica e
zonas locais de reforço, verificando ELU/ELS nos subconjuntos críticos de cada zona.
Nenhum pico é eliminado nem suavizado.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np
import pandas as pd

from .models import RebarSolution
from .peaks import canonical_node_id
from .utils import safe_float, normalize_text
from .geometry.local_design import _eval_solution, _local_final_solutions, _critical_rows

_LABELS = ("X+", "X-", "Y+", "Y-")
_REQ = {
    "X+": "Asx+_req_mm2_m", "X-": "Asx-_req_mm2_m",
    "Y+": "Asy+_req_mm2_m", "Y-": "Asy-_req_mm2_m",
}
_PROV = {
    "X+": "Asx+_prov_mm2_m", "X-": "Asx-_prov_mm2_m",
    "Y+": "Asy+_prov_mm2_m", "Y-": "Asy-_prov_mm2_m",
}


def _node_lookup(nodes: pd.DataFrame) -> Dict[str, Tuple[float, float, float]]:
    if nodes is None or nodes.empty or not {"node", "x", "y", "z"}.issubset(nodes.columns):
        return {}
    out = {}
    for _, r in nodes.iterrows():
        nid = canonical_node_id(r.get("node", ""))
        if not nid:
            continue
        x, y, z = (safe_float(r.get(k), float("nan")) for k in ("x", "y", "z"))
        if all(math.isfinite(v) for v in (x, y, z)):
            out[nid] = (x, y, z)
    return out


def _mesh_estimate(points: Sequence[Tuple[float, float]]) -> float:
    """Estimativa robusta do passo da malha sem custo O(n²)."""
    if len(points) < 2:
        return float("nan")
    xs = np.array(sorted({round(float(p[0]), 6) for p in points}), dtype=float)
    ys = np.array(sorted({round(float(p[1]), 6) for p in points}), dtype=float)
    diffs = []
    if len(xs) > 1:
        dx = np.diff(xs); dx = dx[dx > 1e-6]
        if len(dx): diffs.append(float(np.median(dx)))
    if len(ys) > 1:
        dy = np.diff(ys); dy = dy[dy > 1e-6]
        if len(dy): diffs.append(float(np.median(dy)))
    if diffs:
        return max(1e-4, min(diffs))
    # fallback pela área envolvente / número de pontos
    x = np.array([p[0] for p in points], dtype=float)
    y = np.array([p[1] for p in points], dtype=float)
    area = max((x.max() - x.min()) * (y.max() - y.min()), 0.0)
    return math.sqrt(area / max(len(points), 1)) if area > 1e-12 else float("nan")


def _spatial_components(node_ids: Iterable[str], lookup: Dict[str, Tuple[float, float, float]], radius: float) -> Tuple[List[Set[str]], Set[str]]:
    ids = [canonical_node_id(v) for v in node_ids if canonical_node_id(v)]
    known = [v for v in ids if v in lookup]
    missing = {v for v in ids if v not in lookup}
    if not known:
        return [], missing
    if not math.isfinite(radius) or radius <= 0:
        return [{v} for v in known], missing

    cell = radius
    buckets: Dict[Tuple[int, int, int], List[str]] = defaultdict(list)
    for nid in known:
        x, y, z = lookup[nid]
        key = (int(math.floor(x / cell)), int(math.floor(y / cell)), int(round(z / max(cell, 1e-6))))
        buckets[key].append(nid)

    adj: Dict[str, Set[str]] = {nid: set() for nid in known}
    r2 = radius * radius
    for nid in known:
        x, y, z = lookup[nid]
        key = (int(math.floor(x / cell)), int(math.floor(y / cell)), int(round(z / max(cell, 1e-6))))
        for ix in range(key[0] - 1, key[0] + 2):
            for iy in range(key[1] - 1, key[1] + 2):
                for iz in range(key[2] - 1, key[2] + 2):
                    for other in buckets.get((ix, iy, iz), []):
                        if other == nid:
                            continue
                        ox, oy, oz = lookup[other]
                        # lajes: pequena tolerância em Z, distância principal em planta
                        if abs(oz - z) <= max(0.15, radius * 0.35) and (ox - x) ** 2 + (oy - y) ** 2 <= r2 + 1e-12:
                            adj[nid].add(other)

    remaining = set(known)
    comps: List[Set[str]] = []
    while remaining:
        seed = remaining.pop()
        comp = {seed}
        q = deque([seed])
        while q:
            cur = q.popleft()
            for nb in adj[cur]:
                if nb in remaining:
                    remaining.remove(nb); comp.add(nb); q.append(nb)
        comps.append(comp)
    comps.sort(key=lambda s: (-len(s), sorted(s)[0] if s else ""))
    return comps, missing




def _configured_base_solutions(designer) -> Dict[str, RebarSolution]:
    """Base global definida pelo utilizador, repetida nas duas faces de cada direcção."""
    x_is_main = not designer.local_y_is_vertical
    y_is_main = designer.local_y_is_vertical
    bx = designer.base_solution_for_direction(x_is_main)
    by = designer.base_solution_for_direction(y_is_main)
    def clone(b):
        return RebarSolution(
            b.phi, b.spacing, b.as_prov, text_override=b.text, base_text=b.text, add_text="-",
            as_base=b.as_prov, as_add=0.0, optimization_note="base global fixa definida pelo utilizador"
        )
    return {"X+": clone(bx), "X-": clone(bx), "Y+": clone(by), "Y-": clone(by)}


def _expand_component(comp: Set[str], panel_ids: Set[str], lookup: Dict[str, Tuple[float, float, float]],
                      radius: float, min_nodes: int = 4) -> Set[str]:
    """Dilata um cluster FEM para uma zona física executável, com índice espacial linear."""
    known_comp = [n for n in comp if n in lookup]
    known_panel = [n for n in panel_ids if n in lookup]
    if not known_comp or not known_panel:
        return set(comp)
    rr = radius if math.isfinite(radius) and radius > 0 else 0.50
    cell = rr
    ztol = max(0.15, 0.35 * rr)
    buckets: Dict[Tuple[int, int], List[str]] = defaultdict(list)
    for n in known_panel:
        x, y, _ = lookup[n]
        buckets[(int(math.floor(x / cell)), int(math.floor(y / cell)))].append(n)
    out = set(comp)
    r2 = rr * rr
    for c in known_comp:
        cx, cy, cz = lookup[c]
        key = (int(math.floor(cx / cell)), int(math.floor(cy / cell)))
        for ix in range(key[0]-1, key[0]+2):
            for iy in range(key[1]-1, key[1]+2):
                for n in buckets.get((ix, iy), []):
                    x, y, z = lookup[n]
                    if abs(z-cz) <= ztol and (x-cx)**2 + (y-cy)**2 <= r2 + 1e-12:
                        out.add(n)
    if len(out) < min_nodes:
        cx = float(np.mean([lookup[n][0] for n in known_comp])); cy = float(np.mean([lookup[n][1] for n in known_comp]))
        zref = float(np.median([lookup[n][2] for n in known_comp]))
        near = sorted(
            (math.hypot(lookup[n][0]-cx, lookup[n][1]-cy), n)
            for n in known_panel if abs(lookup[n][2]-zref) <= ztol
        )
        for _, n in near:
            out.add(n)
            if len(out) >= min(min_nodes, len(known_panel)):
                break
    return out

def _merge_overlapping_components(comps: List[Set[str]]) -> List[Set[str]]:
    comps = [set(c) for c in comps if c]
    changed = True
    while changed:
        changed = False
        out = []
        while comps:
            cur = comps.pop()
            i = 0
            while i < len(comps):
                if cur & comps[i]:
                    cur |= comps.pop(i)
                    changed = True
                else:
                    i += 1
            out.append(cur)
        comps = out
    comps.sort(key=lambda c: (-len(c), sorted(c)[0] if c else ""))
    return comps

def _solution_text(sol: RebarSolution) -> str:
    return str(getattr(sol, "text", "") or "-")


def _zone_bbox(ids: Set[str], lookup: Dict[str, Tuple[float, float, float]]) -> Dict[str, float]:
    pts = [lookup[n] for n in ids if n in lookup]
    if not pts:
        return {k: float("nan") for k in ("Xmin_m", "Xmax_m", "Ymin_m", "Ymax_m", "Zmed_m")}
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]; zs = [p[2] for p in pts]
    return {"Xmin_m": min(xs), "Xmax_m": max(xs), "Ymin_m": min(ys), "Ymax_m": max(ys), "Zmed_m": float(np.median(zs))}


def _node_demand_index(g: pd.DataFrame) -> pd.DataFrame:
    """Índice escalar para separar a zona base das regiões de maior solicitação.

    O índice usa a razão As,req/As,prov e acrescenta indicadores ELS já calculados com a
    solução uniforme. É apenas usado para particionar espacialmente; a solução de cada zona
    é depois recalculada pelo núcleo com os próprios envelopes ELU/ELS.
    """
    work = g.copy()
    if "Node" not in work.columns:
        return pd.DataFrame(columns=["Node", "Demand_index"])
    ratios = []
    for lab in _LABELS:
        req = pd.to_numeric(work.get(_REQ[lab], 0.0), errors="coerce").fillna(0.0)
        prov = pd.to_numeric(work.get(_PROV[lab], 0.0), errors="coerce").fillna(0.0)
        ratios.append((req / prov.clip(lower=1e-9)).to_numpy())
    arr = np.maximum.reduce(ratios) if ratios else np.zeros(len(work))
    if "ELS_wk_ratio" in work.columns:
        wk = pd.to_numeric(work["ELS_wk_ratio"], errors="coerce").fillna(0.0).to_numpy()
        arr = np.maximum(arr, wk)
    if "ELS_sigma_s_max_MPa" in work.columns and "ELS_sigma_s_limit_MPa" in work.columns:
        ss = pd.to_numeric(work["ELS_sigma_s_max_MPa"], errors="coerce").fillna(0.0)
        sl = pd.to_numeric(work["ELS_sigma_s_limit_MPa"], errors="coerce").replace(0, np.nan)
        arr = np.maximum(arr, (ss / sl).fillna(0.0).to_numpy())
    work["_demand"] = arr
    work["_node"] = work["Node"].map(canonical_node_id)
    work = work[work["_node"] != ""]
    if work.empty:
        return pd.DataFrame(columns=["Node", "Demand_index"])
    nd = work.groupby("_node", sort=False)["_demand"].max().reset_index()
    nd.columns = ["Node", "Demand_index"]
    return nd


def _sum_as(sols: Dict[str, RebarSolution]) -> float:
    return sum(max(0.0, safe_float(getattr(sols[k], "as_prov", 0.0), 0.0)) for k in _LABELS)


def _zone_row(panel: object, zone: str, zone_type: str, ids: Set[str], n_total: int, sols: Dict[str, RebarSolution],
              base_sols: Dict[str, RebarSolution], status: str, util: float, wk: float, lookup, q: float,
              mesh: float, score: float, mode: str) -> dict:
    bbox = _zone_bbox(ids, lookup)
    rec = {
        "Panel": panel, "Zona": zone, "Tipo_zona": zone_type,
        "N_nós": len(ids), "Frac_nós": len(ids) / max(n_total, 1),
        "Nós_amostra": ", ".join(sorted(ids)[:40]) + (" …" if len(ids) > 40 else ""),
        "Status_verificação": status, "util_M_max": util, "wk_wmax_ratio_max": wk,
        "Quantil_base": q, "Malha_estimada_m": mesh, "Score_espacial": score,
        "Modo_solução": mode,
    }
    rec.update(bbox)
    for lab in _LABELS:
        sol = sols[lab]; b = base_sols[lab]
        rec[f"{lab}_base"] = _solution_text(b)
        rec[f"{lab}_reforço"] = str(getattr(sol, "add_text", "") or "-") if zone_type != "Base distribuída" else "-"
        rec[f"{lab}_final"] = _solution_text(sol)
        rec[f"As_{lab}_base_mm2_m"] = safe_float(getattr(b, "as_prov", 0.0), 0.0)
        rec[f"As_{lab}_final_mm2_m"] = safe_float(getattr(sol, "as_prov", 0.0), 0.0)
    rec["Nota"] = (
        "Zona verificada com os envelopes ELU/ELS dos próprios nós; o envelope FEM bruto é preservado. "
        "A solução uniforme por painel continua disponível como referência fail-safe."
    )
    return rec


def build_spatial_rebar_zones(results: pd.DataFrame, nodes: pd.DataFrame, designer,
                              quantiles: Sequence[float] = (0.70, 0.80, 0.90, 1.00),
                              max_local_zones: int = 8) -> pd.DataFrame:
    """Gera base distribuída + reforços locais com agrupamento espacial automático.

    v2.14.1: quando a estratégia é ``Base + reforços``, a base configurada pelo utilizador
    é invariável em todos os painéis, faces e zonas. O zonamento apenas decide onde é necessário
    acrescentar reforço. Clusters pontuais são dilatados para pelo menos uma coroa de malha e,
    quando a geometria o permite, para um mínimo de quatro nós, evitando zonas finais de um nó.
    """
    if results is None or results.empty or "Panel" not in results.columns:
        return pd.DataFrame()
    lookup = _node_lookup(nodes)
    rows: List[dict] = []
    base_plus = bool(getattr(designer, "optimize_rebar", False)) and "substituir" not in normalize_text(getattr(designer, "rebar_strategy", ""))

    for panel, gall in results.groupby("Panel", dropna=False, sort=False):
        g = gall.copy()
        if "Excluded_from_distributed_envelope" in g.columns:
            g = g[g["Excluded_from_distributed_envelope"].astype(str) != "Sim"].copy()
        if "Case_classification" in g.columns:
            g = g[g["Case_classification"].astype(str).isin(["ELU", "ELS-QP", "ELS-CHAR", "ELS-FREQ"])].copy()
        if g.empty or "Node" not in g.columns:
            continue
        g["_SpatialNode"] = g["Node"].map(canonical_node_id)
        node_ids = {v for v in g["_SpatialNode"] if v}
        if not node_ids:
            continue
        n_total = len(node_ids)
        geocoded = {n for n in node_ids if n in lookup}
        coverage = len(geocoded) / max(n_total, 1)

        fixed_base = _configured_base_solutions(designer) if base_plus else None

        if coverage < 0.80:
            try:
                sols = designer._panel_solution_from_envelope(g)
                st, util, wk, _ = _eval_solution(designer, g, sols)
            except Exception:
                sols = {lab: RebarSolution(phi=0.0, spacing=0.0, as_prov=0.0, text_override="-") for lab in _LABELS}
                st, util, wk = "Não avaliado", float("nan"), float("nan")
            bases = fixed_base if fixed_base is not None else sols
            rec = _zone_row(panel, "Z0", "Base + reforço — sem geometria suficiente" if base_plus else "Uniforme — sem geometria suficiente",
                            node_ids, n_total, sols, bases, st, util, wk, lookup, 1.0, float("nan"), _sum_as(sols),
                            f"Optimização espacial não aplicada: cobertura de coordenadas={coverage:.0%} (<80%).")
            rec["Nota"] = ("A base configurada foi preservada; sem coordenadas suficientes o reforço é apresentado para todo o painel. "
                           "Importar a tabela geral de nós para obter zonas físicas automáticas.") if base_plus else "Importar a tabela geral de nós para activar o zonamento espacial automático."
            rows.append(rec)
            continue

        nd = _node_demand_index(g)
        if nd.empty:
            continue
        demand = dict(zip(nd["Node"].astype(str), pd.to_numeric(nd["Demand_index"], errors="coerce").fillna(0.0)))
        pts = [(lookup[n][0], lookup[n][1]) for n in geocoded]
        mesh = _mesh_estimate(pts)
        radius = (1.75 * mesh) if math.isfinite(mesh) and mesh > 0 else float("nan")

        # ---------------- Base + reforços: base fixa ----------------
        if base_plus:
            qs = sorted(set([0.50, 0.60] + [min(0.95, max(0.50, float(q))) for q in quantiles if float(q) < 1.0]))
            vals = np.array([demand.get(n, 0.0) for n in node_ids], dtype=float)
            best = None
            for q in qs:
                threshold = float(np.quantile(vals, q)) if len(vals) else 0.0
                high_ids = {n for n in node_ids if demand.get(n, 0.0) > threshold + 1e-12}
                if not high_ids:
                    high_ids = {max(node_ids, key=lambda n: demand.get(n, 0.0))}
                comps, missing_high = _spatial_components(high_ids, lookup, radius)
                if missing_high:
                    comps.append(set(missing_high))
                expand_r = min(1.50, max(0.35, 2.25 * mesh)) if math.isfinite(mesh) and mesh > 0 else 0.50
                comps = [_expand_component(c, node_ids, lookup, expand_r, min_nodes=4) for c in comps if c]
                comps = _merge_overlapping_components(comps)
                if len(comps) > max_local_zones:
                    continue
                reinforced_ids = set().union(*comps) if comps else set()
                base_only_ids = node_ids - reinforced_ids
                try:
                    if base_only_ids:
                        base_subset = _critical_rows(g[g["_SpatialNode"].isin(base_only_ids)].copy())
                        bst, butil, bwk, _ = _eval_solution(designer, base_subset, fixed_base)
                        if bst == "Não conforme":
                            continue
                    else:
                        bst, butil, bwk = "Base coberta por reforço", 0.0, 0.0

                    zones = []
                    ok = True
                    weighted = _sum_as(fixed_base) * n_total
                    for comp in comps:
                        sub = _critical_rows(g[g["_SpatialNode"].isin(comp)].copy())
                        target = designer._panel_solution_from_envelope(sub)
                        final_sols, st, util, wk, mode = _local_final_solutions(designer, fixed_base, target, sub)
                        if st == "Não conforme":
                            ok = False
                            break
                        # Só mantém zonas que acrescentam efectivamente aço à base.
                        has_add = any(safe_float(final_sols[lab].as_prov, 0.0) > safe_float(fixed_base[lab].as_prov, 0.0) + 1e-9 for lab in _LABELS)
                        if not has_add:
                            continue
                        zones.append((comp, final_sols, st, util, wk, mode))
                        weighted += sum(max(0.0, safe_float(final_sols[lab].as_prov, 0.0) - safe_float(fixed_base[lab].as_prov, 0.0)) for lab in _LABELS) * len(comp)
                    if not ok:
                        continue
                    penalty = 0.025 * max(_sum_as(fixed_base), 1.0) * len(zones)
                    score = weighted / max(n_total, 1) + penalty
                    cand = (score, q, base_only_ids, bst, butil, bwk, zones)
                    if best is None or cand[0] < best[0] - 1e-9:
                        best = cand
                except Exception:
                    continue

            if best is None:
                # Fail-safe: a base continua fixa e o reforço passa a abranger o painel inteiro.
                target = designer._panel_solution_from_envelope(g)
                st, util, wk, _ = _eval_solution(designer, g, target)
                zones = []
                if any(safe_float(target[lab].as_prov, 0.0) > safe_float(fixed_base[lab].as_prov, 0.0) + 1e-9 for lab in _LABELS):
                    zones = [(set(node_ids), target, st, util, wk, "Reforço necessário em todo o painel mantendo a base global fixa.")]
                best = (_sum_as(target), 1.0, set(), "Base coberta por reforço", 0.0, 0.0, zones)

            score, q, base_only_ids, bst, butil, bwk, zones = best
            base_rec = _zone_row(panel, "ZB", "Base distribuída", set(node_ids), n_total, fixed_base, fixed_base,
                                 bst, butil, bwk, lookup, q, mesh, score,
                                 "Base global fixa definida pelo utilizador; nunca é optimizada nem substituída por painel.")
            base_rec["N_nós_sem_reforço"] = len(base_only_ids)
            base_rec["Frac_nós_sem_reforço"] = len(base_only_ids) / max(n_total, 1)
            base_rec["Nota"] = ("Base global fixa aplicada a 100% do painel. As zonas ZR apenas acrescentam armadura; "
                                "a coluna Base mantém exactamente a solução definida pelo utilizador.")
            rows.append(base_rec)
            for i, (ids, sols, st, util, wk, mode) in enumerate(zones, start=1):
                rec = _zone_row(panel, f"ZR{i}", "Reforço local automático", set(ids), n_total, sols, fixed_base,
                                st, util, wk, lookup, q, mesh, score, mode)
                rec["N_nós_sem_reforço"] = len(base_only_ids)
                rec["Frac_nós_sem_reforço"] = len(base_only_ids) / max(n_total, 1)
                rec["Nota"] = ("Zona física de reforço sobre a base global fixa. O cluster FEM foi dilatado para uma região executável; "
                               "o envelope FEM raw permanece inalterado.")
                rows.append(rec)
            continue

        # ---------------- Estratégia de substituição/base não fixa: comportamento v2.14.0 ----------------
        best = None
        for q in quantiles:
            q = min(1.0, max(0.5, float(q)))
            vals = np.array([demand.get(n, 0.0) for n in node_ids], dtype=float)
            threshold = float(np.quantile(vals, q)) if len(vals) else 0.0
            base_ids = {n for n in node_ids if demand.get(n, 0.0) <= threshold + 1e-12}
            high_ids = node_ids - base_ids
            if not base_ids:
                continue
            comps, missing_high = _spatial_components(high_ids, lookup, radius)
            if missing_high:
                comps.append(set(missing_high))
            comps = [c for c in comps if c]
            if len(comps) > max_local_zones:
                continue
            try:
                base_subset = _critical_rows(g[g["_SpatialNode"].isin(base_ids)].copy())
                base_sols = designer._panel_solution_from_envelope(base_subset)
                bst, butil, bwk, _ = _eval_solution(designer, base_subset, base_sols)
                if bst == "Não conforme":
                    continue
                zones = []
                ok = True
                weighted = _sum_as(base_sols) * len(base_ids)
                for comp in comps:
                    sub = _critical_rows(g[g["_SpatialNode"].isin(comp)].copy())
                    target = designer._panel_solution_from_envelope(sub)
                    final_sols, st, util, wk, mode = _local_final_solutions(designer, base_sols, target, sub)
                    if st == "Não conforme":
                        ok = False; break
                    zones.append((comp, final_sols, st, util, wk, mode))
                    weighted += _sum_as(final_sols) * len(comp)
                if not ok:
                    continue
                avg_as = weighted / max(n_total, 1)
                penalty = 0.025 * max(_sum_as(base_sols), 1.0) * len(zones)
                score = avg_as + penalty
                cand = (score, q, base_ids, base_sols, bst, butil, bwk, zones)
                if best is None or cand[0] < best[0] - 1e-9:
                    best = cand
            except Exception:
                continue
        if best is None:
            sols = designer._panel_solution_from_envelope(g)
            st, util, wk, _ = _eval_solution(designer, g, sols)
            best = (_sum_as(sols), 1.0, set(node_ids), sols, st, util, wk, [])
        score, q, base_ids, base_sols, bst, butil, bwk, zones = best
        rows.append(_zone_row(panel, "ZB", "Base distribuída", set(base_ids), n_total, base_sols, base_sols,
                              bst, butil, bwk, lookup, q, mesh, score,
                              "Base optimizada automaticamente a partir do envelope espacial do painel."))
        for i, (ids, sols, st, util, wk, mode) in enumerate(zones, start=1):
            rows.append(_zone_row(panel, f"ZR{i}", "Reforço local automático", set(ids), n_total, sols, base_sols,
                                  st, util, wk, lookup, q, mesh, score, mode))

    out = pd.DataFrame(rows)
    if out.empty:
        return out
    order = {"Base distribuída": 0, "Reforço local automático": 1, "Base + reforço — sem geometria suficiente": 2, "Uniforme — sem geometria suficiente": 3}
    out["_ord"] = out["Tipo_zona"].map(order).fillna(9)
    out = out.sort_values(["Panel", "_ord", "Zona"], kind="stable").drop(columns="_ord").reset_index(drop=True)
    return out
