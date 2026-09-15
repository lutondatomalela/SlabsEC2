# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re
from typing import Dict, Tuple

import pandas as pd

from ..importers import read_delimited_file_robust
from ..utils import normalize_text, safe_float
from ..peaks import canonical_node_id


ALIASES: Dict[str, Dict[str, list]] = {
    "nodes": {
        "node": ["node", "nó", "no"],
        "x": ["x", "x (m)", "x [m]", "coord x", "coordenada x"],
        "y": ["y", "y (m)", "y [m]", "coord y", "coordenada y"],
        "z": ["z", "z (m)", "z [m]", "coord z", "coordenada z", "cota"],
        "support": ["support", "apoio", "restraint", "restrição", "restricao"],
    },
    "members": {
        "member": ["member", "membro", "bar", "barra", "element", "elemento"],
        "node1": ["node 1", "node1", "nó 1", "no 1", "nó1", "no1"],
        "node2": ["node 2", "node2", "nó 2", "no 2", "nó2", "no2"],
        "structure_object": ["structure object", "object type", "tipo", "tipo de objecto", "tipo de objeto"],
        "material": ["material", "mat"],
    },
    "walls": {
        "panel_node_case": ["panel/node/case", "panel / node / case", "painel/nó/caso", "painel/no/caso"],
        "panel": ["panel", "painel"],
        "node": ["node", "nó", "no"],
        "case": ["case", "caso", "combination", "combinação", "combinacao"],
    },
    "openings": {
        "contour": ["contour", "contorno", "opening", "abertura", "negative", "negativo", "id", "nome"],
        "type": ["type", "tipo"],
        "x": ["x", "x (m)", "x [m]", "coord x", "coordenada x"],
        "y": ["y", "y (m)", "y [m]", "coord y", "coordenada y"],
        "z": ["z", "z (m)", "z [m]", "coord z", "coordenada z", "cota"],
    },
}


def _simplify_header(value: object) -> str:
    txt = normalize_text(value)
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt


def _rename(df: pd.DataFrame, kind: str) -> pd.DataFrame:
    aliases = ALIASES[kind]
    norm_to_orig = {_simplify_header(c): c for c in df.columns}
    rename = {}
    for target, vals in aliases.items():
        for alias in vals:
            a = _simplify_header(alias)
            if a in norm_to_orig:
                rename[norm_to_orig[a]] = target
                break
    return df.rename(columns=rename).copy()


def _parse_panel_node_case(value: object):
    parts = [p.strip() for p in str(value).split("/")]
    panel = parts[0] if len(parts) > 0 else ""
    node = parts[1] if len(parts) > 1 else ""
    case = parts[2] if len(parts) > 2 else ""
    return panel, node, case


def _float_series(s: pd.Series) -> pd.Series:
    return s.map(lambda v: safe_float(v, float("nan")))


def clean_geometry_dataframe(df: pd.DataFrame, kind: str, default_contour: str = "") -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    kind = str(kind).strip().lower()
    if kind not in ALIASES:
        raise ValueError(f"Tipo de geometria desconhecido: {kind}")
    out = _rename(df, kind)

    if kind == "nodes":
        required = {"node", "x", "y", "z"}
        missing = required - set(out.columns)
        if missing:
            raise ValueError("Tabela de nós sem colunas obrigatórias: " + ", ".join(sorted(missing)))
        out["node"] = out["node"].map(canonical_node_id)
        for c in ("x", "y", "z"):
            out[c] = _float_series(out[c])
        if "support" not in out.columns:
            out["support"] = ""
        out["support"] = out["support"].fillna("").astype(str).str.strip()
        out = out[(out["node"] != "") & out[["x", "y", "z"]].notna().all(axis=1)].copy()
        out = out.drop_duplicates(subset=["node"], keep="last")
        return out[["node", "x", "y", "z", "support"]].reset_index(drop=True)

    if kind == "members":
        required = {"member", "node1", "node2", "structure_object"}
        missing = required - set(out.columns)
        if missing:
            raise ValueError("Tabela de vigas/pilares sem colunas obrigatórias: " + ", ".join(sorted(missing)))
        out["member"] = out["member"].astype(str).str.strip()
        out["node1"] = out["node1"].map(canonical_node_id)
        out["node2"] = out["node2"].map(canonical_node_id)
        out["structure_object"] = out["structure_object"].fillna("").astype(str).str.strip()
        if "material" not in out.columns:
            out["material"] = ""
        out["material"] = out["material"].fillna("").astype(str).str.strip()
        out = out[(out["node1"] != "") & (out["node2"] != "")].copy()
        return out[["member", "node1", "node2", "structure_object", "material"]].reset_index(drop=True)

    if kind == "walls":
        if "panel_node_case" in out.columns:
            parsed = out["panel_node_case"].map(_parse_panel_node_case)
            if "panel" not in out.columns:
                out["panel"] = parsed.map(lambda t: t[0])
            if "node" not in out.columns:
                out["node"] = parsed.map(lambda t: t[1])
            if "case" not in out.columns:
                out["case"] = parsed.map(lambda t: t[2])
        if not {"panel", "node"}.issubset(out.columns):
            raise ValueError("Tabela de paredes deve conter 'Panel/Node/Case' ou colunas Panel e Node.")
        out["panel"] = out["panel"].fillna("").astype(str).str.strip()
        # Algumas tabelas de resultados de paredes apresentam o nó como 25' / 25";
        # para cruzamento com a tabela geral de nós conserva-se o identificador numérico.
        out["node"] = out["node"].map(lambda v: canonical_node_id(str(v).strip().strip("\'\"")))
        if "case" not in out.columns:
            out["case"] = ""
        out["case"] = out["case"].fillna("").astype(str).str.strip()
        out = out[(out["panel"] != "") & (out["node"] != "")].copy()
        # Para contexto geométrico basta uma ocorrência única de cada nó do painel.
        out = out.drop_duplicates(subset=["panel", "node"], keep="first")
        return out[["panel", "node", "case"]].reset_index(drop=True)

    # openings
    required = {"x", "y", "z"}
    missing = required - set(out.columns)
    if missing:
        raise ValueError("Tabela de abertura/negativo sem colunas obrigatórias: " + ", ".join(sorted(missing)))
    for c in ("x", "y", "z"):
        out[c] = _float_series(out[c])
    if "type" not in out.columns:
        out["type"] = "Segmento"
    out["type"] = out["type"].fillna("Segmento").astype(str).str.strip()
    if "contour" not in out.columns:
        out["contour"] = default_contour or "Abertura 1"
    else:
        out["contour"] = out["contour"].fillna("").astype(str).str.strip()
        out.loc[out["contour"] == "", "contour"] = default_contour or "Abertura 1"
    out = out[out[["x", "y", "z"]].notna().all(axis=1)].copy()
    out["sequence"] = out.groupby("contour").cumcount() + 1
    return out[["contour", "sequence", "type", "x", "y", "z"]].reset_index(drop=True)


def _sheet_score(df: pd.DataFrame, kind: str) -> int:
    if df is None or df.empty:
        return 0
    renamed = _rename(df, kind)
    cols = set(renamed.columns)
    expected = {
        "nodes": {"node", "x", "y", "z"},
        "members": {"member", "node1", "node2", "structure_object"},
        "walls": {"panel_node_case", "panel", "node"},
        "openings": {"x", "y", "z", "type"},
    }[kind]
    return len(cols & expected)


def read_geometry_file(path: str, kind: str, default_contour: str = "") -> Tuple[pd.DataFrame, str, str]:
    """Lê uma tabela geométrica opcional em XLSX/XLS/CSV/TXT.

    Returns: (dataframe limpo, nota da origem, folha seleccionada)
    """
    kind = kind.lower()
    if path.lower().endswith((".xlsx", ".xls")):
        xls = pd.ExcelFile(path)
        best_name = None
        best_score = -1
        for name in xls.sheet_names:
            try:
                sample = pd.read_excel(path, sheet_name=name, dtype=str, nrows=25)
                score = _sheet_score(sample, kind)
                if score > best_score:
                    best_score = score
                    best_name = name
            except Exception:
                continue
        if best_name is None:
            raise ValueError("Não foi possível identificar uma folha legível no workbook.")
        raw = pd.read_excel(path, sheet_name=best_name, dtype=str)
        clean = clean_geometry_dataframe(raw, kind, default_contour=default_contour)
        return clean, f"Excel: {os.path.basename(path)}; folha: {best_name}", best_name

    raw, note = read_delimited_file_robust(path)
    clean = clean_geometry_dataframe(raw, kind, default_contour=default_contour)
    return clean, f"{os.path.basename(path)}; {note}", ""
