# -*- coding: utf-8 -*-
import math
import re
import pandas as pd
from typing import Dict

def normalize_text(s: str) -> str:
    s = str(s).strip().lower()
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s)
    return s

def safe_float(value, default=float("nan")):
    try:
        if pd.isna(value):
            return default
        if isinstance(value, (int, float)):
            return float(value)
        s = str(value).strip()
        if not s:
            return default
        s = s.replace("\u00a0", " ").replace(" ", "")
        # Formato PT: 1.234,56
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+,\d+", s):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", ".")
        return float(s)
    except Exception:
        return default

def bar_area_mm2(phi_mm: float) -> float:
    return math.pi * phi_mm * phi_mm / 4.0

def parse_strength_from_class(cls: str, default: float = 30.0) -> float:
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*/\s*(\d+(?:[.,]\d+)?)", str(cls))
    if m:
        return float(m.group(1).replace(",", "."))
    m = re.search(r"(\d+(?:[.,]\d+)?)", str(cls))
    if m:
        return float(m.group(1).replace(",", "."))
    return default

def concrete_props(fck: float, alpha_cc: float = 1.0, gamma_c: float = 1.5) -> Dict[str, float]:
    fcm = fck + 8.0
    fcd = alpha_cc * fck / gamma_c
    fctm = 0.30 * fck ** (2.0 / 3.0) if fck <= 50 else 2.12 * math.log(1 + fcm / 10.0)
    return {"fck": fck, "fcm": fcm, "fcd": fcd, "fctm": fctm}

def steel_fyd(fyk: float, gamma_s: float = 1.15) -> float:
    return fyk / gamma_s

def displacement_unit_factor_to_mm(unit: str) -> float:
    u = normalize_text(unit)
    if u in ("m", "metro", "metros") or " m" == u:
        return 1000.0
    if "cm" in u:
        return 10.0
    if "mm" in u:
        return 1.0
    return 10.0

def parse_deflection_limit_to_ratio(limit_text: str) -> float:
    txt = normalize_text(limit_text)
    m = re.search(r"(?:l|span|vao|vão)\s*/\s*(\d+(?:[.,]\d+)?)", txt)
    if not m:
        m = re.search(r"/(\d+(?:[.,]\d+)?)", txt)
    if m:
        den = safe_float(m.group(1), 250.0)
        return max(1.0, den)
    if "500" in txt:
        return 500.0
    return 250.0

def moment_unit_factor_to_kNm_per_m(unit: str) -> float:
    u = normalize_text(unit)
    if "nmm/mm" in u:
        return 0.001
    if "nm/m" in u and "kn" not in u:
        return 0.001
    if "knmm/m" in u:
        return 0.001
    if "knm/m" in u or "kn.m/m" in u or "kn·m/m" in u:
        return 1.0
    return 1.0

def shear_unit_factor_to_kN_per_m(unit: str) -> float:
    u = normalize_text(unit)
    if "n/mm" in u:
        return 1.0
    if "n/m" in u and "kn" not in u:
        return 0.001
    if "kn/m" in u:
        return 1.0
    return 1.0

def status_rank(status: str) -> int:
    order = {"Informativo": -1, "OK": 0, "OK*": 1, "Verificar": 2, "Dados insuficientes": 3, "Não conforme": 4}
    return order.get(str(status), 2)
