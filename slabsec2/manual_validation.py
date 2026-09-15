# -*- coding: utf-8 -*-
"""Campanha de validação independente com valores de referência bloqueados.

Os valores desta bateria não são calculados por funções do núcleo SlabsEC2. Foram obtidos
separadamente a partir das expressões adoptadas do EC2 para uma faixa rectangular de 1 m e
ficam deliberadamente bloqueados neste ficheiro para detectar regressões.

Âmbito:
- profundidade útil segundo a ordem física configurada das malhas;
- As,min de flexão;
- As,req em ELU;
- MRd/x/z para armadura conhecida;
- secção fendilhada e wk em ELS-QP;
- transição secção não fendilhada/fendilhada e ramos 7.11/7.14 de sr,max;
- diâmetro equivalente de famílias de armadura diferentes.
"""
from __future__ import annotations

import math
from typing import Dict, List

from .designer import SlabDesigner

# Valores bloqueados. Unidades: mm, MPa, kNm/m, mm2/m conforme os nomes dos campos.
REFERENCE_CASES: List[Dict[str, float]] = [
    dict(id="R01", h=180.0, c=25.0, phi_this=10.0, phi_other=10.0, fck=25.0, M=30.0, phi=10.0, spacing=150.0,
         d=150.0, As_min=200.067185761174, As_req=480.037950800784, As_bar=523.598775598299, MRd=32.592988137462,
         x=17.073873117336, z=143.170450753066, xcr=28.440388647189, sigma_s=407.741476911533,
         hceff=50.519870450937, rho=0.010364214534, c_eff=25.0, sr=249.025936975227, wk=0.376314537273, branch="7.11"),
    dict(id="R02", h=200.0, c=30.0, phi_this=12.0, phi_other=10.0, fck=30.0, M=60.0, phi=12.0, spacing=150.0,
         d=164.0, As_min=247.010804157504, As_req=894.493552149904, As_bar=753.98223686155, MRd=51.075589679888,
         x=20.488647740803, z=155.804540903679, xcr=34.489308296079, sigma_s=521.807290991877,
         hceff=55.170230567974, rho=0.013666468838, c_eff=30.0, sr=251.270453409014, wk=0.54019968541, branch="7.11"),
    dict(id="R03", h=250.0, c=35.0, phi_this=16.0, phi_other=12.0, fck=35.0, M=100.0, phi=16.0, spacing=150.0,
         d=207.0, As_min=345.520357224075, As_req=1173.044367383008, As_bar=1340.412865531645, MRd=113.359113136508,
         x=31.220796557414, z=194.511681377034, xcr=49.742080260301, sigma_s=391.787371324253,
         hceff=66.752639913233, rho=0.020080297458, c_eff=35.0, sr=254.456160734461, wk=0.407523105783, branch="7.11"),
    dict(id="R04", h=300.0, c=40.0, phi_this=16.0, phi_other=16.0, fck=40.0, M=150.0, phi=16.0, spacing=125.0,
         d=252.0, As_min=459.795941298497, As_req=1435.731243660127, As_bar=1608.495438637974, MRd=167.064816008003,
         x=32.781836385285, z=238.887265445886, xcr=59.327050718011, sigma_s=401.572285377314,
         hceff=80.22431642733, rho=0.020049973752, c_eff=40.0, sr=271.661025478015, wk=0.439548640539, branch="7.11"),
    dict(id="R05", h=250.0, c=30.0, phi_this=12.0, phi_other=16.0, fck=50.0, M=120.0, phi=12.0, spacing=125.0,
         d=214.0, As_min=453.090588562022, As_req=1344.837059639801, As_bar=904.77868423386, MRd=81.862514436342,
         x=14.751826373378, z=208.099269450649, xcr=40.984373549095, sigma_s=662.024979415807,
         hceff=69.671875483635, rho=0.012986282886, c_eff=30.0, sr=259.088831184133, wk=0.683831210462, branch="7.11"),
    dict(id="R06", h=250.0, c=30.0, phi_this=12.0, phi_other=12.0, fck=30.0, M=35.0, phi=12.0, spacing=150.0,
         d=214.0, As_min=322.318976156743, As_req=383.643981329244, As_bar=753.98223686155, MRd=67.466507872531,
         x=20.488647740803, z=205.804540903679, xcr=39.979047568464, sigma_s=231.321808058243,
         hceff=70.006984143845, rho=0.010770100242, c_eff=30.0, sr=291.413278816632, wk=0.202230739644, branch="7.11"),
    dict(id="R07", h=200.0, c=35.0, phi_this=10.0, phi_other=10.0, fck=30.0, M=20.0, phi=10.0, spacing=100.0,
         d=160.0, As_min=240.986150397565, As_req=293.345911960881, As_bar=785.398163397448, MRd=51.721222543206,
         x=21.34234139667, z=151.463063441332, xcr=34.632829055102, sigma_s=171.531216640935,
         hceff=55.122390314966, rho=0.014248260261, c_eff=35.0, sr=238.31281215388, wk=0.12263425983, branch="7.11"),
    dict(id="R08", h=300.0, c=40.0, phi_this=16.0, phi_other=12.0, fck=40.0, M=50.0, phi=16.0, spacing=400.0,
         d=252.0, As_min=459.795941298497, As_req=463.292795050878, As_bar=502.654824574367, MRd=54.177944463285,
         x=10.244323870401, z=247.902270451839, xcr=150.0, sigma_s=12.871305595434,
         hceff=0.0, rho=0.0, c_eff=40.0, sr=0.0, wk=0.0, branch="não fendilhada"),
    dict(id="R09", h=300.0, c=40.0, phi_this=16.0, phi_other=12.0, fck=40.0, M=80.0, phi=16.0, spacing=400.0,
         d=252.0, As_min=459.795941298497, As_req=748.271782041479, As_bar=502.654824574367, MRd=54.177944463285,
         x=10.244323870401, z=247.902270451839, xcr=35.181590887837, sigma_s=662.392668166983,
         hceff=88.272803037388, rho=0.005694334011, c_eff=40.0, sr=344.263931845813, wk=0.702203106872, branch="7.14"),
]


def _rel_close(a: float, b: float, rel: float = 2e-8, abs_tol: float = 2e-8) -> bool:
    return abs(a - b) <= max(abs_tol, rel * max(abs(a), abs(b), 1.0))


def _concrete_class(fck: float) -> str:
    mapping = {20: "C20/25", 25: "C25/30", 30: "C30/37", 35: "C35/45", 40: "C40/50", 45: "C45/55", 50: "C50/60"}
    return mapping[int(round(fck))]


def run_manual_reference_validation() -> str:
    rows = []
    n_checks = 0
    failures = []
    fields = [
        ("d", "d"), ("As_min", "As_min"), ("As_req", "As_req"), ("As_bar", "As_bar"),
        ("MRd", "MRd"), ("x", "x"), ("z", "z"), ("xcr", "xcr"), ("sigma_s", "sigma_s"),
        ("hceff", "hceff"), ("rho", "rho"), ("c_eff", "c_eff"), ("sr", "sr"), ("wk", "wk"),
    ]

    for ref in REFERENCE_CASES:
        dsg = SlabDesigner(
            ref["h"], ref["c"], _concrete_class(ref["fck"]), 500.0,
            uls_cases="101", qp_cases="301", wk_check_enabled=True,
            phi_min_mm=8, phi_max_mm=25, optimize_rebar=False,
        )
        d = dsg.layer_effective_depth("sup", "X", ref["phi_this"], ref["phi_other"])
        as_min = dsg.slab_flexural_min_for_d(d)
        as_req = dsg.flexural_as_required(ref["M"], d_mm=d)
        sol = dsg.rebar_from_phi_spacing(ref["phi"], ref["spacing"])
        mrd, x, z, _xd = dsg.flexural_metrics(sol.as_prov, d)
        cr = dsg.cracked_section_service_state(ref["M"], sol, d_mm=d)
        calc = dict(
            d=d, As_min=as_min, As_req=as_req, As_bar=sol.as_prov, MRd=mrd, x=x, z=z,
            xcr=cr["x_cr_mm"], sigma_s=cr["sigma_s_MPa"], hceff=cr["h_ceff_mm"],
            rho=cr["rho_p_eff"], c_eff=cr["c_eff_mm"], sr=cr["sr_max_mm"], wk=cr["wk_mm"],
        )
        case_ok = True
        for calc_key, ref_key in fields:
            n_checks += 1
            if not _rel_close(float(calc[calc_key]), float(ref[ref_key])):
                case_ok = False
                failures.append(
                    f"{ref['id']} {calc_key}: calc={calc[calc_key]:.12g}; referência={ref[ref_key]:.12g}"
                )
        # Teste explícito da transição não fendilhada e do ramo de sr,max.
        # Mcr é reconstruído aqui, sem chamar a rotina de fendilhação do núcleo.
        fctm_ref = 0.3 * float(ref["fck"]) ** (2.0 / 3.0)
        mcr_ref = fctm_ref * (1000.0 * float(ref["h"]) ** 2 / 6.0) / 1e6
        threshold = 5.0 * (calc["c_eff"] + ref["phi"] / 2.0)
        if float(ref["M"]) <= mcr_ref + 1e-9:
            branch = "não fendilhada"
        else:
            branch = "7.11" if ref["spacing"] <= threshold + 1e-9 else "7.14"
        n_checks += 1
        if branch != ref["branch"]:
            case_ok = False
            failures.append(f"{ref['id']} ramo sr,max: calc={branch}; referência={ref['branch']}")
        rows.append((ref["id"], "OK" if case_ok else "FALHA", calc["As_req"], calc["MRd"], calc["wk"], branch))

    # Caso independente de diâmetro equivalente, expressão EC2 7.12.
    dsg = SlabDesigner(250, 30, "C30/37", 500, uls_cases="101", qp_cases="301", wk_check_enabled=True,
                       phi_min_mm=8, phi_max_mm=16)
    comp = dsg.rebar_from_phi_spacing(10, 200)
    comp.base_text = "Ø10//200"
    comp.add_text = "Ø8//200"
    comp.text_override = "Ø10//200 + Ø8//200"
    phi_eq, s_eff, n_fam = dsg.rebar_crack_geometry(comp)
    phi_ref = (10.0**2 + 8.0**2) / (10.0 + 8.0)
    n_checks += 3
    if not _rel_close(phi_eq, phi_ref, rel=1e-12, abs_tol=1e-12):
        failures.append(f"REQ phi_eq: calc={phi_eq:.12g}; referência={phi_ref:.12g}")
    if not _rel_close(s_eff, 100.0, rel=1e-12, abs_tol=1e-12):
        failures.append(f"REQ s_eff: calc={s_eff:.12g}; referência=100")
    if n_fam != 2:
        failures.append(f"REQ n_fam: calc={n_fam}; referência=2")

    if failures:
        raise AssertionError("Validação independente falhou:\n" + "\n".join(failures))

    lines = [
        "SlabsEC2 — Campanha de validação independente bloqueada",
        f"Resultado: {n_checks}/{n_checks} comparações concluídas sem desvios fora da tolerância.",
        "Base: valores de referência numéricos fixos, não calculados por funções do núcleo em tempo de execução.",
        "Âmbito: flexão ELU + transição não fendilhada/fendilhada + fendilhação ELS-QP para faixa rectangular de 1 m, C25/30 a C50/60.",
        "",
        "Caso | Estado | As,req [mm²/m] | MRd [kNm/m] | wk [mm] | ramo sr,max",
    ]
    for cid, st, asr, mrd, wk, branch in rows:
        lines.append(f"{cid:>4} | {st:>6} | {asr:>14.3f} | {mrd:>12.3f} | {wk:>7.4f} | {branch}")
    lines += [
        "",
        f"REQ  |     OK | phi_eq={phi_eq:.6f} mm | s_eff={s_eff:.1f} mm | n_fam={n_fam}",
        "",
        "Nota: esta validação reduz o risco de regressões e de auto-confirmação do código, mas não constitui certificação externa.",
    ]
    return "\n".join(lines)
