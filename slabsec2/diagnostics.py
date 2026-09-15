# -*- coding: utf-8 -*-
"""Diagnósticos robustos dos resultados de placa.

Os indicadores deste módulo são informativos. Não alteram esforços nem substituem
qualquer valor do modelo de análise/cálculo.
"""
from __future__ import annotations

import math
import pandas as pd

from .utils import safe_float


def assess_mxy_dominance(grp: pd.DataFrame, min_reference_kNm_m: float = 1.0) -> dict:
    """Avalia a relevância de MXY sem quocientes artificiais junto de MXX/MYY≈0.

    O indicador principal compara os percentis 95 de |MXY| e do momento normal de
    referência max(|MXX|, |MYY|). É também devolvido um indicador máximo/P95 apenas
    como informação complementar. O denominador nunca é inferior a
    ``min_reference_kNm_m``.
    """
    empty = {
        "MXY_diagnostic_available": "Não",
        "MXY_ratio_robust": 0.0,
        "MXY_ratio_max_to_P95_normal": 0.0,
        "MXY_P95_kNm_m": 0.0,
        "MXY_max_kNm_m": 0.0,
        "Mnormal_P95_kNm_m": 0.0,
        "MXY_diagnostic_note": "Momentos brutos MXX/MYY/MXY não disponíveis para diagnóstico.",
    }
    if grp is None or grp.empty or not {"MXX_kNm_m", "MYY_kNm_m", "MXY_kNm_m"}.issubset(grp.columns):
        return empty

    g = grp.copy()
    # O diagnóstico é mais útil nos casos ELU, quando esta classificação existe.
    if "Case_classification" in g.columns:
        gelu = g[g["Case_classification"].astype(str) == "ELU"].copy()
        if not gelu.empty:
            g = gelu

    mxx = pd.to_numeric(g["MXX_kNm_m"], errors="coerce").fillna(0.0).abs()
    myy = pd.to_numeric(g["MYY_kNm_m"], errors="coerce").fillna(0.0).abs()
    mxy = pd.to_numeric(g["MXY_kNm_m"], errors="coerce").fillna(0.0).abs()
    normal = pd.concat([mxx, myy], axis=1).max(axis=1)

    mxy_p95 = safe_float(mxy.quantile(0.95), 0.0)
    mxy_max = safe_float(mxy.max(), 0.0)
    normal_p95_raw = safe_float(normal.quantile(0.95), 0.0)
    normal_ref = max(normal_p95_raw, float(min_reference_kNm_m))
    ratio_robust = mxy_p95 / normal_ref if normal_ref > 0 else 0.0
    ratio_max = mxy_max / normal_ref if normal_ref > 0 else 0.0

    if mxy_max <= 1e-9 and normal_p95_raw <= 1e-9:
        note = "Momentos brutos praticamente nulos; indicador MXY não significativo."
    elif normal_p95_raw < float(min_reference_kNm_m):
        note = (
            f"P95 do momento normal inferior a {float(min_reference_kNm_m):.1f} kNm/m; "
            "foi aplicado um denominador mínimo para evitar quocientes artificiais."
        )
    else:
        note = "Indicador baseado em P95(|MXY|)/P95(max(|MXX|,|MYY|)); não altera os momentos de cálculo."

    return {
        "MXY_diagnostic_available": "Sim",
        "MXY_ratio_robust": ratio_robust,
        "MXY_ratio_max_to_P95_normal": ratio_max,
        "MXY_P95_kNm_m": mxy_p95,
        "MXY_max_kNm_m": mxy_max,
        "Mnormal_P95_kNm_m": normal_p95_raw,
        "MXY_diagnostic_note": note,
    }


def select_worst_els_wk_issue(grp: pd.DataFrame):
    """Selecciona de forma fail-safe a linha ELS/wk mais gravosa.

    Considera apenas estados ``Não conforme`` e ``Verificar``. A prioridade é:
    1) ``Não conforme``;
    2) ``Verificar``;
    3) maior ``ELS_wk_ratio`` dentro do mesmo nível de gravidade.

    Retorna uma ``Series`` ou ``None`` se não existirem linhas problemáticas.
    Esta função evita acessos posicionais a subconjuntos vazios.
    """
    if grp is None or grp.empty or "ELS_wk_status" not in grp.columns:
        return None
    # v2.15.2: diagnósticos GLOBAIS de wk só podem usar linhas que pertencem ao
    # envelope distribuído. Picos RAW/singularidades continuam no resultado e são
    # reportados separadamente como verificação local obrigatória.
    base = grp.copy()
    if "Design_relevant" in base.columns:
        base = base[base["Design_relevant"].astype(str) != "Não"].copy()
    if "Excluded_from_distributed_envelope" in base.columns:
        base = base[base["Excluded_from_distributed_envelope"].astype(str) != "Sim"].copy()
    if "Case_classification" in base.columns:
        base = base[base["Case_classification"].astype(str) == "ELS-QP"].copy()
    bad = base[base["ELS_wk_status"].astype(str).isin(["Não conforme", "Verificar"])].copy()
    if bad.empty:
        return None
    severity = {"Não conforme": 2, "Verificar": 1}
    bad["__wk_severity"] = bad["ELS_wk_status"].astype(str).map(severity).fillna(0).astype(int)
    if "ELS_wk_ratio" in bad.columns:
        bad["__wk_ratio_num"] = pd.to_numeric(bad["ELS_wk_ratio"], errors="coerce").fillna(-1.0)
    else:
        bad["__wk_ratio_num"] = -1.0
    bad = bad.sort_values(["__wk_severity", "__wk_ratio_num"], ascending=[False, False])
    if bad.empty:
        return None
    return bad.iloc[0]
