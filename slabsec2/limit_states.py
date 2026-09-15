# -*- coding: utf-8 -*-
"""Estados limite auxiliares para o núcleo SlabsEC2.

Mantém formulações estruturais pequenas e auditáveis fora da GUI/designer.
Âmbito: secção rectangular de laje, b=1,00 m, flexão simples sem esforço normal relevante.
"""
from __future__ import annotations

import math
from typing import Dict


def concrete_block_parameters(fck: float) -> Dict[str, float]:
    """Parâmetros do bloco rectangular EC2 3.1.7 para fck até 90 MPa."""
    fck = max(0.0, min(float(fck), 90.0))
    if fck <= 50.0:
        lam = 0.80
        eta = 1.00
        eps_cu3 = 3.50e-3
    else:
        lam = 0.80 - (fck - 50.0) / 400.0
        eta = 1.00 - (fck - 50.0) / 200.0
        eps_cu3 = (2.60 + 35.0 * ((90.0 - fck) / 100.0) ** 4) * 1e-3
    return {"lambda": lam, "eta": eta, "eps_cu3": eps_cu3}


def singly_reinforced_limit(d_mm: float, fck: float, fcd: float, fyd: float,
                            Es: float = 200000.0, b_mm: float = 1000.0) -> Dict[str, float]:
    """Limite da hipótese de secção simplesmente armada com aço traccionado a fyd.

    O limite é obtido impondo eps_s >= eps_yd ao diagrama de deformações último.
    Não é um limite de redistribuição; é uma verificação de coerência da hipótese T=As*fyd.
    """
    d = max(float(d_mm), 1e-9)
    p = concrete_block_parameters(fck)
    eps_yd = max(float(fyd), 0.0) / max(float(Es), 1.0)
    eps_cu3 = p["eps_cu3"]
    xi_bal = eps_cu3 / max(eps_cu3 + eps_yd, 1e-12)
    x_bal = xi_bal * d
    c_force = p["eta"] * float(fcd) * b_mm * p["lambda"] * x_bal
    as_bal = c_force / max(float(fyd), 1e-12)
    z_bal = d - 0.5 * p["lambda"] * x_bal
    mrd_lim = as_bal * float(fyd) * z_bal / 1e6
    return {
        "xi_bal": xi_bal, "x_bal_mm": x_bal, "As_bal_mm2_m": as_bal,
        "z_bal_mm": z_bal, "MRd_singly_lim_kNm_m": mrd_lim,
        "eps_yd": eps_yd, "eps_cu3": eps_cu3,
        "lambda": p["lambda"], "eta": p["eta"],
    }


def flexural_state(as_mm2_m: float, d_mm: float, fck: float, fcd: float, fyd: float,
                   Es: float = 200000.0, b_mm: float = 1000.0) -> Dict[str, float | str]:
    """Estado resistente por compatibilidade de extensões EC2 6.1 / 3.1.7 / 3.2.7.

    A versão 2.15 limitava artificialmente MRd ao ponto em que a armadura traccionada
    atingia exactamente fyd. Isso classificava como ``fora do domínio`` secções que
    continuam fisicamente calculáveis com sigma_s < fyd. Nesta versão, o equilíbrio
    C=T é resolvido com o diagrama elástico-perfeitamente plástico do aço:

        sigma_s = min(fyd, Es * eps_s)
        eps_s   = eps_cu3 * (d-x) / x

    O ponto de cedência continua reportado como diagnóstico de ductilidade, mas deixa
    de truncar a resistência da secção.
    """
    As = max(float(as_mm2_m), 0.0)
    d = max(float(d_mm), 1e-9)
    p = concrete_block_parameters(fck)
    A = p["eta"] * p["lambda"] * b_mm * max(float(fcd), 1e-12)
    lim = singly_reinforced_limit(d, fck, fcd, fyd, Es=Es, b_mm=b_mm)

    if As <= 1e-12:
        return {
            "MRd_kNm_m": 0.0, "MRd_yield_assumption_kNm_m": 0.0,
            "x_mm": 0.0, "z_mm": d, "x_d": 0.0,
            "eps_s": float("inf"), "eps_yd": lim["eps_yd"],
            "sigma_s_uls_MPa": 0.0, "steel_yields": "Não",
            "section_domain_valid": "Sim", "ductility_status": "Sem solicitação",
            **lim,
        }

    # Primeiro testa a hipótese de aço a fyd.
    x_yield = As * float(fyd) / max(A, 1e-12)
    eps_s_yield = (p["eps_cu3"] * max(d - x_yield, 0.0) / x_yield) if x_yield > 1e-12 else float("inf")
    if x_yield < d and eps_s_yield + 1e-12 >= lim["eps_yd"]:
        x = x_yield
        eps_s = eps_s_yield
        sigma_s = float(fyd)
        yielding = True
    else:
        # Ramo elástico do aço: A*x = As*Es*eps_cu3*(d-x)/x.
        K = As * max(float(Es), 1.0) * p["eps_cu3"]
        disc = K * K + 4.0 * A * K * d
        x = (-K + math.sqrt(max(disc, 0.0))) / max(2.0 * A, 1e-12)
        x = min(max(x, 1e-12), d * (1.0 - 1e-12))
        eps_s = p["eps_cu3"] * (d - x) / x
        sigma_s = min(float(fyd), max(0.0, float(Es) * eps_s))
        yielding = sigma_s >= float(fyd) - 1e-6

    z = max(0.0, d - 0.5 * p["lambda"] * x)
    c_force = A * x
    mrd = c_force * z / 1e6
    mrd_yield_assumption = As * float(fyd) * max(0.0, d - 0.5 * p["lambda"] * x_yield) / 1e6
    xi = x / d if d > 0.0 else 0.0

    return {
        "MRd_kNm_m": mrd,
        "MRd_yield_assumption_kNm_m": mrd_yield_assumption,
        "x_mm": x, "z_mm": z, "x_d": xi,
        "eps_s": eps_s, "eps_yd": lim["eps_yd"],
        "sigma_s_uls_MPa": sigma_s,
        "steel_yields": "Sim" if yielding else "Não",
        # Compatibilidade de extensões resolvida; não confundir ausência de cedência com invalidade.
        "section_domain_valid": "Sim",
        "ductility_status": "Aço cede" if yielding else "Aço abaixo de fyd — verificar ductilidade/redistribuição quando aplicável",
        **lim,
    }


def service_stress_limits(fck: float, fyk: float, k1: float = 0.60, k2: float = 0.45,
                          k3: float = 0.80) -> Dict[str, float]:
    """Valores recomendados EC2 7.2 / Anexo Nacional quando aplicáveis."""
    return {
        "sigma_c_char_lim_MPa": k1 * float(fck),
        "sigma_c_qp_linear_creep_lim_MPa": k2 * float(fck),
        "sigma_s_char_lim_MPa": k3 * float(fyk),
        "k1": k1, "k2": k2, "k3": k3,
    }
