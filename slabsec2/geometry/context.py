# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import re
from typing import Dict, Optional, Tuple

import pandas as pd

from ..peaks import canonical_node_id
from ..utils import safe_float


def geometry_summary(nodes=None, members=None, walls=None, openings=None) -> pd.DataFrame:
    nodes = nodes if isinstance(nodes, pd.DataFrame) else pd.DataFrame()
    members = members if isinstance(members, pd.DataFrame) else pd.DataFrame()
    walls = walls if isinstance(walls, pd.DataFrame) else pd.DataFrame()
    openings = openings if isinstance(openings, pd.DataFrame) else pd.DataFrame()
    n_beams = 0
    n_cols = 0
    if not members.empty and "structure_object" in members.columns:
        types = members["structure_object"].astype(str).str.lower()
        n_beams = int(types.str.contains("beam|viga", regex=True).sum())
        n_cols = int(types.str.contains("column|pilar", regex=True).sum())
    return pd.DataFrame([
        ["Nós gerais", len(nodes), "Disponível" if not nodes.empty else "Não importado"],
        ["Vigas", n_beams, "Disponível" if n_beams else "Não identificadas"],
        ["Pilares", n_cols, "Disponível" if n_cols else "Não identificados"],
        ["Nós de paredes", len(walls), "Disponível" if not walls.empty else "Não importado"],
        ["Painéis de parede", walls["panel"].nunique() if not walls.empty and "panel" in walls.columns else 0, "Informativo"],
        ["Pontos de aberturas/negativos", len(openings), "Disponível" if not openings.empty else "Não importado"],
        ["Contornos", openings["contour"].nunique() if not openings.empty and "contour" in openings.columns else 0, "Informativo"],
        ["Uso no cálculo", "Diagnóstico; dimensionamento local se activado", "Esforços FEM brutos permanecem inalterados"],
    ], columns=["Fonte", "Quantidade", "Estado"])


def _point_segment_distance(px, py, ax, ay, bx, by) -> float:
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    vv = vx * vx + vy * vy
    if vv <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / vv))
    qx = ax + t * vx
    qy = ay + t * vy
    return math.hypot(px - qx, py - qy)


def _node_lookup(nodes: pd.DataFrame) -> Dict[str, dict]:
    if nodes is None or nodes.empty:
        return {}
    return {
        canonical_node_id(r["node"]): {
            "x": safe_float(r["x"], float("nan")),
            "y": safe_float(r["y"], float("nan")),
            "z": safe_float(r["z"], float("nan")),
            "support": str(r.get("support", "") or ""),
        }
        for _, r in nodes.iterrows()
        if canonical_node_id(r.get("node", ""))
    }


def _node_arrays(nodes: pd.DataFrame):
    if nodes is None or nodes.empty:
        return pd.DataFrame(columns=["node", "x", "y", "z", "support"])
    cols = [c for c in ["node", "x", "y", "z", "support"] if c in nodes.columns]
    out = nodes[cols].copy()
    for c in ("x", "y", "z"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out.dropna(subset=["x", "y", "z"] if {"x", "y", "z"}.issubset(out.columns) else None)


def _local_mesh_spacing(nodes: pd.DataFrame, px: float, py: float, pz: float) -> float:
    """Estimativa diagnóstica do passo local da malha a partir dos nós gerais.

    Usa os vizinhos em planta no mesmo nível. Não entra em nenhuma equação resistente.
    """
    if nodes is None or nodes.empty or not all(math.isfinite(v) for v in (px, py, pz)):
        return float("nan")
    arr = _node_arrays(nodes)
    if arr.empty:
        return float("nan")
    # Tolerância de piso deliberadamente pequena; se não houver nós, abre até 0,15 m.
    same = arr[(arr["z"] - pz).abs() <= 0.03]
    if len(same) < 4:
        same = arr[(arr["z"] - pz).abs() <= 0.15]
    if same.empty:
        return float("nan")
    dist = ((same["x"] - px) ** 2 + (same["y"] - py) ** 2) ** 0.5
    dist = dist[dist > 1e-6].sort_values().head(12)
    if dist.empty:
        return float("nan")
    # Mediana dos vizinhos mais próximos reduz a influência de nós estruturais isolados.
    use = dist.head(min(3, len(dist)))
    return safe_float(use.median(), float("nan"))


def _nearest_member_detail(px, py, pz, members: pd.DataFrame, lookup: Dict[str, dict], kind_pattern: str) -> dict:
    empty = {"id": "", "distance": float("nan"), "endpoint_distance": float("nan"), "type": ""}
    if members is None or members.empty or not lookup:
        return empty
    best = None
    for _, r in members.iterrows():
        typ = str(r.get("structure_object", ""))
        tl = typ.lower()
        if kind_pattern == "column" and not ("column" in tl or "pilar" in tl):
            continue
        if kind_pattern == "beam" and not ("beam" in tl or "viga" in tl):
            continue
        a = lookup.get(canonical_node_id(r.get("node1", "")))
        b = lookup.get(canonical_node_id(r.get("node2", "")))
        if not a or not b:
            continue
        if kind_pattern == "column":
            zmin = min(a["z"], b["z"])
            zmax = max(a["z"], b["z"])
            if math.isfinite(pz) and not (zmin - 0.25 <= pz <= zmax + 0.25):
                continue
            # Eixo vertical: em planta usa-se o ponto médio dos dois nós.
            cx = 0.5 * (a["x"] + b["x"])
            cy = 0.5 * (a["y"] + b["y"])
            d = math.hypot(px - cx, py - cy)
            dend = d
        else:
            zbar = 0.5 * (a["z"] + b["z"])
            if math.isfinite(pz) and abs(pz - zbar) > 0.50:
                continue
            d = _point_segment_distance(px, py, a["x"], a["y"], b["x"], b["y"])
            dend = min(math.hypot(px - a["x"], py - a["y"]), math.hypot(px - b["x"], py - b["y"]))
        item = {"id": str(r.get("member", "")), "distance": d, "endpoint_distance": dend, "type": typ}
        if best is None or d < best["distance"]:
            best = item
    return best or empty


def _nearest_member(px, py, pz, members: pd.DataFrame, lookup: Dict[str, dict], kind_pattern: str) -> Tuple[str, float, str]:
    d = _nearest_member_detail(px, py, pz, members, lookup, kind_pattern)
    return d["id"], d["distance"], d["type"]


def _wall_plan_segments(walls: pd.DataFrame, lookup: Dict[str, dict], pz: float):
    if walls is None or walls.empty or not lookup or "panel" not in walls.columns or "node" not in walls.columns:
        return []
    segments = []
    for panel, g in walls.groupby("panel", dropna=False):
        pts = []
        zs = []
        for node in g["node"]:
            p = lookup.get(canonical_node_id(node))
            if p and all(math.isfinite(p[k]) for k in ("x", "y", "z")):
                pts.append((p["x"], p["y"]))
                zs.append(p["z"])
        if not pts:
            continue
        if math.isfinite(pz) and zs:
            if pz < min(zs) - 0.25 or pz > max(zs) + 0.25:
                continue
        # Colapsa coordenadas XY repetidas de topo/base da parede.
        uniq = list(dict.fromkeys((round(x, 9), round(y, 9)) for x, y in pts))
        if len(uniq) == 1:
            a = b = uniq[0]
        else:
            # Os dois pontos mais afastados representam de forma robusta o eixo em planta
            # para painéis de parede rectos, que é o formato disponível nesta importação.
            max_pair = (uniq[0], uniq[1])
            max_d2 = -1.0
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    dx = uniq[i][0] - uniq[j][0]
                    dy = uniq[i][1] - uniq[j][1]
                    d2 = dx * dx + dy * dy
                    if d2 > max_d2:
                        max_d2 = d2
                        max_pair = (uniq[i], uniq[j])
            a, b = max_pair
        segments.append((str(panel), a, b))
    return segments


def _nearest_wall_detail(px, py, pz, walls: pd.DataFrame, lookup: Dict[str, dict]) -> dict:
    empty = {"id": "", "distance": float("nan"), "endpoint_distance": float("nan")}
    best = None
    for panel, a, b in _wall_plan_segments(walls, lookup, pz):
        d = _point_segment_distance(px, py, a[0], a[1], b[0], b[1])
        dend = min(math.hypot(px - a[0], py - a[1]), math.hypot(px - b[0], py - b[1]))
        item = {"id": panel, "distance": d, "endpoint_distance": dend}
        if best is None or d < best["distance"]:
            best = item
    return best or empty


def _nearest_wall(px, py, pz, walls: pd.DataFrame, lookup: Dict[str, dict]) -> Tuple[str, float]:
    d = _nearest_wall_detail(px, py, pz, walls, lookup)
    return d["id"], d["distance"]


def _nearest_opening_detail(px, py, pz, openings: pd.DataFrame) -> dict:
    empty = {"id": "", "distance": float("nan"), "vertex_distance": float("nan")}
    if openings is None or openings.empty:
        return empty
    best = None
    for name, g in openings.groupby("contour", dropna=False):
        gg = g.sort_values("sequence")
        pts = [(safe_float(r.x, float("nan")), safe_float(r.y, float("nan")), safe_float(r.z, float("nan"))) for r in gg.itertuples()]
        pts = [p for p in pts if all(math.isfinite(v) for v in p)]
        if len(pts) < 2:
            continue
        if math.isfinite(pz) and min(abs(p[2] - pz) for p in pts) > 0.50:
            continue
        dists = []
        for i in range(len(pts) - 1):
            a = pts[i]
            b = pts[i + 1]
            dists.append(_point_segment_distance(px, py, a[0], a[1], b[0], b[1]))
        if len(pts) >= 3 and (pts[0][0], pts[0][1]) != (pts[-1][0], pts[-1][1]):
            dists.append(_point_segment_distance(px, py, pts[-1][0], pts[-1][1], pts[0][0], pts[0][1]))
        if not dists:
            continue
        d = min(dists)
        dv = min(math.hypot(px - p[0], py - p[1]) for p in pts)
        item = {"id": str(name), "distance": d, "vertex_distance": dv}
        if best is None or d < best["distance"]:
            best = item
    return best or empty


def _nearest_opening(px, py, pz, openings: pd.DataFrame) -> Tuple[str, float]:
    d = _nearest_opening_detail(px, py, pz, openings)
    return d["id"], d["distance"]


def _parse_candidate_nodes(value: object):
    if value is None:
        return []
    raw = str(value).strip()
    if not raw:
        return []
    # build_peak_assessment apresenta candidatos como "12261 (471.0), 12262 (461.2)".
    # Para o cruzamento geométrico conserva-se apenas o identificador antes do valor entre parênteses.
    chunks = [c.strip() for c in re.split(r"[,;]+", raw) if c.strip()]
    toks = []
    for chunk in chunks:
        token = re.sub(r"\s*\([^)]*\)\s*$", "", chunk).strip()
        cid = canonical_node_id(token)
        if cid:
            toks.append(cid)
    return toks


def _candidate_cluster_metrics(candidate_ids, lookup: Dict[str, dict], peak_point: dict, mesh: float) -> dict:
    coords = []
    for nid in candidate_ids:
        p = lookup.get(canonical_node_id(nid))
        if not p:
            continue
        if math.isfinite(peak_point.get("z", float("nan"))) and abs(p["z"] - peak_point["z"]) > 0.15:
            continue
        coords.append((p["x"], p["y"], p["z"]))
    if not coords:
        return {
            "N_candidatos_georreferenciados": 0,
            "Extensão_P99_X_m": float("nan"),
            "Extensão_P99_Y_m": float("nan"),
            "Raio_P99_m": float("nan"),
            "Compacidade_P99": "Não avaliada",
        }
    xs = [p[0] for p in coords]
    ys = [p[1] for p in coords]
    dx = max(xs) - min(xs)
    dy = max(ys) - min(ys)
    px, py = peak_point["x"], peak_point["y"]
    radius = max(math.hypot(x - px, y - py) for x, y, _ in coords)
    if math.isfinite(mesh) and mesh > 1e-6:
        if radius <= 2.5 * mesh:
            compact = "Compacta"
        elif radius <= 5.0 * mesh:
            compact = "Moderada"
        else:
            compact = "Extensa"
    else:
        compact = "Não avaliada"
    return {
        "N_candidatos_georreferenciados": len(coords),
        "Extensão_P99_X_m": dx,
        "Extensão_P99_Y_m": dy,
        "Raio_P99_m": radius,
        "Compacidade_P99": compact,
    }


def _classify_geometry_context(p: dict, mesh: float, col: dict, beam: dict, wall: dict, opening: dict, cluster: dict) -> dict:
    # Heurísticas transparentes e exclusivamente diagnósticas. Não são critérios normativos.
    base_mesh = mesh if math.isfinite(mesh) and mesh > 1e-6 else 0.25
    near = max(2.0 * base_mesh, 0.35)
    corner = max(1.25 * base_mesh, 0.25)
    support_txt = str(p.get("support", "") or "").strip()

    zone = "Sem descontinuidade identificada"
    nature = "Pico local a investigar"
    confidence = "Baixa"
    action = (
        "Manter o máximo bruto no registo. Confirmar malha, cargas, vínculos e convergência local; "
        "não excluir nem suavizar o pico sem avaliação do projectista."
    )
    ref_id = ""
    ref_dist = float("nan")

    # Cantos de aberturas e extremidades de paredes são descontinuidades geométricas fortes.
    if opening.get("id") and math.isfinite(opening.get("vertex_distance", float("nan"))) and opening["vertex_distance"] <= corner:
        zone = "Canto de abertura/negativo"
        nature = "Singularidade geométrica potencial"
        confidence = "Alta" if opening["vertex_distance"] <= base_mesh else "Média"
        ref_id = opening["id"]
        ref_dist = opening["vertex_distance"]
        action = (
            "Manter o pico bruto e verificar a zona local do canto/bordo da abertura. Rever discretização, "
            "continuidade da armadura e eventual reforço local; não extrapolar automaticamente o máximo nodal para todo o painel."
        )
    elif wall.get("id") and math.isfinite(wall.get("endpoint_distance", float("nan"))) and wall["endpoint_distance"] <= corner:
        zone = "Extremidade de parede"
        nature = "Concentração estrutural local provável"
        confidence = "Alta" if wall["endpoint_distance"] <= base_mesh else "Média"
        ref_id = wall["id"]
        ref_dist = wall["endpoint_distance"]
        action = (
            "Manter o valor bruto e avaliar a faixa local na extremidade da parede, incluindo continuidade/ancoragem da armadura. "
            "Não usar o máximo pontual como armadura distribuída de todo o painel sem avaliação espacial."
        )
    elif col.get("id") and math.isfinite(col.get("distance", float("nan"))) and col["distance"] <= near:
        zone = "Junto a pilar"
        nature = "Concentração junto a apoio pontual provável"
        confidence = "Alta" if col["distance"] <= base_mesh else "Média"
        ref_id = col["id"]
        ref_dist = col["distance"]
        action = (
            "Manter o máximo bruto; avaliar armadura local da faixa de apoio e verificar punçoamento separadamente. "
            "A geometria apenas contextualiza o pico e não reduz o MEd utilizado pelo núcleo."
        )
    elif opening.get("id") and math.isfinite(opening.get("distance", float("nan"))) and opening["distance"] <= near:
        zone = "Bordo de abertura/negativo"
        nature = "Concentração junto a descontinuidade geométrica provável"
        confidence = "Alta" if opening["distance"] <= base_mesh else "Média"
        ref_id = opening["id"]
        ref_dist = opening["distance"]
        action = (
            "Verificar a faixa local junto ao bordo da abertura e a continuidade das armaduras. "
            "Manter o máximo bruto e confirmar a sensibilidade à malha antes de qualquer tratamento local."
        )
    elif wall.get("id") and math.isfinite(wall.get("distance", float("nan"))) and wall["distance"] <= near:
        zone = "Junto a parede"
        nature = "Concentração junto a apoio linear provável"
        confidence = "Alta" if wall["distance"] <= base_mesh else "Média"
        ref_id = wall["id"]
        ref_dist = wall["distance"]
        action = (
            "Avaliar o momento numa faixa local sobre/junto à parede e a pormenorização superior/inferior correspondente. "
            "Não suavizar nem excluir automaticamente o pico."
        )
    elif beam.get("id") and math.isfinite(beam.get("endpoint_distance", float("nan"))) and beam["endpoint_distance"] <= corner:
        zone = "Extremidade de viga"
        nature = "Concentração local junto a descontinuidade de apoio provável"
        confidence = "Alta" if beam["endpoint_distance"] <= base_mesh else "Média"
        ref_id = beam["id"]
        ref_dist = beam["endpoint_distance"]
        action = (
            "Verificar a transição laje-viga e a armadura local na extremidade do apoio. "
            "Manter o valor bruto e confirmar a distribuição espacial antes de adoptar reforço."
        )
    elif beam.get("id") and math.isfinite(beam.get("distance", float("nan"))) and beam["distance"] <= near:
        zone = "Sobre/junto a viga"
        nature = "Concentração junto a apoio linear provável"
        confidence = "Alta" if beam["distance"] <= base_mesh else "Média"
        ref_id = beam["id"]
        ref_dist = beam["distance"]
        action = (
            "Avaliar a faixa de apoio sobre/junto à viga e a continuidade da armadura. "
            "A classificação geométrica é diagnóstica e não altera o envelope de cálculo."
        )
    elif support_txt:
        zone = "Nó com restrição estrutural"
        nature = "Concentração associada a vínculo potencial"
        confidence = "Média"
        ref_id = support_txt
        ref_dist = 0.0
        action = (
            "Confirmar a condição de apoio/restrição e a sua representação no modelo. "
            "Manter o máximo bruto até validação do significado físico do vínculo."
        )
    elif cluster.get("Compacidade_P99") == "Compacta" and cluster.get("N_candidatos_georreferenciados", 0) >= 2:
        zone = "Aglomerado local de esforços elevados"
        nature = "Pico espacialmente concentrado sem descontinuidade importada próxima"
        confidence = "Média"
        action = (
            "Os candidatos P99 formam uma região compacta. Rever malha, cargas e eventual descontinuidade não importada; "
            "não eliminar o pico automaticamente."
        )

    return {
        "Tipo_zona_local": zone,
        "Natureza_pico_geométrica": nature,
        "Confiança_contexto": confidence,
        "Elemento_referência": ref_id,
        "Dist_referência_m": ref_dist,
        "Malha_local_estimada_m": mesh,
        "Raio_contexto_m": near,
        "Tratamento_recomendado_geom": action,
    }


def enrich_peak_assessment_with_geometry(peaks: pd.DataFrame, nodes=None, members=None, walls=None, openings=None) -> pd.DataFrame:
    """Acrescenta contexto espacial e classificação de zonas locais.

    A rotina é deliberadamente diagnóstica: nunca modifica MEd, envelopes, As, MRd,
    wk, estados ELU/ELS ou a lista de nós singulares confirmados.
    """
    if peaks is None or peaks.empty:
        return peaks
    nodes = nodes if isinstance(nodes, pd.DataFrame) else pd.DataFrame()
    members = members if isinstance(members, pd.DataFrame) else pd.DataFrame()
    walls = walls if isinstance(walls, pd.DataFrame) else pd.DataFrame()
    openings = openings if isinstance(openings, pd.DataFrame) else pd.DataFrame()
    lookup = _node_lookup(nodes)
    out = peaks.copy()
    rows = []
    for _, r in out.iterrows():
        node_id = canonical_node_id(r.get("Nó_pico", ""))
        p = lookup.get(node_id)
        ctx = {
            "Geo_disponível": "Sim" if p else "Não",
            "Pico_X_m": float("nan"), "Pico_Y_m": float("nan"), "Pico_Z_m": float("nan"),
            "Pico_support": "", "Pilar_próximo": "", "Dist_pilar_m": float("nan"),
            "Viga_próxima": "", "Dist_viga_m": float("nan"), "Dist_extremidade_viga_m": float("nan"),
            "Parede_próxima": "", "Dist_parede_m": float("nan"), "Dist_extremidade_parede_m": float("nan"),
            "Abertura_próxima": "", "Dist_abertura_m": float("nan"), "Dist_canto_abertura_m": float("nan"),
            "Malha_local_estimada_m": float("nan"), "Raio_contexto_m": float("nan"),
            "N_candidatos_georreferenciados": 0, "Extensão_P99_X_m": float("nan"), "Extensão_P99_Y_m": float("nan"),
            "Raio_P99_m": float("nan"), "Compacidade_P99": "Não avaliada",
            "Tipo_zona_local": "Sem geometria", "Natureza_pico_geométrica": "Não avaliada",
            "Confiança_contexto": "Não avaliada", "Elemento_referência": "", "Dist_referência_m": float("nan"),
            "Tratamento_recomendado_geom": "Importar a tabela geral de nós para permitir classificação espacial do pico.",
            "Contexto_geométrico": "Sem coordenadas do nó crítico.",
        }
        if p:
            px, py, pz = p["x"], p["y"], p["z"]
            ctx.update({"Pico_X_m": px, "Pico_Y_m": py, "Pico_Z_m": pz, "Pico_support": p["support"]})
            mesh = _local_mesh_spacing(nodes, px, py, pz)
            col = _nearest_member_detail(px, py, pz, members, lookup, "column")
            beam = _nearest_member_detail(px, py, pz, members, lookup, "beam")
            wall = _nearest_wall_detail(px, py, pz, walls, lookup)
            opening = _nearest_opening_detail(px, py, pz, openings)
            candidate_ids = _parse_candidate_nodes(r.get("Nós_candidatos_P99", ""))
            cluster = _candidate_cluster_metrics(candidate_ids, lookup, p, mesh)
            classified = _classify_geometry_context(p, mesh, col, beam, wall, opening, cluster)
            ctx.update({
                "Pilar_próximo": col["id"], "Dist_pilar_m": col["distance"],
                "Viga_próxima": beam["id"], "Dist_viga_m": beam["distance"], "Dist_extremidade_viga_m": beam["endpoint_distance"],
                "Parede_próxima": wall["id"], "Dist_parede_m": wall["distance"], "Dist_extremidade_parede_m": wall["endpoint_distance"],
                "Abertura_próxima": opening["id"], "Dist_abertura_m": opening["distance"], "Dist_canto_abertura_m": opening["vertex_distance"],
            })
            ctx.update(cluster)
            ctx.update(classified)
            zone = ctx["Tipo_zona_local"]
            conf = ctx["Confiança_contexto"]
            ref = ctx["Elemento_referência"]
            dref = ctx["Dist_referência_m"]
            if ref and math.isfinite(dref):
                ctx["Contexto_geométrico"] = (
                    f"{zone}; referência {ref}; distância ≈ {dref:.3f} m; confiança {conf.lower()}. "
                    "Classificação diagnóstica: não altera o envelope resistente nem exclui o pico."
                )
            else:
                ctx["Contexto_geométrico"] = (
                    f"{zone}; confiança {conf.lower()}. Classificação diagnóstica: não altera o envelope resistente nem exclui o pico."
                )
        rows.append(ctx)
    extra = pd.DataFrame(rows, index=out.index)
    return pd.concat([out, extra], axis=1)


def build_geometry_peak_diagnostic(peaks: pd.DataFrame) -> pd.DataFrame:
    """Converte a classificação geométrica dos picos em mensagens de diagnóstico da GUI/relatório."""
    if peaks is None or peaks.empty or "Geo_disponível" not in peaks.columns:
        return pd.DataFrame()
    rows = []
    for _, r in peaks.iterrows():
        if str(r.get("Geo_disponível", "Não")) != "Sim":
            continue
        panel = r.get("Panel", "")
        pflag = str(r.get("Pico_FEM", "Não"))
        if pflag != "Sim":
            continue
        zone = str(r.get("Tipo_zona_local", "Contexto geométrico disponível"))
        nature = str(r.get("Natureza_pico_geométrica", ""))
        conf = str(r.get("Confiança_contexto", ""))
        ratio = safe_float(r.get("Pico_ratio_max_P95", 0.0), 0.0)
        problem = f"Pico FEM com contexto geométrico: {zone}. {nature}. max/P95={ratio:.2f}; confiança={conf}."
        action = str(r.get("Tratamento_recomendado_geom", "Manter o máximo bruto e avaliar a zona local."))
        rows.append({
            "Painel": panel,
            "Severidade": "Média" if conf in {"Alta", "Média"} else "Informativa",
            "Problema": problem,
            "Acção recomendada": action,
            "Origem": "Geometria opcional / Picos FEM",
        })
    return pd.DataFrame(rows)


def merge_geometry_peak_context_into_summary(summary: pd.DataFrame, peaks: pd.DataFrame) -> pd.DataFrame:
    """Acrescenta contexto geométrico ao resumo sem alterar o estado estrutural."""
    if summary is None or summary.empty or peaks is None or peaks.empty or "Panel" not in summary.columns or "Panel" not in peaks.columns:
        return summary
    cols = [
        "Panel", "Geo_disponível", "Tipo_zona_local", "Natureza_pico_geométrica", "Confiança_contexto",
        "Elemento_referência", "Dist_referência_m", "Malha_local_estimada_m", "Compacidade_P99",
        "Tratamento_recomendado_geom",
    ]
    available = [c for c in cols if c in peaks.columns]
    if len(available) <= 1:
        return summary
    geo = peaks[available].drop_duplicates(subset=["Panel"], keep="first").copy()
    out = summary.copy()
    # Remove versões anteriores caso a geometria seja recarregada e o resumo reprocessado.
    for c in available:
        if c != "Panel" and c in out.columns:
            out = out.drop(columns=[c])
    return out.merge(geo, on="Panel", how="left")
