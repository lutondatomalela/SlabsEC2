# -*- coding: utf-8 -*-
"""Rastreabilidade explícita dos governantes de dimensionamento."""
from __future__ import annotations

import math
import pandas as pd

from .utils import safe_float

_LABEL_DATA = {
    "X+": {"med": "MEd_x_sup_kNm_m", "asreq": "Asx+_req_mm2_m", "asprov": "Asx+_prov_mm2_m", "mrd": "MRd_x+_kNm_m", "wk": "wk_x+_mm", "sigmas": "sigma_s_x+_MPa", "sigmac": "sigma_c_x+_MPa"},
    "X-": {"med": "MEd_x_inf_kNm_m", "asreq": "Asx-_req_mm2_m", "asprov": "Asx-_prov_mm2_m", "mrd": "MRd_x-_kNm_m", "wk": "wk_x-_mm", "sigmas": "sigma_s_x-_MPa", "sigmac": "sigma_c_x-_MPa"},
    "Y+": {"med": "MEd_y_sup_kNm_m", "asreq": "Asy+_req_mm2_m", "asprov": "Asy+_prov_mm2_m", "mrd": "MRd_y+_kNm_m", "wk": "wk_y+_mm", "sigmas": "sigma_s_y+_MPa", "sigmac": "sigma_c_y+_MPa"},
    "Y-": {"med": "MEd_y_inf_kNm_m", "asreq": "Asy-_req_mm2_m", "asprov": "Asy-_prov_mm2_m", "mrd": "MRd_y-_kNm_m", "wk": "wk_y-_mm", "sigmas": "sigma_s_y-_MPa", "sigmac": "sigma_c_y-_MPa"},
}


def _row_at_max(g: pd.DataFrame, col: str):
    if g is None or g.empty or col not in g.columns:
        return None
    s = pd.to_numeric(g[col], errors="coerce")
    if not s.notna().any():
        return None
    return g.loc[s.idxmax()]


def _optional_float(value):
    try:
        if pd.isna(value):
            return float("nan")
        return float(value)
    except Exception:
        return float("nan")

def _base_record(panel, label, state, row, d):
    if row is None:
        return None
    med = safe_float(row.get(d["med"], 0.0), 0.0)
    mrd = safe_float(row.get(d["mrd"], 0.0), 0.0)
    util = med / mrd if mrd > 1e-9 else (999.0 if med > 1e-9 else 0.0)
    return {
        "Panel": panel,
        "Face_direção": label,
        "Estado_limite": state,
        "Case_governante": row.get("Case", ""),
        "Node_governante": row.get("Node", ""),
        "Case_classification": row.get("Case_classification", ""),
        "Moment_input_mode": row.get("Moment_input_mode", ""),
        "Equivalent_moment_source": row.get("Equivalent_moment_source", ""),
        "WA_method": row.get("WA_method", ""),
        "WA_transformation_applied": row.get("WA_transformation_applied", ""),
        "MXX_raw": _optional_float(row.get("MXX_raw", float("nan"))),
        "MYY_raw": _optional_float(row.get("MYY_raw", float("nan"))),
        "MXY_raw": _optional_float(row.get("MXY_raw", float("nan"))),
        "MXX_kNm_m": _optional_float(row.get("MXX_kNm_m", float("nan"))),
        "MYY_kNm_m": _optional_float(row.get("MYY_kNm_m", float("nan"))),
        "MXY_kNm_m": _optional_float(row.get("MXY_kNm_m", float("nan"))),
        "MXY_abs_kNm_m": abs(_optional_float(row.get("MXY_kNm_m", float("nan")))),
        "MEd_governante_kNm_m": med,
        "As_req_mm2_m": safe_float(row.get(d["asreq"], 0.0), 0.0),
        "As_prov_mm2_m": safe_float(row.get(d["asprov"], 0.0), 0.0),
        "Armadura_adoptada": row.get(label + "_rebar", ""),
        "Armadura_base": row.get(label + "_base", ""),
        "Armadura_adicional": row.get(label + "_additional", ""),
        "MRd_kNm_m": mrd,
        "util_M_face": util,
        "wk_face_mm": safe_float(row.get(d["wk"], float("nan")), float("nan")),
        "sigma_s_face_MPa": safe_float(row.get(d["sigmas"], float("nan")), float("nan")),
        "sigma_c_face_MPa": safe_float(row.get(d["sigmac"], float("nan")), float("nan")),
        "FEM_peak_flag": row.get("FEM_peak_flag", ""),
        "FEM_peak_ratio": safe_float(row.get("FEM_peak_ratio", 0.0), 0.0),
        "Singular_node_confirmed": row.get("Singular_node_confirmed", "Não"),
        "Verification_reason": row.get("Verification_reason", ""),
    }


def build_governing_traceability(results: pd.DataFrame) -> pd.DataFrame:
    """Uma linha por painel × face/direcção × estado limite governante.

    ELU governa por MEd equivalente. ELS-QP governa por wk da própria face/direcção.
    ELS-CHAR governa pela tensão de aço da própria face/direcção. Mantém os três momentos
    raw na mesma linha para permitir reconstruir a transformação Wood-Armer.
    """
    if results is None or results.empty or "Panel" not in results.columns:
        return pd.DataFrame()
    rows = []
    for panel, g0 in results.groupby("Panel", dropna=False, sort=False):
        g = g0.copy()
        if "Excluded_from_distributed_envelope" in g.columns:
            distributed = g[g["Excluded_from_distributed_envelope"].astype(str) != "Sim"].copy()
            if not distributed.empty:
                g = distributed
        cls = g.get("Case_classification", pd.Series("", index=g.index)).astype(str)
        gu = g[cls == "ELU"]
        gq = g[cls == "ELS-QP"]
        gc = g[cls == "ELS-CHAR"]
        for label, d in _LABEL_DATA.items():
            r = _row_at_max(gu, d["med"])
            rec = _base_record(panel, label, "ELU — flexão", r, d)
            if rec:
                rec["Métrica_governante"] = "MEd equivalente máximo"
                rec["Valor_métrica"] = rec["MEd_governante_kNm_m"]
                rows.append(rec)
            r = _row_at_max(gq, d["wk"])
            rec = _base_record(panel, label, "ELS-QP — fendilhação", r, d)
            if rec:
                rec["Métrica_governante"] = "wk máximo da face/direcção"
                rec["Valor_métrica"] = rec["wk_face_mm"]
                rows.append(rec)
            r = _row_at_max(gc, d["sigmas"])
            rec = _base_record(panel, label, "ELS-CHAR — tensão no aço", r, d)
            if rec:
                rec["Métrica_governante"] = "σs máximo da face/direcção"
                rec["Valor_métrica"] = rec["sigma_s_face_MPa"]
                rows.append(rec)
    return pd.DataFrame(rows).reset_index(drop=True)
