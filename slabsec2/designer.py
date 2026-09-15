# -*- coding: utf-8 -*-
import math
import re
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .models import RebarSolution
from .utils import (
    normalize_text, safe_float, bar_area_mm2, parse_strength_from_class, concrete_props, steel_fyd,
    moment_unit_factor_to_kNm_per_m, shear_unit_factor_to_kN_per_m,
    displacement_unit_factor_to_mm
)
from .importers import canonical_case_id
from .combinations import parse_case_spec, format_case_ids, find_overlaps, CombinationSpecError
from .peaks import canonical_node_id, parse_node_spec, assess_panel_peak
from .validation import audit_design_results

LARGE_DATASET_THRESHOLD = 100000
# Em datasets muito grandes, estes textos repetitivos não são necessários linha a linha.
# Continuam disponíveis nos resumos, diagnósticos, notas normativas e linhas governantes.
LARGE_VERBOSE_RESULT_COLUMNS = {
    "Deflection_note", "Transverse_links_note", "d_calculation_mode", "Layer_order_mode",
    "Bottom_outer_axis", "Top_outer_axis", "Panel_solution_mode",
    "X+_constructability_note", "X-_constructability_note", "Y+_constructability_note", "Y-_constructability_note",
    "X+_optimization", "X-_optimization", "Y+_optimization", "Y-_optimization",
    "Crack_reason_x+", "Crack_reason_x-", "Crack_reason_y+", "Crack_reason_y-",
    "Crack_control_note", "ELS_wk_note", "ELS_stress_note",
    "Moment_sign_convention", "Cross_panel_harmonization_note",
}
from .limit_states import concrete_block_parameters, singly_reinforced_limit, flexural_state, service_stress_limits

class SlabDesigner:
    def __init__(
        self,
        thickness_mm: float,
        cover_mm: float,
        concrete_class: str,
        fyk: float,
        gamma_c: float = 1.5,
        gamma_s: float = 1.15,
        alpha_cc: float = 1.0,
        local_y_is_vertical: bool = True,
        aggregate_mm: float = 20.0,
        crack_spacing_limit_mm: Optional[float] = None,
        wood_armer_method: str = "Wood-Armer ortogonal optimizado",
        swap_local_axes: bool = False,
        crack_check_enabled: bool = True,
        wk_check_enabled: bool = False,
        qp_case: str = "",  # compatibilidade com configurações v2.2
        qp_cases: str = "",
        frequent_cases: str = "",
        characteristic_cases: str = "",
        moment_unit: str = "kNm/m",
        shear_unit: str = "kN/m",
        membrane_unit: str = "kN/m",
        combo_type: str = "ELU",
        wmax_mm: float = 0.30,
        phi_min_mm: float = 10.0,
        phi_max_mm: float = 32.0,
        optimize_rebar: bool = False,
        rebar_strategy: str = "Base + reforços",
        base_vertical_phi: float = 12.0,
        base_vertical_spacing: float = 200.0,
        base_horizontal_phi: float = 12.0,
        base_horizontal_spacing: float = 200.0,
        span_x_m: float = 0.0,
        span_y_m: float = 0.0,
        deflection_unit: str = "cm",
        deflection_limit: str = "Informativo",
        negative_z_is_down: bool = True,
        bottom_outer_axis: str = "X",
        top_outer_axis: str = "X",
        positive_moment_face: str = "Superior",
        uls_cases: str = "",
        peak_ratio_threshold: float = 1.50,
        singular_nodes: str = "",
        distributed_peak_policy: str = "P99 nodal + RAW local",
        distributed_peak_percentile: float = 0.99,
        auto_peak_ratio_p99_threshold: float = 1.20,
        auto_peak_max_fraction: float = 0.01,
        stress_check_enabled: bool = True,
        stress_k1: float = 0.60,
        stress_k2: float = 0.45,
        stress_k3: float = 0.80,
    ):
        self.t = float(thickness_mm)
        self.cover = float(cover_mm)
        self.gamma_c = float(gamma_c)
        self.gamma_s = float(gamma_s)
        self.alpha_cc = float(alpha_cc)
        self.aggregate_mm = float(aggregate_mm)
        if self.gamma_c <= 0.0 or self.gamma_s <= 0.0:
            raise ValueError("Os coeficientes parciais γc e γs devem ser positivos.")
        if not (0.80 <= self.alpha_cc <= 1.00):
            raise ValueError("αcc deve estar entre 0,80 e 1,00 para o âmbito configurável desta versão.")
        if self.aggregate_mm <= 0.0:
            raise ValueError("A dimensão máxima do agregado dg deve ser positiva.")
        self.fck = parse_strength_from_class(concrete_class, 30.0)
        self.cp = concrete_props(self.fck, alpha_cc=self.alpha_cc, gamma_c=self.gamma_c)
        self.fyd = steel_fyd(fyk, self.gamma_s)
        self.fyk = fyk
        self.local_y_is_vertical = local_y_is_vertical
        self.crack_spacing_limit_mm = crack_spacing_limit_mm
        self.wood_armer_method = wood_armer_method
        self.swap_local_axes = swap_local_axes
        self.crack_check_enabled = crack_check_enabled
        self.wk_check_enabled = wk_check_enabled
        # Classificação explícita de combinações. O parâmetro qp_case é mantido apenas
        # para compatibilidade com configurações anteriores; qp_cases tem prioridade.
        self.qp_cases_text = str(qp_cases or qp_case or "").strip()
        self.frequent_cases_text = str(frequent_cases or "").strip()
        self.characteristic_cases_text = str(characteristic_cases or "").strip()
        self.qp_case_ids = set(parse_case_spec(self.qp_cases_text))
        self.frequent_case_ids = set(parse_case_spec(self.frequent_cases_text))
        self.characteristic_case_ids = set(parse_case_spec(self.characteristic_cases_text))
        # Alias apenas para compatibilidade de leitura interna/relatórios antigos.
        self.qp_case = format_case_ids(self.qp_case_ids)
        self.moment_unit = moment_unit
        self.shear_unit = shear_unit
        self.membrane_unit = membrane_unit
        self.moment_factor = moment_unit_factor_to_kNm_per_m(moment_unit)
        self.shear_factor = shear_unit_factor_to_kN_per_m(shear_unit)
        self.membrane_factor = shear_unit_factor_to_kN_per_m(membrane_unit)
        self.combo_type = combo_type
        self.wmax_mm = wmax_mm
        self.phi_min_mm = float(phi_min_mm)
        self.phi_max_mm = float(phi_max_mm)
        if self.phi_min_mm > self.phi_max_mm:
            raise ValueError(f"Intervalo de diâmetros inválido: Ømin={self.phi_min_mm:g} mm > Ømax={self.phi_max_mm:g} mm.")
        # Grelha construtiva fechada definida para o projecto SlabsEC2. Não são gerados
        # diâmetros/espaçamentos fora desta lista por conveniência do optimizador.
        self.allowed_phi_candidates = [10.0, 12.0, 16.0, 20.0, 25.0, 32.0]
        self.allowed_spacing_candidates = [100.0, 125.0, 150.0, 175.0, 200.0]
        self.phi_candidates = [p for p in self.allowed_phi_candidates if self.phi_min_mm <= p <= self.phi_max_mm]
        if not self.phi_candidates:
            raise ValueError(
                f"O intervalo Ø{self.phi_min_mm:g}–Ø{self.phi_max_mm:g} mm não contém nenhum dos diâmetros disponíveis "
                "(10, 12, 16, 20, 25, 32 mm)."
            )
        self.preferred_spacing_candidates = list(self.allowed_spacing_candidates)
        self.fallback_spacing_candidates = []
        self.spacing_candidates = list(self.allowed_spacing_candidates)
        self.optimize_rebar = bool(optimize_rebar)
        self.rebar_strategy = str(rebar_strategy)
        self.base_vertical_phi = float(base_vertical_phi)
        self.base_vertical_spacing = float(base_vertical_spacing)
        self.base_horizontal_phi = float(base_horizontal_phi)
        self.base_horizontal_spacing = float(base_horizontal_spacing)
        self.span_x_m = max(0.0, float(span_x_m or 0.0))
        self.span_y_m = max(0.0, float(span_y_m or 0.0))
        self.deflection_unit = str(deflection_unit or "cm")
        self.deflection_factor = displacement_unit_factor_to_mm(self.deflection_unit)
        self.deflection_limit = "Informativo"
        self.deflection_denominator = 0.0
        self.negative_z_is_down = bool(negative_z_is_down)
        self.bottom_outer_axis = str(bottom_outer_axis or "X").upper()[:1] if str(bottom_outer_axis or "X").upper()[:1] in ("X", "Y") else "X"
        self.top_outer_axis = str(top_outer_axis or "X").upper()[:1] if str(top_outer_axis or "X").upper()[:1] in ("X", "Y") else "X"
        _pf = normalize_text(str(positive_moment_face or "Superior"))
        self.positive_moment_face = "Inferior" if ("infer" in _pf or "bottom" in _pf) else "Superior"
        self.uls_cases_text = str(uls_cases or "").strip()
        self.uls_case_ids = set(parse_case_spec(self.uls_cases_text))
        self.peak_ratio_threshold = max(1.01, float(peak_ratio_threshold or 1.50))
        self.singular_nodes_text = str(singular_nodes or "").strip()
        self.singular_node_ids = set(parse_node_spec(self.singular_nodes_text))
        self.distributed_peak_policy = str(distributed_peak_policy or "RAW integral").strip()
        self.distributed_peak_percentile = min(0.999, max(0.95, float(distributed_peak_percentile or 0.99)))
        self.auto_peak_ratio_p99_threshold = max(1.01, float(auto_peak_ratio_p99_threshold or 1.20))
        self.auto_peak_max_fraction = min(0.05, max(0.001, float(auto_peak_max_fraction or 0.01)))
        self._auto_peak_panel_info = {}
        self.stress_check_enabled = bool(stress_check_enabled)
        self.stress_k1 = float(stress_k1)
        self.stress_k2 = float(stress_k2)
        self.stress_k3 = float(stress_k3)
        if min(self.stress_k1, self.stress_k2, self.stress_k3) <= 0.0:
            raise ValueError("Os coeficientes de limitação de tensões k1, k2 e k3 devem ser positivos.")
        self.stress_limits = service_stress_limits(self.fck, self.fyk, self.stress_k1, self.stress_k2, self.stress_k3)
        # Caches de desempenho. Em resultados FEM extensos, as mesmas quatro soluções de
        # armadura de um painel são consultadas centenas de milhares de vezes.
        self._case_class_cache = {}
        self._rebar_parse_cache = {}
        self._rebar_crack_geom_cache = {}
        self._rebar_layer_geom_cache = {}
        self._uls_cases_label = format_case_ids(self.uls_case_ids)
        self._qp_cases_label = format_case_ids(self.qp_case_ids)
        self._freq_cases_label = format_case_ids(self.frequent_case_ids)
        self._char_cases_label = format_case_ids(self.characteristic_case_ids)
        overlaps = find_overlaps(
            self.uls_case_ids, self.qp_case_ids, self.frequent_case_ids, self.characteristic_case_ids
        )
        if overlaps:
            raise CombinationSpecError(
                "As mesmas combinações foram atribuídas a mais do que uma classe: "
                + format_case_ids(overlaps)
                + ". Cada combinação deve pertencer a uma única classe."
            )

    @property
    def ac_per_m(self) -> float:
        return 1000.0 * self.t

    def min_slab_reinf_limits(self, phi: float = 12.0) -> Tuple[float, float, float]:
        """Retorna As,min principal, As,min secundária e As,max por metro de laje.

        Critérios adoptados nesta versão:
        - As,min de flexão por faixa de 1 m, compatível com EC2 9.3.1.1;
        - As,sec,min >= 20% da armadura principal mínima, aplicável quando a direcção é apenas secundária;
        - As,max = 0,04 Ac por metro, usado como limite construtivo/preliminar.
        """
        as_main_min = self.slab_flexural_min_per_face(phi)
        as_secondary_min = 0.20 * as_main_min
        as_max = 0.04 * self.ac_per_m
        return as_main_min, as_secondary_min, as_max

    def slab_flexural_min_for_d(self, d_mm: float) -> float:
        """Armadura mínima de flexão para a profundidade útil física fornecida."""
        d = max(float(d_mm), 1.0)
        return max(0.26 * self.cp["fctm"] / self.fyk * 1000.0 * d, 0.0013 * 1000.0 * d)

    def slab_flexural_min_per_face(self, phi: float = 12.0) -> float:
        """Mínimo de flexão tipo laje/faixa de 1 m para a malha exterior simples."""
        return self.slab_flexural_min_for_d(self.effective_depth(phi))

    def max_spacing_for_direction(self, is_main_direction: bool) -> float:
        """Espaçamento máximo para armadura de lajes maciças.

        EC2 9.3.1.1: armadura principal <= min(3h, 400 mm);
        armadura secundária <= min(3,5h, 450 mm).
        Em zonas condicionantes ou quando o utilizador activa o controlo adicional,
        o valor pode ser limitado a 250 mm.
        """
        if is_main_direction:
            base = min(3.0 * self.t, 400.0)
        else:
            base = min(3.5 * self.t, 450.0)
        if self.crack_spacing_limit_mm and self.crack_spacing_limit_mm > 0:
            base = min(base, self.crack_spacing_limit_mm)
        return base

    def effective_depth(self, phi: float = 12.0) -> float:
        # Profundidade útil simples, mantida para mínimos e compatibilidade interna.
        return max(self.t - self.cover - phi / 2.0, 1.0)

    def layer_effective_depth(self, face: str, direction: str, phi_this: float = 12.0, phi_other: float = 12.0, outer_axis: Optional[str] = None) -> float:
        """Profundidade útil com a ordem física das camadas X/Y.

        ``outer_axis`` identifica a malha mais próxima da face de betão considerada. Se omitido,
        usa ``top_outer_axis`` na face superior e ``bottom_outer_axis`` na face inferior.
        A direção exterior tem o centróide a ``c_nom + phi/2``; a direção interior é deslocada
        pela espessura da malha ortogonal exterior.
        """
        phi_this = max(float(phi_this or 0.0), 0.0)
        phi_other = max(float(phi_other or phi_this), 0.0)
        f = normalize_text(str(face))
        default_outer = self.top_outer_axis if ("sup" in f or "top" in f or f == "+") else self.bottom_outer_axis
        oa = str(outer_axis or default_outer).upper()[:1]
        if oa not in ("X", "Y"):
            oa = default_outer
        direction = str(direction or "X").upper()[:1]
        if direction == oa:
            cover_to_centroid = self.cover + phi_this / 2.0
        else:
            cover_to_centroid = self.cover + phi_other + phi_this / 2.0
        return max(self.t - cover_to_centroid, 1.0)

    def classify_case(self, case_value: object) -> str:
        """Classifica explicitamente um caso, com cache para grandes tabelas."""
        key = str(case_value)
        cached = self._case_class_cache.get(key)
        if cached is not None:
            return cached
        cid = canonical_case_id(case_value)
        if not cid:
            out = "Outro"
        elif cid in self.uls_case_ids:
            out = "ELU"
        elif cid in self.qp_case_ids:
            out = "ELS-QP"
        elif cid in self.frequent_case_ids:
            out = "ELS-FREQ"
        elif cid in self.characteristic_case_ids:
            out = "ELS-CHAR"
        else:
            out = "Outro"
        self._case_class_cache[key] = out
        return out

    def is_uls_case(self, case_value: object) -> bool:
        return self.classify_case(case_value) == "ELU"

    def effective_span_mm(self) -> float:
        return 0.0

    def deflection_limit_mm(self) -> float:
        return 0.0

    def evaluate_deflection(self, ugz_raw: float) -> Dict[str, object]:
        ugz_mm = ugz_raw * self.deflection_factor
        if self.negative_z_is_down:
            down_mm = max(0.0, -ugz_mm)
            direction_note = "UGZ negativo considerado como deslocamento para baixo"
        else:
            down_mm = max(0.0, ugz_mm)
            direction_note = "UGZ positivo considerado como deslocamento para baixo"
        if abs(ugz_mm) <= 1e-12:
            return {"UGZ_mm": ugz_mm, "UGZ_down_mm": down_mm, "Deflection_limit_mm": 0.0, "util_deflection": 0.0, "Deflection_status": "Não avaliado", "Deflection_note": "UGZ inexistente ou nulo"}
        return {"UGZ_mm": ugz_mm, "UGZ_down_mm": down_mm, "Deflection_limit_mm": 0.0, "util_deflection": 0.0, "Deflection_status": "Informativo", "Deflection_note": f"{direction_note}; UGZ é apresentado apenas como diagnóstico importado do modelo FEM"}

    def flexural_as_required(self, m_ed_kNm_per_m: float, phi_assumed: float = 12.0, d_mm: Optional[float] = None) -> float:
        """As requerido por metro por compatibilidade de extensões.

        Resolve primeiro a profundidade do eixo neutro a partir do equilíbrio de momentos
        do bloco comprimido e depois calcula a tensão efectiva do aço. Ao contrário da
        v2.15.0, o cálculo não é truncado no ponto eps_s=eps_yd: se o aço não atingir fyd,
        usa-se sigma_s=Es*eps_s, coerentemente com EC2 6.1/3.2.7.
        """
        m = abs(float(m_ed_kNm_per_m)) * 1e6
        if m <= 1e-9:
            return 0.0
        d = float(d_mm) if d_mm and d_mm > 0 else self.effective_depth(phi_assumed)
        fcd = self.cp["fcd"]
        b = 1000.0
        if fcd <= 0 or self.fyd <= 0 or d <= 0:
            return 0.0
        p = concrete_block_parameters(self.fck)
        A = p["eta"] * p["lambda"] * b * fcd
        # M = A*x*(d - 0.5*lambda*x). A menor raiz corresponde ao ramo físico.
        disc = d * d - 2.0 * p["lambda"] * m / max(A, 1e-12)
        if disc <= 0.0:
            # Acima da capacidade assintótica deste modelo simplesmente armado.
            return float("inf")
        x = (d - math.sqrt(disc)) / max(p["lambda"], 1e-12)
        if x <= 1e-12 or x >= d:
            return float("inf")
        eps_s = p["eps_cu3"] * (d - x) / x
        sigma_s = min(self.fyd, 200000.0 * eps_s)
        if sigma_s <= 1e-9:
            return float("inf")
        c_force = A * x
        return c_force / sigma_s

    def flexural_section_state(self, as_mm2_per_m: float, d_mm: float) -> Dict[str, object]:
        if not hasattr(self, "_flexural_state_cache"):
            self._flexural_state_cache = {}
        key = (round(float(as_mm2_per_m), 9), round(float(d_mm), 9))
        st = self._flexural_state_cache.get(key)
        if st is None:
            st = flexural_state(as_mm2_per_m, d_mm, self.fck, self.cp["fcd"], self.fyd)
            self._flexural_state_cache[key] = st
        return st

    def flexural_metrics(self, as_mm2_per_m: float, d_mm: float) -> Tuple[float, float, float, float]:
        """Retorna MRd válido [kNm/m], x [mm], z [mm] e x/d.

        A resistência não é creditada acima do limite de validade da hipótese de secção
        simplesmente armada com aço traccionado a fyd.
        """
        st = self.flexural_section_state(as_mm2_per_m, d_mm)
        return float(st["MRd_kNm_m"]), float(st["x_mm"]), float(st["z_mm"]), float(st["x_d"])

    def mrd_kNm_per_m(self, as_mm2_per_m: float, phi: float, d_mm: Optional[float] = None) -> float:
        d = float(d_mm) if d_mm and d_mm > 0 else self.effective_depth(phi)
        return self.flexural_metrics(as_mm2_per_m, d)[0]

    def choose_rebar(self, as_req_per_face: float, max_spacing: float = 400.0) -> RebarSolution:
        best = None
        for phi in self.phi_candidates:
            for s in self.spacing_candidates:
                if s > max_spacing + 1e-9:
                    continue
                clear = s - phi
                min_clear = max(phi, self.aggregate_mm + 5.0, 20.0)
                if clear < min_clear:
                    continue
                as_prov = bar_area_mm2(phi) * 1000.0 / s
                if as_prov + 1e-9 >= as_req_per_face:
                    cand = RebarSolution(phi=phi, spacing=s, as_prov=as_prov)
                    excess = cand.as_prov / max(as_req_per_face, 1.0)
                    # Engenharia prática: evita espaçamentos <100 mm, evita Ø20/Ø25 quando não necessários,
                    # e minimiza excesso de aço sem penalizar demasiado soluções correntes Ø10/Ø12.
                    penalty_spacing = 0 if cand.spacing in self.preferred_spacing_candidates else (20 if cand.spacing < 100.0 else 4)
                    penalty_large_phi = max(0.0, cand.phi - 16.0) / 10.0
                    penalty_preferred = 0 if cand.phi in (8.0, 10.0, 12.0, 16.0) else 1
                    # Segurança já foi satisfeita pelo filtro As>=Asreq; depois privilegia solução corrente
                    # e só então minimiza excesso de aço.
                    key = (penalty_spacing, penalty_preferred, penalty_large_phi, excess, cand.as_prov, cand.phi, -cand.spacing)
                    if best is None:
                        best = cand
                        best_key = key
                    elif key < best_key:
                        best = cand
                        best_key = key
        if best is None:
            # Não ultrapassar silenciosamente Ømax definido pelo utilizador.
            # Se nenhuma solução uniforme cumprir As,req, adopta-se apenas a maior capacidade
            # fisicamente admissível dentro dos limites configurados; a verificação ELU permanece
            # não conforme e o relatório identifica explicitamente o limite atingido.
            feasible = []
            for phi in self.phi_candidates:
                for s in self.spacing_candidates:
                    if s > max_spacing + 1e-9:
                        continue
                    clear = s - phi
                    min_clear = max(phi, self.aggregate_mm + 5.0, 20.0)
                    if clear < min_clear:
                        continue
                    as_prov = bar_area_mm2(phi) * 1000.0 / s
                    feasible.append((as_prov, phi, s))
            if not feasible:
                raise ValueError(
                    f"Não existe solução de armadura geometricamente admissível dentro de Ø{self.phi_min_mm:g}–Ø{self.phi_max_mm:g} mm "
                    f"e s≤{max_spacing:g} mm para os critérios de distância livre adoptados."
                )
            as_prov, phi, s = max(feasible, key=lambda x: (x[0], x[1], -x[2]))
            best = RebarSolution(
                phi, s, as_prov,
                capacity_limited=True,
                limit_note=(
                    f"Armadura uniforme insuficiente dentro dos limites configurados: As,req={as_req_per_face:.1f} mm²/m; "
                    f"capacidade máxima disponível={as_prov:.1f} mm²/m com Ø{int(phi)}//{int(s)}; "
                    f"Ømax={self.phi_max_mm:g} mm."
                )
            )
            best.optimization_note = "limite Ø/s configurado atingido; solução máxima admissível adoptada apenas para avaliação"
        return best

    def rebar_from_phi_spacing(self, phi: float, spacing: float) -> RebarSolution:
        phi = float(phi)
        spacing = float(spacing)
        if phi <= 0 or spacing <= 0:
            return RebarSolution(0.0, 1e9, 0.0, text_override="-")
        return RebarSolution(phi, spacing, bar_area_mm2(phi) * 1000.0 / spacing)

    def base_solution_for_direction(self, is_vertical_direction: bool) -> RebarSolution:
        if is_vertical_direction:
            return self.rebar_from_phi_spacing(self.base_vertical_phi, self.base_vertical_spacing)
        return self.rebar_from_phi_spacing(self.base_horizontal_phi, self.base_horizontal_spacing)

    def base_solution_is_valid(self, sol: RebarSolution, max_spacing: float) -> Tuple[bool, str]:
        if sol.phi <= 0 or sol.spacing <= 0:
            return False, "armadura base não definida"
        if sol.phi not in self.allowed_phi_candidates:
            return False, f"diâmetro base Ø{sol.phi:g} mm fora da grelha permitida {self.allowed_phi_candidates}"
        if sol.phi < self.phi_min_mm - 1e-9 or sol.phi > self.phi_max_mm + 1e-9:
            return False, f"diâmetro base Ø{sol.phi:g} mm fora do intervalo configurado Ø{self.phi_min_mm:g}–Ø{self.phi_max_mm:g}"
        if sol.spacing not in self.allowed_spacing_candidates:
            return False, f"espaçamento base {sol.spacing:g} mm fora da grelha permitida {self.allowed_spacing_candidates}"
        if sol.spacing > max_spacing + 1e-9:
            return False, f"espaçamento base {sol.spacing:.0f} mm > smax {max_spacing:.0f} mm"
        clear = sol.spacing - sol.phi
        min_clear = max(sol.phi, self.aggregate_mm + 5.0, 20.0)
        if clear < min_clear:
            return False, f"distância livre base insuficiente ({clear:.0f} mm < {min_clear:.0f} mm)"
        return True, "armadura base válida"

    def choose_compatible_additional_rebar(self, deficit_as: float, base: RebarSolution, max_spacing: float) -> RebarSolution:
        """Escolhe UMA família de reforço adicional com a MESMA modulação da armadura base.

        Regras fail-safe da estratégia ``Base + reforços``:
        - nunca gera multiplicadores do tipo ``2Ø...``, ``3Ø...`` ou ``5Ø...``;
        - admite no máximo uma família adicional por face/direcção;
        - o reforço tem obrigatoriamente o mesmo espaçamento da armadura base;
        - a família adicional é entendida como intercalada/desfasada relativamente à base;
        - verifica a distância livre entre barras da base e do reforço na disposição intercalada;
        - se uma família adicional com essa modulação não cobrir o défice dentro de Ømin/Ømax,
          devolve a maior família admissível apenas para avaliação e marca ``capacity_limited``.

        Exemplos admissíveis: ``Ø10//200 + Ø12//200`` ou ``Ø10//200 + Ø16//200``.
        Exemplos que esta rotina não gera: ``Ø10//200 + Ø16//125`` ou ``Ø10//200 + 2Ø16//200``.
        """
        deficit_as = max(0.0, float(deficit_as))
        if deficit_as <= 1e-9:
            return RebarSolution(0.0, 1e9, 0.0, text_override="-")

        s = float(base.spacing)
        if s <= 0 or s > max_spacing + 1e-9:
            return RebarSolution(
                0.0, 1e9, 0.0, text_override="-", capacity_limited=True,
                limit_note=(
                    f"O espaçamento da armadura base ({s:.0f} mm) não é admissível para o reforço "
                    f"nesta direcção (smax={max_spacing:.0f} mm)."
                ),
            )

        candidates = []
        admissible = []
        for phi in sorted(self.phi_candidates):
            phi = float(phi)

            # Base e reforço têm a mesma modulação, ficando a família adicional intercalada.
            # A distância entre eixos de barras consecutivas passa a s/2.
            clear_interleaved = s / 2.0 - (float(base.phi) + phi) / 2.0
            min_clear = max(float(base.phi), phi, self.aggregate_mm + 5.0, 20.0)
            if clear_interleaved + 1e-9 < min_clear:
                continue

            as_add = bar_area_mm2(phi) * 1000.0 / s
            text = f"Ø{int(phi)}//{int(s)}"
            sol = RebarSolution(phi=phi, spacing=s, as_prov=as_add, text_override=text)
            admissible.append(sol)
            if as_add + 1e-9 < deficit_as:
                continue

            excess = as_add / max(deficit_as, 1.0)
            penalty_phi = 0 if phi <= 12.0 else (phi - 12.0) / 10.0
            candidates.append(((penalty_phi, excess, phi), sol))

        if candidates:
            candidates.sort(key=lambda x: x[0])
            return candidates[0][1]

        # Sem solução suficiente com o mesmo espaçamento: nunca alterar a modulação nem multiplicar famílias.
        if admissible:
            best = max(admissible, key=lambda x: (x.as_prov, x.phi))
            best.capacity_limited = True
            best.limit_note = (
                f"Estratégia Base + reforço simples insuficiente com s={s:.0f} mm: "
                f"défice={deficit_as:.1f} mm²/m; máximo reforço adicional admissível={best.as_prov:.1f} mm²/m "
                f"com {best.text}. O reforço deve manter o mesmo espaçamento da base. "
                f"Rever a estratégia (Substituir base), a armadura base, os limites de diâmetro, "
                f"a espessura ou o significado do esforço governante."
            )
            best.optimization_note = "limite da estratégia Base + reforço com mesma modulação atingido"
            return best

        return RebarSolution(
            0.0, 1e9, 0.0, text_override="-", capacity_limited=True,
            limit_note=(
                f"Não existe família de reforço admissível com o mesmo espaçamento da base ({s:.0f} mm) "
                f"dentro dos limites Ø configurados e da distância livre mínima."
            ),
        )

    def optimize_rebar_solution(self, as_req: float, max_spacing: float, is_vertical_direction: bool, label: str) -> RebarSolution:
        """Selecciona a solução resistente e aplica a estratégia construtiva configurada.

        Regra v2.14.1 para ``Base + reforços``: a armadura base definida pelo utilizador é
        invariável. O programa pode acrescentar, no máximo, uma família adicional com a mesma
        modulação, mas nunca substitui silenciosamente a base por uma malha uniforme. Se a base
        e a maior família adicional admissível não forem suficientes, a solução é marcada como
        limitada/não conforme e é sugerida a revisão da base ou dos limites de armadura.
        """
        full = self.choose_rebar(as_req, max_spacing=max_spacing)
        full.as_base = 0.0
        full.as_add = 0.0
        full.add_text = "-"
        full.minimum_valid_text = full.text
        full.optimization_note = "solução automática directa"
        full.n_iterations = 1
        full.constructability_status, full.constructability_note, full.reinforcement_ratio_add_base = self.review_solution_constructability(full)

        if not self.optimize_rebar:
            return full

        if "substituir" in normalize_text(self.rebar_strategy):
            full.optimization_note = f"estratégia substituir base: adoptada solução uniforme directa para {label}"
            return full

        base = self.base_solution_for_direction(is_vertical_direction)
        ok_base, base_note = self.base_solution_is_valid(base, max_spacing)
        if not ok_base:
            # Fail-safe: em Base + reforços uma base inválida não pode ser trocada automaticamente.
            sol = RebarSolution(
                base.phi, base.spacing, base.as_prov,
                text_override=base.text, base_text=base.text, add_text="-",
                as_base=base.as_prov, as_add=0.0, minimum_valid_text=full.text,
                optimization_note=f"base configurada inválida para {label}; não substituída automaticamente",
                n_iterations=0, capacity_limited=True,
                limit_note=f"Armadura base definida pelo utilizador não admissível: {base_note}. Rever a base.",
                constructability_status="Não conforme",
                constructability_note=f"Base + reforços exige preservar a base; {base_note}.",
            )
            return sol

        if base.as_prov + 1e-9 >= as_req:
            sol = RebarSolution(
                base.phi, base.spacing, base.as_prov,
                text_override=base.text, base_text=base.text, add_text="-",
                as_base=base.as_prov, as_add=0.0,
                minimum_valid_text=full.text,
                optimization_note=f"base suficiente para {label}", n_iterations=0,
            )
            sol.constructability_status, sol.constructability_note, sol.reinforcement_ratio_add_base = self.review_solution_constructability(sol)
            return sol

        deficit = max(0.0, as_req - base.as_prov)
        add = self.choose_compatible_additional_rebar(deficit, base, max_spacing=max_spacing)
        final_as = base.as_prov + add.as_prov
        text = f"{base.text} + {add.text}" if add.as_prov > 0 else base.text
        capacity_limited = bool(add.capacity_limited or final_as + 1e-9 < as_req)
        limit_note = add.limit_note
        ratio = add.as_prov / max(base.as_prov, 1e-12)

        if capacity_limited and not limit_note:
            limit_note = (
                f"Estratégia Base + reforço insuficiente para {label}: "
                f"As,req={as_req:.1f} mm²/m; As,prov={final_as:.1f} mm²/m. "
                "A base foi preservada; rever base, Ømáx, espessura ou o esforço governante."
            )

        sol = RebarSolution(
            max(base.phi, add.phi), base.spacing, final_as,
            text_override=text, base_text=base.text, add_text=add.text if add.as_prov > 0 else "-",
            as_base=base.as_prov, as_add=add.as_prov,
            minimum_valid_text=full.text,
            optimization_note=(
                f"base fixa preservada; uma única família de reforço com a mesma modulação adoptada para {label}"
                + ("; capacidade máxima da estratégia atingida" if capacity_limited else "")
            ),
            n_iterations=1, capacity_limited=capacity_limited, limit_note=limit_note,
        )
        sol.constructability_status, sol.constructability_note, sol.reinforcement_ratio_add_base = self.review_solution_constructability(sol)
        # Um reforço maior do que a base é permitido: continua a ser explicitamente base + reforço.
        sol.reinforcement_ratio_add_base = ratio
        return sol

    def shear_vrdc_kN_per_m(self, as_l_per_m: float, d_mm: float) -> float:
        fck = self.fck
        # EC2 6.2.2: C_Rd,c = 0,18/γc. Desde v2.13, γc é o valor configurado
        # no objecto de cálculo, evitando a inconsistência anterior com γc=1,50 fixo.
        crdc = 0.18 / self.gamma_c
        k = min(2.0, 1.0 + math.sqrt(200.0 / d_mm)) if d_mm > 0 else 2.0
        rho_l = min(0.02, max(0.0, as_l_per_m / (1000.0 * d_mm))) if d_mm > 0 else 0.0
        vrdc = crdc * k * (100.0 * rho_l * fck) ** (1.0 / 3.0) if rho_l > 0 else 0.0
        vmin = 0.035 * k ** 1.5 * math.sqrt(fck)
        vrdc = max(vrdc, vmin)  # MPa = N/mm2
        return vrdc * d_mm  # N/mm = kN/m

    def shear_vrdmax_kN_per_m(self, d_mm: float, cot_theta: float = 2.5) -> float:
        """Limite superior simplificado de esmagamento da biela comprimida, por metro."""
        if d_mm <= 0:
            return 0.0
        fcd = self.cp["fcd"]
        nu1 = 0.6 * (1.0 - self.fck / 250.0)
        z = 0.9 * d_mm
        tan_theta = 1.0 / cot_theta
        # N/mm = kN/m, para bw = 1000 mm
        return 1000.0 * z * nu1 * fcd / (cot_theta + tan_theta) / 1000.0

    def wood_armer_detail(self, mxx: float, myy: float, mxy: float) -> Dict[str, float]:
        """Wood-Armer ortogonal optimizado para momentos RAW de placa.

        Para cada sinal de flexão aplica-se o ramo clássico. O ramo negativo é obtido
        aplicando a mesma transformação a ``(-Mxx, -Myy, Mxy)``. Quando a soma simples
        com ``|Mxy|`` tornaria uma das direções negativa, essa direção é anulada e a outra
        recebe a correção ``Mxy²/M``.
        """
        def branch(mx: float, my: float, txy: float):
            a = abs(float(txy))
            x = float(mx) + a
            y = float(my) + a
            eps = 1e-12
            if x < 0.0:
                # mx é necessariamente negativo neste ramo; a direção X não necessita armadura.
                x = 0.0
                y = max(0.0, float(my) - (float(txy) ** 2) / float(mx)) if abs(float(mx)) > eps else max(0.0, y)
            elif y < 0.0:
                y = 0.0
                x = max(0.0, float(mx) - (float(txy) ** 2) / float(my)) if abs(float(my)) > eps else max(0.0, x)
            else:
                x = max(0.0, x); y = max(0.0, y)
            return x, y

        xp, yp = branch(mxx, myy, mxy)
        xn, yn = branch(-mxx, -myy, mxy)
        dxp, dxn = max(0.0, mxx), max(0.0, -mxx)
        dyp, dyn = max(0.0, myy), max(0.0, -myy)
        return {
            "X+": xp, "X-": xn, "Y+": yp, "Y-": yn,
            "X+_direct": dxp, "X-_direct": dxn, "Y+_direct": dyp, "Y-_direct": dyn,
            "X+_mxy": max(0.0, xp - dxp), "X-_mxy": max(0.0, xn - dxn),
            "Y+_mxy": max(0.0, yp - dyp), "Y-_mxy": max(0.0, yn - dyn),
            "method": "Wood-Armer ortogonal optimizado",
        }

    def wood_armer_moments(self, mxx: float, myy: float, mxy: float) -> Tuple[float, float, float, float, str]:
        d = self.wood_armer_detail(mxx, myy, mxy)
        return d["X+"], d["X-"], d["Y+"], d["Y-"], str(d["method"])

    def crack_simplified_status(self, sol: RebarSolution) -> Tuple[str, str]:
        # Controlo sempre activo quando wk não é seleccionado.
        # Usa espaçamento efectivo quando existe reforço intercalado.
        phi_ctrl, s_eff, _ = self.rebar_crack_geometry(sol)
        if s_eff <= 200.0 and phi_ctrl <= 12.0:
            return "OK", "controlo simplificado: Ø≤12 e s_ef≤200 mm"
        if s_eff <= 250.0 and phi_ctrl <= 16.0:
            return "OK*", "controlo simplificado preliminar: Ø≤16 e s_ef≤250 mm; confirmar por ELS se condicionante"
        return "Verificar", "diâmetro/espaçamento efectivo elevado; recomenda-se verificação wk com combinação quase-permanente"

    def crack_min_as_per_face(self, sigma_s_lim: float = 500.0) -> float:
        """Armadura mínima para controlo da fendilhação, EC2 7.3.2, faixa de 1 m.

        Para flexão simples de uma secção rectangular sem esforço normal significativo adopta-se
        kc=0,40. Para a zona traccionada imediatamente antes da fendilhação considera-se Act=b*h/2.
        O coeficiente k é 1,0 para h<=300 mm, 0,65 para h>=800 mm e interpolado linearmente
        entre estes limites. fct,eff=fctm salvo indicação específica de idade de fendilhação.
        """
        kc = 0.40
        if self.t <= 300.0:
            k = 1.00
        elif self.t >= 800.0:
            k = 0.65
        else:
            k = 1.00 - (self.t - 300.0) * (1.00 - 0.65) / 500.0
        fct_eff = self.cp["fctm"]
        act = 1000.0 * self.t / 2.0
        return kc * k * fct_eff * act / max(float(sigma_s_lim), 1.0)

    def _parse_rebar_text(self, txt: str) -> List[Tuple[int, float, float]]:
        """Extrai famílias de armadura, usando cache por texto normalizado."""
        key = str(txt or "")
        if key in self._rebar_parse_cache:
            return self._rebar_parse_cache[key]
        out = []
        for part in key.replace("phi", "Ø").split("+"):
            p = part.strip().replace(" ", "")
            if not p or p == "-":
                continue
            m = re.search(r"(?:(\d+)Ø)?(\d+(?:[.,]\d+)?)//(\d+(?:[.,]\d+)?)", p)
            if not m:
                m = re.search(r"(\d+)?\s*[Øø]\s*(\d+(?:[.,]\d+)?)\s*/{2,3}\s*(\d+(?:[.,]\d+)?)", p)
            if m:
                n = int(m.group(1)) if m.group(1) else 1
                phi = float(m.group(2).replace(",", "."))
                s = float(m.group(3).replace(",", "."))
                out.append((max(1, n), phi, s))
        self._rebar_parse_cache[key] = out
        return out

    def rebar_crack_geometry(self, sol: RebarSolution) -> Tuple[float, float, int]:
        key = (str(sol.text or ""), str(sol.base_text or ""), str(sol.add_text or ""),
               float(sol.phi or 0.0), float(sol.spacing or 0.0))
        val = self._rebar_crack_geom_cache.get(key)
        if val is None:
            val = self._rebar_crack_geometry_uncached(sol)
            self._rebar_crack_geom_cache[key] = val
        return val

    def _rebar_crack_geometry_uncached(self, sol: RebarSolution) -> Tuple[float, float, int]:
        """Retorna Ø equivalente, espaçamento efectivo e nº de famílias para fendilhação.

        Para famílias de diâmetros diferentes aplica-se o diâmetro equivalente do EC2 7.3.4(3):
        phi_eq = sum(n_i*phi_i^2) / sum(n_i*phi_i).

        Para base + reforços com o mesmo espaçamento, considera-se intercalamento geométrico:
        Ø10//200 + Ø8//200 -> s_eff ≈ 100 mm.
        """
        families = []
        if sol.base_text:
            families.extend(self._parse_rebar_text(sol.base_text))
        if sol.add_text and sol.add_text != "-":
            families.extend(self._parse_rebar_text(sol.add_text))
        if not families:
            families.extend(self._parse_rebar_text(sol.text))
        if not families:
            return sol.phi, sol.spacing, 1

        # Para famílias com espaçamentos diferentes, n_i deve representar a quantidade de
        # varões por unidade de largura, não apenas o número de famílias textuais.
        # Usa-se densidade de barras (multiplicidade/s) na expressão de phi_eq.
        weighted = [(max(1, n) / max(float(s), 1e-9), phi, float(s)) for n, phi, s in families if s > 0]
        den = sum(dens * phi for dens, phi, _s in weighted)
        num = sum(dens * phi * phi for dens, phi, _s in weighted)
        phi_eq = num / den if den > 1e-12 else max(phi for _n, phi, _s in families)

        spacings = [s for _n, _phi, s in families if s > 0]
        n_fam = sum(max(1, n) for n, _phi, _s in families)
        if spacings and max(spacings) - min(spacings) < 1e-6:
            # Famílias com a mesma modulação podem ser intercaladas.
            s_eff = spacings[0] / max(1, n_fam)
        else:
            # Com modulações diferentes não se assume uma intercalação perfeita; adopta-se
            # conservadoramente o menor espaçamento individual para o controlo de fendas.
            s_eff = min(spacings) if spacings else sol.spacing
        return phi_eq, s_eff, max(1, n_fam)

    def rebar_layer_geometry(self, sol: RebarSolution) -> Dict[str, float]:
        key = (str(sol.text or ""), str(sol.base_text or ""), str(sol.add_text or ""),
               float(sol.phi or 0.0), float(sol.spacing or 0.0), float(sol.as_prov or 0.0))
        val = self._rebar_layer_geom_cache.get(key)
        if val is None:
            val = self._rebar_layer_geometry_uncached(sol)
            self._rebar_layer_geom_cache[key] = val
        return val

    def _rebar_layer_geometry_uncached(self, sol: RebarSolution) -> Dict[str, float]:
        """Geometria física equivalente da família de armadura adoptada.

        A função é usada para calcular a posição real do centróide de uma solução composta.
        Para ``Base + reforço`` as duas famílias são consideradas na mesma camada, com o mesmo
        recobrimento à face exterior. O centróide vertical é ponderado pela área de aço por metro.
        A espessura física ocupada pela camada é conservadoramente o maior diâmetro presente.
        """
        families = []
        if sol.base_text and sol.base_text != "-":
            families.extend(self._parse_rebar_text(sol.base_text))
        if sol.add_text and sol.add_text != "-":
            families.extend(self._parse_rebar_text(sol.add_text))
        if not families:
            families.extend(self._parse_rebar_text(sol.text))
        if not families:
            phi = max(float(sol.phi or 0.0), 0.0)
            return {
                "as_total_mm2_m": max(float(sol.as_prov or 0.0), 0.0),
                "phi_max_mm": phi,
                "centroid_from_layer_face_mm": phi / 2.0,
                "phi_centroid_mm": phi,
                "n_families": 1.0,
            }

        items = []
        for n, phi, spacing in families:
            if spacing <= 0 or phi <= 0:
                continue
            asi = max(1, n) * bar_area_mm2(phi) * 1000.0 / float(spacing)
            items.append((asi, float(phi)))
        if not items:
            phi = max(float(sol.phi or 0.0), 0.0)
            return {
                "as_total_mm2_m": max(float(sol.as_prov or 0.0), 0.0),
                "phi_max_mm": phi,
                "centroid_from_layer_face_mm": phi / 2.0,
                "phi_centroid_mm": phi,
                "n_families": 1.0,
            }
        ast = sum(a for a, _ in items)
        centroid = sum(a * phi / 2.0 for a, phi in items) / max(ast, 1e-12)
        return {
            "as_total_mm2_m": ast,
            "phi_max_mm": max(phi for _a, phi in items),
            "centroid_from_layer_face_mm": centroid,
            "phi_centroid_mm": 2.0 * centroid,
            "n_families": float(len(items)),
        }

    def layer_effective_depth_from_solutions(self, face: str, direction: str,
                                             sol_this: RebarSolution, sol_other: RebarSolution) -> float:
        """Profundidade útil usando ordem física X/Y e centróide real da solução composta."""
        gt = self.rebar_layer_geometry(sol_this)
        go = self.rebar_layer_geometry(sol_other)
        f = normalize_text(str(face))
        outer_axis = self.top_outer_axis if ("sup" in f or "top" in f or f == "+") else self.bottom_outer_axis
        direction = str(direction or "X").upper()[:1]
        if direction == outer_axis:
            cover_to_centroid = self.cover + gt["centroid_from_layer_face_mm"]
        else:
            cover_to_centroid = self.cover + go["phi_max_mm"] + gt["centroid_from_layer_face_mm"]
        return max(self.t - cover_to_centroid, 1.0)

    def review_solution_constructability(self, sol: RebarSolution) -> Tuple[str, str, float]:
        """Avalia a racionalidade construtiva sem contrariar a estratégia Base + reforços.

        Um reforço adicional superior à base é permitido: a base permanece global e o reforço
        é uma família localizada. A rotina apenas emite ``OK*`` para chamar a atenção quando a
        proporção é elevada; isso não substitui a verificação resistente.
        """
        as_base = max(float(sol.as_base or 0.0), 0.0)
        as_add = max(float(sol.as_add or 0.0), 0.0)
        ratio = as_add / as_base if as_base > 1e-9 else 0.0
        if sol.spacing not in self.allowed_spacing_candidates:
            return ("Não conforme", f"Espaçamento {sol.spacing:g} mm fora da grelha construtiva permitida.", ratio)
        if sol.phi > 0 and sol.phi not in self.allowed_phi_candidates:
            return ("Não conforme", f"Diâmetro Ø{sol.phi:g} mm fora da grelha construtiva permitida.", ratio)
        if as_base > 1e-9 and as_add > 1.50 * as_base + 1e-9:
            return ("OK*", f"Reforço local elevado (As,ref/As,base={ratio:.2f}); a base mantém-se invariável, mas convém rever a extensão física da zona.", ratio)
        if as_base > 1e-9 and as_add > 0.75 * as_base + 1e-9:
            return ("OK*", f"Reforço local significativo (As,ref/As,base={ratio:.2f}); confirmar a extensão e pormenorização da zona.", ratio)
        return ("OK", "Solução de armadura compatível com a grelha construtiva automática adoptada.", ratio)

    def _interp_limit(self, sigma_s: float, table: List[Tuple[float, float]]) -> float:
        if not table:
            return 0.0
        sigma_s = max(0.0, float(sigma_s))
        table = sorted(table)
        if sigma_s <= table[0][0]:
            return table[0][1]
        for (s0, v0), (s1, v1) in zip(table[:-1], table[1:]):
            if s0 <= sigma_s <= s1:
                if abs(s1 - s0) < 1e-9:
                    return v0
                return v0 + (v1 - v0) * (sigma_s - s0) / (s1 - s0)
        return table[-1][1]

    def ec2_crack_limits(self, sigma_s: float) -> Tuple[float, float, str]:
        """Limites aproximados por tabelas EC2 7.3N/7.2N para controlo sem cálculo directo.

        As tabelas são usadas como verificação de coerência de diâmetro/espaçamento para o valor de wmax
        seleccionado. Para valores intermédios de tensão é feita interpolação linear.
        """
        w = float(self.wmax_mm)
        # Tabelas indicativas usuais do EC2 para betão armado.
        # sigma_s [MPa] -> phi_max [mm]
        phi_tables = {
            0.4: [(160, 40), (200, 32), (240, 20), (280, 16), (320, 12), (360, 10), (400, 8), (450, 6)],
            0.3: [(160, 32), (200, 25), (240, 16), (280, 12), (320, 10), (360, 8), (400, 6), (450, 5)],
            0.2: [(160, 25), (200, 16), (240, 12), (280, 8), (320, 6), (360, 5), (400, 4), (450, 0)],
        }
        # sigma_s [MPa] -> s_max [mm]
        spacing_tables = {
            0.4: [(160, 300), (200, 300), (240, 250), (280, 200), (320, 150), (360, 100), (400, 50), (450, 0)],
            0.3: [(160, 300), (200, 250), (240, 200), (280, 150), (320, 100), (360, 50), (400, 0), (450, 0)],
            0.2: [(160, 200), (200, 150), (240, 100), (280, 50), (320, 0), (360, 0), (400, 0), (450, 0)],
        }
        # selecciona a classe de wmax imediatamente inferior/igual, por segurança
        if w <= 0.20 + 1e-9:
            key = 0.2
        elif w <= 0.30 + 1e-9:
            key = 0.3
        else:
            key = 0.4
        phi_lim = self._interp_limit(sigma_s, phi_tables[key])
        s_lim = self._interp_limit(sigma_s, spacing_tables[key])
        note = f"limites EC2 indicativos para wmax≈{key:.1f} mm e σs={sigma_s:.0f} MPa"
        return phi_lim, s_lim, note

    def _cracked_section_service_state_uncached(self, m_ed_kNm_per_m: float, sol: RebarSolution, d_mm: Optional[float] = None) -> Dict[str, float]:
        """Estado elástico da secção fendilhada para uma faixa de 1 m.

        A linha neutra e a tensão na armadura são obtidas pela secção transformada fendilhada,
        desprezando o betão traccionado. O método é adequado à flexão simples de lajes correntes
        sem esforço normal significativo, que é o âmbito do SlabsEC2.
        """
        m = abs(float(m_ed_kNm_per_m or 0.0)) * 1e6  # Nmm/m
        As = max(float(sol.as_prov or 0.0), 0.0)
        phi_ctrl, s_eff, _ = self.rebar_crack_geometry(sol)
        d = float(d_mm) if d_mm and d_mm > 0 else self.effective_depth(phi_ctrl)
        # EC2 7.3.4: c é o recobrimento da armadura longitudinal considerada.
        # Como o SlabsEC2 adopta a ordem física configurada das malhas X/Y para d, o recobrimento
        # correspondente dessa família é h-d-phi_eq/2, e não simplesmente c_nom da camada exterior.
        c_eff = max(self.t - d - phi_ctrl / 2.0, self.cover)
        Es = 200000.0
        Ecm = 22.0 * ((self.fck + 8.0) / 10.0) ** 0.3 * 1000.0
        alpha_e = Es / max(Ecm, 1.0)
        b = 1000.0
        I_gross = b * self.t**3 / 12.0
        W_gross = b * self.t**2 / 6.0
        Mcr_Nmm = self.cp["fctm"] * W_gross
        Mcr_kNm_m = Mcr_Nmm / 1e6
        if m <= 1e-9 or As <= 1e-9 or d <= 1.0:
            return {
                "x_cr_mm": 0.0, "I_cr_mm4": 0.0, "sigma_s_MPa": 0.0, "sigma_c_MPa": 0.0,
                "h_ceff_mm": 0.0, "Ac_eff_mm2": 0.0, "rho_p_eff": 0.0,
                "alpha_e": alpha_e, "eps_diff": 0.0, "sr_max_mm": 0.0,
                "wk_mm": 0.0, "kt": 0.4, "phi_control_mm": phi_ctrl,
                "phi_eq_mm": phi_ctrl, "c_eff_mm": c_eff,
                "s_eff_mm": s_eff, "d_mm": d, "Mcr_kNm_m": Mcr_kNm_m,
                "section_cracked": "Não",
            }

        # EC2 7.1: enquanto a tensão de tracção do betão não exceder fct,eff,
        # a secção é tratada como não fendilhada. Nesse caso wk=0.
        if m <= Mcr_Nmm + 1e-9:
            sigma_c_uncr = m * (self.t / 2.0) / max(I_gross, 1.0)
            sigma_s_uncr = alpha_e * m * max(d - self.t / 2.0, 0.0) / max(I_gross, 1.0)
            return {
                "x_cr_mm": self.t / 2.0, "I_cr_mm4": I_gross,
                "sigma_s_MPa": max(0.0, sigma_s_uncr), "sigma_c_MPa": max(0.0, sigma_c_uncr),
                "h_ceff_mm": 0.0, "Ac_eff_mm2": 0.0, "rho_p_eff": 0.0,
                "alpha_e": alpha_e, "eps_diff": 0.0, "sr_max_mm": 0.0,
                "wk_mm": 0.0, "kt": 0.4, "phi_control_mm": phi_ctrl,
                "phi_eq_mm": phi_ctrl, "c_eff_mm": c_eff, "s_eff_mm": s_eff,
                "d_mm": d, "Mcr_kNm_m": Mcr_kNm_m, "section_cracked": "Não",
            }

        # b*x^2/2 = alpha_e*As*(d-x)
        aeAs = alpha_e * As
        disc = aeAs * aeAs + 2.0 * b * aeAs * d
        x = (-aeAs + math.sqrt(max(disc, 0.0))) / b
        x = min(max(x, 1e-6), d - 1e-6)
        Icr = b * x**3 / 3.0 + aeAs * (d - x) ** 2
        sigma_s = alpha_e * m * (d - x) / max(Icr, 1.0)
        sigma_s = max(0.0, sigma_s)
        sigma_c = m * x / max(Icr, 1.0)
        sigma_c = max(0.0, sigma_c)

        # EC2 7.3.2/7.3.4: Ac,eff=b*hc,eff; hc,eff=min[2,5(h-d), (h-x)/3, h/2]
        h_ceff = min(2.5 * max(self.t - d, 0.0), max(self.t - x, 0.0) / 3.0, self.t / 2.0)
        h_ceff = max(h_ceff, 1.0)
        ac_eff = b * h_ceff
        rho_eff = max(As / max(ac_eff, 1.0), 1e-9)

        # EC2 7.3.4: aderência elevada k1=0,8; flexão k2=0,5; valores recomendados k3=3,4 e k4=0,425.
        k1, k2, k3, k4 = 0.8, 0.5, 3.4, 0.425
        c = c_eff
        if s_eff <= 5.0 * (c + phi_ctrl / 2.0) + 1e-9:
            sr_max = k3 * c + k1 * k2 * k4 * phi_ctrl / rho_eff
        else:
            sr_max = 1.3 * max(self.t - x, 0.0)

        # Para combinação quase-permanente/efeitos de longa duração usa-se kt=0,4.
        kt = 0.4
        fct_eff = self.cp["fctm"]
        term = (sigma_s - kt * fct_eff / rho_eff * (1.0 + alpha_e * rho_eff)) / Es
        lower = 0.6 * sigma_s / Es
        eps_diff = max(term, lower, 0.0)
        wk = sr_max * eps_diff
        return {
            "x_cr_mm": x, "I_cr_mm4": Icr, "sigma_s_MPa": sigma_s, "sigma_c_MPa": sigma_c,
            "h_ceff_mm": h_ceff, "Ac_eff_mm2": ac_eff, "rho_p_eff": rho_eff,
            "alpha_e": alpha_e, "eps_diff": eps_diff, "sr_max_mm": sr_max,
            "wk_mm": wk, "kt": kt, "phi_control_mm": phi_ctrl,
            "phi_eq_mm": phi_ctrl, "c_eff_mm": c_eff,
            "s_eff_mm": s_eff, "d_mm": d, "Mcr_kNm_m": Mcr_kNm_m,
            "section_cracked": "Sim",
        }

    def cracked_section_service_state(self, m_ed_kNm_per_m: float, sol: RebarSolution, d_mm: Optional[float] = None) -> Dict[str, float]:
        """Versão com cache do estado de serviço fendilhado.

        Em tabelas FEM extensas, as combinações repetem um número relativamente pequeno de
        valores de momento arredondados e a solução de armadura é fixa por painel. O cache
        evita resolver centenas de milhares de vezes a mesma secção, sem alterar qualquer
        valor numérico ou critério de verificação.
        """
        if not hasattr(self, "_cracked_service_cache"):
            self._cracked_service_cache = {}
        phi_ctrl, _, _ = self.rebar_crack_geometry(sol)
        d = float(d_mm) if d_mm and d_mm > 0 else self.effective_depth(phi_ctrl)
        key = (
            round(abs(float(m_ed_kNm_per_m or 0.0)), 6),
            round(float(sol.as_prov or 0.0), 6),
            round(float(sol.as_base or 0.0), 6),
            round(float(sol.as_add or 0.0), 6),
            str(sol.text),
            round(d, 6),
        )
        cached = self._cracked_service_cache.get(key)
        if cached is None:
            cached = self._cracked_section_service_state_uncached(m_ed_kNm_per_m, sol, d_mm=d)
            self._cracked_service_cache[key] = cached
        return cached

    def _service_state_arrays(self, moments_kNm_m, sol: RebarSolution, d_mm: float) -> Dict[str, np.ndarray]:
        """Estado ELS vectorizado para uma solução fixa de armadura.

        É numericamente equivalente a :meth:`cracked_section_service_state`, mas evita o custo
        de centenas de milhares de dicionários Python no modo de grandes tabelas FEM.
        """
        mv = np.abs(np.asarray(moments_kNm_m, dtype=float))
        m = mv * 1e6
        n = len(mv)
        As = max(float(sol.as_prov or 0.0), 0.0)
        phi_ctrl, s_eff, _ = self.rebar_crack_geometry(sol)
        d = float(d_mm)
        c_eff = max(self.t - d - phi_ctrl / 2.0, self.cover)
        Es = 200000.0
        Ecm = 22.0 * ((self.fck + 8.0) / 10.0) ** 0.3 * 1000.0
        alpha_e = Es / max(Ecm, 1.0)
        b = 1000.0
        I_gross = b * self.t**3 / 12.0
        W_gross = b * self.t**2 / 6.0
        Mcr_Nmm = self.cp["fctm"] * W_gross
        Mcr_kNm_m = Mcr_Nmm / 1e6

        sigma_s = np.zeros(n, dtype=float)
        sigma_c = np.zeros(n, dtype=float)
        wk = np.zeros(n, dtype=float)
        eps_diff = np.zeros(n, dtype=float)
        sr = np.zeros(n, dtype=float)
        xarr = np.zeros(n, dtype=float)
        Iarr = np.zeros(n, dtype=float)
        hceff_arr = np.zeros(n, dtype=float)
        aceff_arr = np.zeros(n, dtype=float)
        rho_arr = np.zeros(n, dtype=float)
        cracked = np.zeros(n, dtype=bool)

        valid = (m > 1e-9) if (As > 1e-9 and d > 1.0) else np.zeros(n, dtype=bool)
        uncr = valid & (m <= Mcr_Nmm + 1e-9)
        if np.any(uncr):
            sigma_c[uncr] = m[uncr] * (self.t / 2.0) / max(I_gross, 1.0)
            sigma_s[uncr] = alpha_e * m[uncr] * max(d - self.t / 2.0, 0.0) / max(I_gross, 1.0)
            xarr[uncr] = self.t / 2.0
            Iarr[uncr] = I_gross

        cr = valid & ~uncr
        if np.any(cr):
            aeAs = alpha_e * As
            disc = aeAs * aeAs + 2.0 * b * aeAs * d
            x = (-aeAs + math.sqrt(max(disc, 0.0))) / b
            x = min(max(x, 1e-6), d - 1e-6)
            Icr = b * x**3 / 3.0 + aeAs * (d - x) ** 2
            hceff = min(2.5 * max(self.t - d, 0.0), max(self.t - x, 0.0) / 3.0, self.t / 2.0)
            hceff = max(hceff, 1.0)
            ac_eff = b * hceff
            rho = max(As / max(ac_eff, 1.0), 1e-9)
            k1, k2, k3, k4 = 0.8, 0.5, 3.4, 0.425
            if s_eff <= 5.0 * (c_eff + phi_ctrl / 2.0) + 1e-9:
                sr_const = k3 * c_eff + k1 * k2 * k4 * phi_ctrl / rho
            else:
                sr_const = 1.3 * max(self.t - x, 0.0)
            sigma_s_cr = alpha_e * m[cr] * (d - x) / max(Icr, 1.0)
            sigma_c_cr = m[cr] * x / max(Icr, 1.0)
            fct_eff = self.cp["fctm"]
            kt = 0.4
            term = (sigma_s_cr - kt * fct_eff / rho * (1.0 + alpha_e * rho)) / Es
            lower = 0.6 * sigma_s_cr / Es
            eps = np.maximum(np.maximum(term, lower), 0.0)
            sigma_s[cr] = np.maximum(0.0, sigma_s_cr)
            sigma_c[cr] = np.maximum(0.0, sigma_c_cr)
            eps_diff[cr] = eps
            wk[cr] = sr_const * eps
            sr[cr] = sr_const
            xarr[cr] = x
            Iarr[cr] = Icr
            hceff_arr[cr] = hceff
            aceff_arr[cr] = ac_eff
            rho_arr[cr] = rho
            cracked[cr] = True

        return {
            "sigma_s": sigma_s, "sigma_c": sigma_c, "wk": wk, "eps_diff": eps_diff,
            "sr_max": sr, "x_cr": xarr, "I_cr": Iarr, "h_ceff": hceff_arr,
            "Ac_eff": aceff_arr, "rho": rho_arr, "cracked": cracked,
            "phi": np.full(n, phi_ctrl), "s_eff": np.full(n, s_eff),
            "c_eff": np.full(n, c_eff), "Mcr": np.full(n, Mcr_kNm_m),
            "alpha_e": np.full(n, alpha_e),
        }

    def _flexural_as_required_array(self, moments_kNm_m, d_mm: float) -> np.ndarray:
        """As,req vectorizado, equivalente a flexural_as_required para d constante."""
        mv = np.abs(np.asarray(moments_kNm_m, dtype=float))
        M = mv * 1e6
        out = np.zeros(len(mv), dtype=float)
        mask = M > 1e-9
        if not np.any(mask):
            return out
        p = concrete_block_parameters(self.fck)
        A = p["eta"] * p["lambda"] * 1000.0 * self.cp["fcd"]
        d = float(d_mm)
        disc = d*d - 2.0 * p["lambda"] * M[mask] / max(A, 1e-12)
        vals = np.full(mask.sum(), np.inf, dtype=float)
        good = disc > 0.0
        if np.any(good):
            x = (d - np.sqrt(disc[good])) / max(p["lambda"], 1e-12)
            gx = (x > 1e-12) & (x < d)
            if np.any(gx):
                xx = x[gx]
                eps_s = p["eps_cu3"] * (d - xx) / xx
                sigma_s = np.minimum(self.fyd, 200000.0 * eps_s)
                av = A * xx / np.maximum(sigma_s, 1e-12)
                tmp = np.full(len(x), np.inf, dtype=float); tmp[gx] = av
                vals[good] = tmp
        out[mask] = vals
        return out

    def crack_width_estimate(self, m_ed_kNm_per_m: float, sol: RebarSolution, d_mm: Optional[float] = None) -> Tuple[float, float, float, str]:
        st = self.cracked_section_service_state(m_ed_kNm_per_m, sol, d_mm=d_mm)
        note = (
            "EC2 7.3.4: secção fendilhada elástica; Ac,eff por hc,eff; "
            "sr,max e (eps_sm-eps_cm) calculados explicitamente; kt=0,4 para ELS quase-permanente"
        )
        return st["wk_mm"], st["sigma_s_MPa"], st["sr_max_mm"], note

    def crack_check_detail(self, m_ed_kNm_per_m: float, sol: RebarSolution, face: str, direction: str, d_mm: Optional[float] = None) -> Dict[str, object]:
        stc = self.cracked_section_service_state(m_ed_kNm_per_m, sol, d_mm=d_mm)
        wk = stc["wk_mm"]
        sigma_s = stc["sigma_s_MPa"]
        phi_ctrl = stc["phi_control_mm"]
        s_eff = stc["s_eff_mm"]
        _, _, n_fam = self.rebar_crack_geometry(sol)
        phi_lim, s_lim, lim_note = self.ec2_crack_limits(sigma_s)
        if wk <= self.wmax_mm + 1e-9:
            st = "OK*" if self.wmax_mm > 0 and wk / self.wmax_mm >= 0.90 else "OK"
            reason = f"wk={wk:.3f} mm <= wmax={self.wmax_mm:.3f} mm"
        else:
            st = "Verificar"
            reason = f"wk={wk:.3f} mm > wmax={self.wmax_mm:.3f} mm"
        return {
            "Face": face, "Direction": direction, "Rebar": sol.text,
            "As_total_mm2_m": sol.as_prov, "As_base_mm2_m": sol.as_base, "As_add_mm2_m": sol.as_add,
            "phi_control_mm": phi_ctrl, "s_eff_mm": s_eff, "n_families": n_fam,
            "sigma_s_MPa": sigma_s, "sigma_c_MPa": stc["sigma_c_MPa"], "phi_lim_EC2_mm": phi_lim, "s_lim_EC2_mm": s_lim,
            "x_cr_mm": stc["x_cr_mm"], "I_cr_mm4": stc["I_cr_mm4"],
            "h_ceff_mm": stc["h_ceff_mm"], "Ac_eff_mm2": stc["Ac_eff_mm2"],
            "rho_p_eff": stc["rho_p_eff"], "alpha_e": stc["alpha_e"],
            "eps_sm_minus_eps_cm": stc["eps_diff"], "kt": stc["kt"],
            "c_eff_mm": stc["c_eff_mm"], "phi_eq_mm": stc["phi_eq_mm"],
            "sr_max_mm": stc["sr_max_mm"], "wk_mm": wk, "wmax_mm": self.wmax_mm,
            "Mcr_kNm_m": stc.get("Mcr_kNm_m", 0.0), "section_cracked": stc.get("section_cracked", "Sim"),
            "Status": st, "Reason": reason,
            "Note": "verificação directa EC2 7.3.4; limites Ø/s apresentados apenas como diagnóstico complementar; " + lim_note,
        }

    def service_stress_check_detail(self, m_service: float, sol: RebarSolution, case_class: str, d_mm: Optional[float] = None) -> Dict[str, object]:
        """Limitação de tensões EC2 7.2 para a combinação de serviço indicada."""
        st = self.cracked_section_service_state(m_service, sol, d_mm=d_mm)
        sigma_s = float(st["sigma_s_MPa"])
        sigma_c = float(st["sigma_c_MPa"])
        lim_s = self.stress_limits["sigma_s_char_lim_MPa"]
        lim_c_char = self.stress_limits["sigma_c_char_lim_MPa"]
        lim_c_qp = self.stress_limits["sigma_c_qp_linear_creep_lim_MPa"]
        status = "Não avaliado"
        note = "sem limitação específica aplicada"
        if not self.stress_check_enabled:
            status = "Não avaliado"
            note = "verificação de tensões ELS desactivada"
        elif case_class == "ELS-CHAR":
            steel_ok = sigma_s <= lim_s + 1e-9
            concrete_ok = sigma_c <= lim_c_char + 1e-9
            if not steel_ok:
                status = "Não conforme"
            elif not concrete_ok:
                # O limite k1*fck é recomendativo e depende da classe de exposição/aplicabilidade.
                # Sem essa informação, sinalizar margem/aviso sem transformar em falha global.
                status = "OK*"
            else:
                status = "OK"
            note = (f"EC2 7.2 característica: sigma_s={sigma_s:.1f}/{lim_s:.1f} MPa; "
                    f"sigma_c={sigma_c:.1f}/{lim_c_char:.1f} MPa. "
                    "O limite de compressão k1*fck deve ser confirmado face à classe de exposição.")
        elif case_class == "ELS-QP":
            if sigma_c > lim_c_qp + 1e-9:
                status = "OK*"
                note = (f"EC2 7.2: sigma_c,QP={sigma_c:.1f} MPa > {lim_c_qp:.1f} MPa; "
                        "a hipótese de fluência linear deixa de ser automaticamente aplicável; considerar fluência não linear. "
                        "Este aviso não constitui, por si só, falha resistente/ELS.")
            else:
                status = "OK"
                note = (f"EC2 7.2: sigma_c,QP={sigma_c:.1f} MPa <= {lim_c_qp:.1f} MPa; "
                        "compatível com fluência linear quanto a este critério.")
        elif case_class == "ELS-FREQ":
            status = "Informativo"
            note = "ELS frequente classificada; sem limite adicional de tensão imposto nesta versão."
        return {
            "sigma_s_MPa": sigma_s, "sigma_c_MPa": sigma_c,
            "sigma_s_lim_MPa": lim_s, "sigma_c_char_lim_MPa": lim_c_char,
            "sigma_c_qp_lim_MPa": lim_c_qp, "Status": status, "Note": note,
        }

    def optimize_solution_for_service_stress(self, m_char: float, sol: RebarSolution, as_req: float,
                                             max_spacing: float, label: str, d_mm: Optional[float] = None) -> RebarSolution:
        """Aumenta a armadura apenas se necessário para cumprir sigma_s<=0,8 fyk em ELS característica."""
        if not self.stress_check_enabled or abs(float(m_char or 0.0)) <= 1e-9:
            return sol
        det = self.service_stress_check_detail(m_char, sol, "ELS-CHAR", d_mm=d_mm)
        if det["sigma_s_MPa"] <= det["sigma_s_lim_MPa"] + 1e-9:
            return sol

        # Em Base + reforços, a base é invariável também quando ELS condiciona.
        if self.optimize_rebar and "substituir" not in normalize_text(self.rebar_strategy):
            is_vertical = self.local_y_is_vertical if str(label).startswith("Y") else (not self.local_y_is_vertical)
            base = self.base_solution_for_direction(is_vertical)
            ok_base, base_note = self.base_solution_is_valid(base, max_spacing)
            if not ok_base:
                sol.capacity_limited = True
                sol.limit_note = (sol.limit_note + " | " if sol.limit_note else "") + f"ELS: base inválida ({base_note}); a base não foi substituída."
                return sol
            candidates = []
            # Base sem reforço e uma única família adicional com a mesma modulação.
            phi_opts = [0.0] + [float(v) for v in sorted(self.phi_candidates)]
            for phi_add in phi_opts:
                if phi_add <= 0:
                    cand = RebarSolution(
                        base.phi, base.spacing, base.as_prov, text_override=base.text,
                        base_text=base.text, add_text="-", as_base=base.as_prov, as_add=0.0,
                        minimum_valid_text=sol.minimum_valid_text or sol.text,
                        optimization_note=f"base fixa avaliada em ELS tensões para {label}",
                    )
                else:
                    clear_interleaved = base.spacing / 2.0 - (base.phi + phi_add) / 2.0
                    min_clear = max(base.phi, phi_add, self.aggregate_mm + 5.0, 20.0)
                    if clear_interleaved + 1e-9 < min_clear:
                        continue
                    as_add = bar_area_mm2(phi_add) * 1000.0 / base.spacing
                    total_as = base.as_prov + as_add
                    cand = RebarSolution(
                        max(base.phi, phi_add), base.spacing, total_as,
                        text_override=f"{base.text} + Ø{int(phi_add)}//{int(base.spacing)}",
                        base_text=base.text, add_text=f"Ø{int(phi_add)}//{int(base.spacing)}",
                        as_base=base.as_prov, as_add=as_add, minimum_valid_text=sol.minimum_valid_text or sol.text,
                        optimization_note=f"base fixa + reforço por ELS tensões para {label}",
                        reinforcement_ratio_add_base=as_add / max(base.as_prov, 1e-9),
                    )
                if cand.as_prov + 1e-9 < as_req:
                    continue
                chk = self.service_stress_check_detail(m_char, cand, "ELS-CHAR", d_mm=d_mm)
                cand.constructability_status, cand.constructability_note, cand.reinforcement_ratio_add_base = self.review_solution_constructability(cand)
                if chk["sigma_s_MPa"] <= chk["sigma_s_lim_MPa"] + 1e-9:
                    candidates.append((cand.as_prov, cand.phi, cand))
            if candidates:
                best = min(candidates, key=lambda x: (x[0], x[1]))[2]
                best.optimization_note += "; limite de tensão ELS verificado sem substituir a base"
                return best
            sol.capacity_limited = True
            sol.limit_note = (sol.limit_note + " | " if sol.limit_note else "") + (
                f"Não existe solução Base + reforço, mantendo {base.text}, que cumpra o limite de tensão do aço em ELS característica para {label}. "
                "Rever a base ou os limites de armadura."
            )
            return sol

        candidates = []
        for phi in self.phi_candidates:
            for spacing in self.spacing_candidates:
                if spacing > max_spacing + 1e-9:
                    continue
                clear = spacing - phi
                if clear < max(phi, self.aggregate_mm + 5.0, 20.0):
                    continue
                cand = self.rebar_from_phi_spacing(phi, spacing)
                if cand.as_prov + 1e-9 < as_req:
                    continue
                dd = float(d_mm) if d_mm and d_mm > 0 else self.effective_depth(phi)
                chk = self.service_stress_check_detail(m_char, cand, "ELS-CHAR", d_mm=dd)
                if chk["sigma_s_MPa"] <= chk["sigma_s_lim_MPa"] + 1e-9:
                    preferred = 0 if spacing in self.preferred_spacing_candidates else (20 if spacing < 100 else 4)
                    excess = cand.as_prov / max(as_req, 1.0)
                    candidates.append(((preferred, excess, cand.as_prov, phi, -spacing), cand))
        if candidates:
            cand = min(candidates, key=lambda x: x[0])[1]
            cand.minimum_valid_text = cand.text
            cand.optimization_note = (cand.optimization_note + "; " if cand.optimization_note else "") + f"ELS tensões verificado para {label}"
            cand.constructability_status, cand.constructability_note, cand.reinforcement_ratio_add_base = self.review_solution_constructability(cand)
            return cand
        sol.capacity_limited = True
        sol.limit_note = (sol.limit_note + " | " if sol.limit_note else "") + f"Não foi encontrada solução Ø/s que cumpra o limite de tensão do aço em ELS característica para {label}."
        return sol

    def optimize_solution_for_cracking(self, m_qp: float, sol: RebarSolution, as_req: float, max_spacing: float, is_vertical_direction: bool, label: str, d_mm: Optional[float] = None) -> RebarSolution:
        """Optimização de fendilhação mantendo coerência entre resistência e solução construtiva."""
        if not self.wk_check_enabled or abs(m_qp) <= 1e-9:
            return sol

        current_detail = self.crack_check_detail(m_qp, sol, label[-1:] if label else "", label[:1] if label else "", d_mm=d_mm)
        if current_detail["wk_mm"] <= self.wmax_mm + 1e-9:
            sol.optimization_note = (sol.optimization_note + "; " if sol.optimization_note else "") + f"wk verificado para {label}"
            return sol

        # Em Base + reforços, o controlo de fendilhação não pode trocar a base por uma malha
        # uniforme. Procura apenas base + uma família adicional com a mesma modulação.
        if self.optimize_rebar and "substituir" not in normalize_text(self.rebar_strategy):
            base = self.base_solution_for_direction(is_vertical_direction)
            ok_base, base_note = self.base_solution_is_valid(base, max_spacing)
            if not ok_base:
                sol.capacity_limited = True
                sol.limit_note = (sol.limit_note + " | " if sol.limit_note else "") + f"wk: base inválida ({base_note}); a base não foi substituída."
                return sol
            evaluated = []
            phi_opts = [0.0] + [float(v) for v in sorted(self.phi_candidates)]
            for phi_add in phi_opts:
                if phi_add <= 0:
                    cand = RebarSolution(
                        base.phi, base.spacing, base.as_prov, text_override=base.text,
                        base_text=base.text, add_text="-", as_base=base.as_prov, as_add=0.0,
                        minimum_valid_text=sol.minimum_valid_text or sol.text,
                        optimization_note=f"base fixa avaliada por fendilhação para {label}",
                    )
                else:
                    clear_interleaved = base.spacing / 2.0 - (base.phi + phi_add) / 2.0
                    min_clear = max(base.phi, phi_add, self.aggregate_mm + 5.0, 20.0)
                    if clear_interleaved + 1e-9 < min_clear:
                        continue
                    as_add = bar_area_mm2(phi_add) * 1000.0 / base.spacing
                    total_as = base.as_prov + as_add
                    if total_as + 1e-9 < as_req:
                        continue
                    cand = RebarSolution(
                        max(base.phi, phi_add), base.spacing, total_as,
                        text_override=f"{base.text} + Ø{int(phi_add)}//{int(base.spacing)}",
                        base_text=base.text, add_text=f"Ø{int(phi_add)}//{int(base.spacing)}",
                        as_base=base.as_prov, as_add=as_add, minimum_valid_text=sol.minimum_valid_text or sol.text,
                        optimization_note=f"base fixa + reforço por fendilhação para {label}",
                        reinforcement_ratio_add_base=as_add / max(base.as_prov, 1e-9),
                    )
                detc = self.crack_check_detail(m_qp, cand, "", "", d_mm=d_mm)
                cand.constructability_status, cand.constructability_note, cand.reinforcement_ratio_add_base = self.review_solution_constructability(cand)
                evaluated.append((self._crack_candidate_key(cand, detc, composite=(phi_add > 0)), cand, detc))
            valid = [x for x in evaluated if x[2]["wk_mm"] <= self.wmax_mm + 1e-9]
            if valid:
                best = sorted(valid, key=lambda x: x[0])[0][1]
                best.optimization_note += "; wk controlado sem substituir a base"
                return best
            if evaluated:
                best = min(evaluated, key=lambda x: (x[2]["wk_mm"], -x[1].as_prov))[1]
            else:
                best = sol
            best.capacity_limited = True
            best_wk = self.crack_check_detail(m_qp, best, "", "", d_mm=d_mm)["wk_mm"]
            best.limit_note = (best.limit_note + " | " if best.limit_note else "") + (
                f"wk não controlado mantendo a base {base.text}; melhor wk={best_wk:.3f} mm. Rever a base ou os limites de armadura."
            )
            best.optimization_note = (best.optimization_note + "; " if best.optimization_note else "") + "limite da estratégia Base + reforços atingido"
            return best

        simple_valid = []
        all_simple = []
        for phi in sorted(self.phi_candidates):
            for spacing in self.spacing_candidates:
                if spacing > max_spacing + 1e-9:
                    continue
                clear = spacing - phi
                if clear < max(phi, self.aggregate_mm + 5.0, 20.0):
                    continue
                cand = self.rebar_from_phi_spacing(phi, spacing)
                if cand.as_prov + 1e-9 < as_req:
                    continue
                cand.minimum_valid_text = cand.text
                det = self.crack_check_detail(m_qp, cand, "", "", d_mm=d_mm)
                all_simple.append((det["wk_mm"], cand, det))
                if det["wk_mm"] <= self.wmax_mm + 1e-9:
                    simple_valid.append((self._crack_candidate_key(cand, det, composite=False), cand, det))
        if simple_valid:
            best = sorted(simple_valid, key=lambda x: x[0])[0][1]
            best.optimization_note = f"controlo de fendilhação por solução uniforme directa para {label}; wk controlado sem agrupamento"
            best.constructability_status, best.constructability_note, best.reinforcement_ratio_add_base = self.review_solution_constructability(best)
            return best

        # Apenas na estratégia Base + reforços se admite uma solução composta, sempre baseada na
        # armadura base configurada e com a mesma modulação. Não se criam bases arbitrárias.
        composite_evaluated = []
        if self.optimize_rebar and "substituir" not in normalize_text(self.rebar_strategy):
            base = self.base_solution_for_direction(is_vertical_direction)
            ok_base, _ = self.base_solution_is_valid(base, max_spacing)
            if ok_base:
                for phi_add in sorted(self.phi_candidates):
                    s = base.spacing
                    clear_interleaved = s / 2.0 - (base.phi + phi_add) / 2.0
                    min_clear = max(base.phi, phi_add, self.aggregate_mm + 5.0, 20.0)
                    if clear_interleaved + 1e-9 < min_clear:
                        continue
                    as_add = bar_area_mm2(phi_add) * 1000.0 / s
                    total_as = base.as_prov + as_add
                    if total_as + 1e-9 < as_req:
                        continue
                    # Reforço superior à base => solução composta pouco racional; não é candidata.
                    if as_add > base.as_prov + 1e-9:
                        continue
                    txt = f"{base.text} + Ø{int(phi_add)}//{int(s)}"
                    cand = RebarSolution(
                        phi=max(base.phi, phi_add), spacing=s, as_prov=total_as,
                        text_override=txt, base_text=base.text, add_text=f"Ø{int(phi_add)}//{int(s)}",
                        as_base=base.as_prov, as_add=as_add, minimum_valid_text="",
                        optimization_note=f"reforço composto com mesma modulação por fendilhação para {label}", n_iterations=3,
                    )
                    det = self.crack_check_detail(m_qp, cand, "", "", d_mm=d_mm)
                    cand.constructability_status, cand.constructability_note, cand.reinforcement_ratio_add_base = self.review_solution_constructability(cand)
                    composite_evaluated.append((self._crack_candidate_key(cand, det, composite=True), cand, det))
        composite_valid = [x for x in composite_evaluated if x[2]["wk_mm"] <= self.wmax_mm + 1e-9]
        if composite_valid:
            best = sorted(composite_valid, key=lambda x: x[0])[0][1]
            best.optimization_note += "; wk controlado com reforço composto racional"
            return best

        evaluated = [(current_detail["wk_mm"], sol, current_detail)] + all_simple + [(x[2]["wk_mm"], x[1], x[2]) for x in composite_evaluated]
        if evaluated:
            best_wk, best, _det = sorted(evaluated, key=lambda x: (x[0], x[1].as_prov))[0]
            best.capacity_limited = True
            best.limit_note = (best.limit_note + " | " if best.limit_note else "") + (
                f"wk não controlado dentro das soluções construtivamente admissíveis; melhor wk={best_wk:.3f} mm."
            )
            best.optimization_note = (best.optimization_note + "; " if best.optimization_note else "") + "limite ELS/fendilhação atingido"
            return best
        return sol

    def _crack_candidate_key(self, cand: RebarSolution, det: Dict[str, object], composite: bool = False) -> Tuple:
        """Ordenação construtiva das soluções que satisfazem fendilhação.

        Prioridades: evitar agrupamentos; garantir margem razoável (alvo wk/wmax<=0,95); evitar
        espaçamentos excessivamente fechados; minimizar quantidade de aço e privilegiar soluções
        correntes. Não se procura o menor wk possível à custa de sobrearmadura desnecessária.
        """
        wk_ratio = safe_float(det.get("wk_mm", 999.0), 999.0) / max(self.wmax_mm, 1e-9)
        s_eff = safe_float(det.get("s_eff_mm", cand.spacing), cand.spacing)
        phi_ctrl = safe_float(det.get("phi_control_mm", cand.phi), cand.phi)
        composite_penalty = 1 if composite else 0
        crack_margin_penalty = max(0.0, wk_ratio - 0.95)
        tight_spacing_penalty = 1 if s_eff < 100.0 - 1e-9 else 0
        preferred_phi_penalty = 0 if phi_ctrl in (10.0, 12.0, 16.0) else 1
        return (composite_penalty, crack_margin_penalty, tight_spacing_penalty, cand.as_prov, preferred_phi_penalty, phi_ctrl, -s_eff, cand.text)

    def is_qp_case(self, case_value: object) -> bool:
        return self.classify_case(case_value) == "ELS-QP"

    def is_frequent_case(self, case_value: object) -> bool:
        return self.classify_case(case_value) == "ELS-FREQ"

    def is_characteristic_case(self, case_value: object) -> bool:
        return self.classify_case(case_value) == "ELS-CHAR"

    def crack_full_status(self, wk_values: List[float], case_value: object) -> Tuple[str, str]:
        if not self.wk_check_enabled:
            return "Não avaliado", "wk não seleccionado; foi aplicado apenas o controlo simplificado por diâmetro/espaçamento"
        if not self.qp_case_ids:
            return "Verificar", "verificação wk seleccionada, mas não foram indicadas combinações quase-permanentes"
        if not self.is_qp_case(case_value):
            return "Não avaliado", f"wk só é avaliado nas combinações quase-permanentes indicadas: {self._qp_cases_label}"
        wk_max = max(wk_values) if wk_values else 0.0
        case_id = canonical_case_id(case_value)
        if wk_max <= self.wmax_mm + 1e-9:
            return "OK", f"ELS-QP {case_id}: wk,max={wk_max:.3f} mm ≤ wmax={self.wmax_mm:.3f} mm"
        return "Verificar", f"ELS-QP {case_id}: wk,max={wk_max:.3f} mm > wmax={self.wmax_mm:.3f} mm"

    def _prepare_preliminary_dataframe_fast(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepara, de forma vectorizada, os campos necessários ao envelope por painel.

        Esta fase não escolhe armadura linha a linha: a armadura final é única por painel/face/
        direcção e é seleccionada posteriormente pelos envelopes ELU/ELS. Na implementação
        anterior a mesma pesquisa Ø/s era executada para cada uma das centenas de milhares de
        linhas e depois descartada durante a harmonização do painel.
        """
        if df is None or df.empty:
            return pd.DataFrame()
        out = pd.DataFrame(index=df.index)
        n = len(df)
        def num(name):
            if name in df.columns:
                return pd.to_numeric(df[name], errors="coerce").fillna(0.0).to_numpy(dtype=float, copy=False)
            return np.zeros(n, dtype=float)
        def obj(name, default=""):
            if name in df.columns:
                return df[name].to_numpy(copy=False)
            return np.full(n, default, dtype=object)

        panel = obj("panel")
        node = obj("node")
        case = obj("case")
        if "case_id" in df.columns:
            cid = df["case_id"].fillna("").astype(str)
        else:
            cid = pd.Series(case, index=df.index).astype(str).str.extract(r"(\d+)", expand=False).fillna("")
        large_mode = bool(getattr(self, "_large_dataset_mode", False))
        if large_mode:
            cc_codes = np.full(n, 4, dtype=np.int8)  # Outro
            if self.uls_case_ids:
                cc_codes[cid.isin(self.uls_case_ids).to_numpy()] = 0
            if self.qp_case_ids:
                cc_codes[cid.isin(self.qp_case_ids).to_numpy()] = 1
            if self.frequent_case_ids:
                cc_codes[cid.isin(self.frequent_case_ids).to_numpy()] = 2
            if self.characteristic_case_ids:
                cc_codes[cid.isin(self.characteristic_case_ids).to_numpy()] = 3
            cc = pd.Categorical.from_codes(cc_codes, categories=["ELU", "ELS-QP", "ELS-FREQ", "ELS-CHAR", "Outro"])
        else:
            cc = np.full(n, "Outro", dtype=object)
            if self.uls_case_ids:
                cc[cid.isin(self.uls_case_ids).to_numpy()] = "ELU"
            if self.qp_case_ids:
                cc[cid.isin(self.qp_case_ids).to_numpy()] = "ELS-QP"
            if self.frequent_case_ids:
                cc[cid.isin(self.frequent_case_ids).to_numpy()] = "ELS-FREQ"
            if self.characteristic_case_ids:
                cc[cid.isin(self.characteristic_case_ids).to_numpy()] = "ELS-CHAR"

        mxx_raw, myy_raw, mxy_raw = num("mxx"), num("myy"), num("mxy")
        wxp_raw, wxn_raw = num("mxx_wa_pos"), num("mxx_wa_neg")
        wyp_raw, wyn_raw = num("myy_wa_pos"), num("myy_wa_neg")
        qxx_raw, qyy_raw, ugz_raw = num("qxx"), num("qyy"), num("ugz")
        nxx, nyy, nxy = num("nxx")*self.membrane_factor, num("nyy")*self.membrane_factor, num("nxy")*self.membrane_factor
        def input_provided(name: str) -> bool:
            flag = f"__provided_{name}"
            if flag in df.columns and len(df):
                vals = df[flag]
                try:
                    return bool(vals.iloc[0])
                except Exception:
                    return False
            # Compatibilidade com DataFrames construídos programaticamente sem clean_dataframe:
            # se a coluna opcional existe de origem, assume-se que foi fornecida.
            return name in df.columns
        provided = {name: input_provided(name) for name in ("qxx", "qyy", "ugz", "nxx", "nyy", "nxy")}
        mxx, myy, mxy = mxx_raw*self.moment_factor, myy_raw*self.moment_factor, mxy_raw*self.moment_factor
        wxp, wxn = np.abs(wxp_raw*self.moment_factor), np.abs(wxn_raw*self.moment_factor)
        wyp, wyn = np.abs(wyp_raw*self.moment_factor), np.abs(wyn_raw*self.moment_factor)
        qxx, qyy = qxx_raw*self.shear_factor, qyy_raw*self.shear_factor
        if self.swap_local_axes:
            mxx, myy = myy.copy(), mxx.copy()
            qxx, qyy = qyy.copy(), qxx.copy()
            nxx, nyy = nyy.copy(), nxx.copy()

        modes = pd.Series(obj("__moment_input_mode", "raw_plate"), index=df.index).astype(str)
        direct = modes.str.startswith("direct_wa").to_numpy()
        if self.swap_local_axes:
            wxp, wyp = wyp.copy(), wxp.copy()
            wxn, wyn = wyn.copy(), wxn.copy()
        mxp = np.zeros(n); mxn=np.zeros(n); myp=np.zeros(n); myn=np.zeros(n)
        mxp[direct], mxn[direct], myp[direct], myn[direct] = wxp[direct], wxn[direct], wyp[direct], wyn[direct]
        rawmask = ~direct
        # v2.15 — único método resistente para RAW: Wood-Armer ortogonal optimizado.
        def wa_branch_vec(mxv, myv, txyv):
            a = np.abs(txyv)
            xv = mxv + a
            yv = myv + a
            mask_x = xv < 0.0
            mask_y = (~mask_x) & (yv < 0.0)
            xs = np.where(mask_x, 0.0, xv)
            ys = np.where(mask_x, myv - np.divide(txyv*txyv, mxv, out=np.zeros_like(mxv), where=np.abs(mxv)>1e-12), yv)
            xs = np.where(mask_y, mxv - np.divide(txyv*txyv, myv, out=np.zeros_like(myv), where=np.abs(myv)>1e-12), xs)
            ys = np.where(mask_y, 0.0, ys)
            return np.maximum(0.0, xs), np.maximum(0.0, ys)
        px, py = wa_branch_vec(mxx, myy, mxy)
        nx, ny = wa_branch_vec(-mxx, -myy, mxy)
        # RAW: converter os ramos de sinal em faces físicas segundo a convenção configurada.
        if self.positive_moment_face == "Superior":
            mxp[rawmask], myp[rawmask] = px[rawmask], py[rawmask]
            mxn[rawmask], myn[rawmask] = nx[rawmask], ny[rawmask]
        else:
            mxp[rawmask], myp[rawmask] = nx[rawmask], ny[rawmask]
            mxn[rawmask], myn[rawmask] = px[rawmask], py[rawmask]
        wa_raw_label="Wood-Armer ortogonal optimizado"
        if large_mode:
            # Categorias por códigos evitam arrays Unicode enormes para textos repetidos.
            wa_codes = np.where(direct, 0, 1).astype(np.int8)
            wa_label = pd.Categorical.from_codes(wa_codes, categories=["Momentos equivalentes importados do software de análise/cálculo", wa_raw_label])
            eq_source = pd.Categorical.from_codes(wa_codes, categories=["importado", "calculado internamente"])
        else:
            wa_label=np.where(direct,"Momentos equivalentes importados do software de análise/cálculo",wa_raw_label)
            eq_source=np.where(direct,"importado","calculado internamente")
        mref=np.maximum(np.maximum(np.abs(mxx),np.abs(myy)),1e-9)
        mxy_ratio=np.where(direct,0.0,np.abs(mxy)/mref)
        # Auditoria Wood-Armer: contribuição directa e incremento associado a Mxy.
        if self.positive_moment_face == "Superior":
            dxp_raw, dxn_raw = np.maximum(0.0,mxx), np.maximum(0.0,-mxx)
            dyp_raw, dyn_raw = np.maximum(0.0,myy), np.maximum(0.0,-myy)
        else:
            dxp_raw, dxn_raw = np.maximum(0.0,-mxx), np.maximum(0.0,mxx)
            dyp_raw, dyn_raw = np.maximum(0.0,-myy), np.maximum(0.0,myy)
        wa_xp_direct=np.where(direct,mxp,dxp_raw)
        wa_xn_direct=np.where(direct,mxn,dxn_raw)
        wa_yp_direct=np.where(direct,myp,dyp_raw)
        wa_yn_direct=np.where(direct,myn,dyn_raw)
        wa_xp_mxy=np.where(direct,0.0,np.maximum(0.0,mxp-wa_xp_direct))
        wa_xn_mxy=np.where(direct,0.0,np.maximum(0.0,mxn-wa_xn_direct))
        wa_yp_mxy=np.where(direct,0.0,np.maximum(0.0,myp-wa_yp_direct))
        wa_yn_mxy=np.where(direct,0.0,np.maximum(0.0,myn-wa_yn_direct))
        if large_mode:
            wa_applied=pd.Categorical.from_codes(np.where(direct,0,1).astype(np.int8),categories=["Não","Sim"])
        else:
            wa_applied=np.where(direct,"Não","Sim")

        ugz_mm=ugz_raw*self.deflection_factor
        ugz_down=np.maximum(0.0,-ugz_mm if self.negative_z_is_down else ugz_mm)
        zero_ugz = np.abs(ugz_mm)<=1e-12
        direction_note=("UGZ negativo considerado como deslocamento para baixo" if self.negative_z_is_down else "UGZ positivo considerado como deslocamento para baixo")
        if not provided["ugz"]:
            if large_mode:
                defl_status = pd.Categorical.from_codes(np.zeros(n, dtype=np.int8), categories=["Não fornecido"])
                defl_note = pd.Categorical.from_codes(np.zeros(n, dtype=np.int8), categories=["UGZ não foi fornecido no ficheiro de entrada"])
            else:
                defl_status = np.full(n, "Não fornecido", dtype=object)
                defl_note = np.full(n, "UGZ não foi fornecido no ficheiro de entrada", dtype=object)
        elif large_mode:
            defl_codes = np.where(zero_ugz, 0, 1).astype(np.int8)
            defl_status = pd.Categorical.from_codes(defl_codes, categories=["Não avaliado", "Informativo"])
            defl_note = pd.Categorical.from_codes(defl_codes, categories=["UGZ fornecido, mas nulo", direction_note+"; UGZ é apresentado apenas como diagnóstico importado do modelo FEM"])
        else:
            defl_status=np.where(zero_ugz,"Não avaliado","Informativo")
            defl_note=np.where(zero_ugz,"UGZ fornecido, mas nulo",direction_note+"; UGZ é apresentado apenas como diagnóstico importado do modelo FEM")
        if large_mode:
            rel_codes = np.where(np.maximum.reduce([mxp,mxn,myp,myn])<1e-9, 0, 1).astype(np.int8)
            relevant = pd.Categorical.from_codes(rel_codes, categories=["Não", "Sim"])
        else:
            relevant=np.where(np.maximum.reduce([mxp,mxn,myp,myn])<1e-9,"Não","Sim")
        nref=np.maximum.reduce([np.abs(nxx),np.abs(nyy),np.abs(nxy)])
        sigma_n=nref/self.t if self.t>0 else np.zeros(n)
        util_n=sigma_n/self.cp["fcd"] if self.cp["fcd"]>0 else np.zeros(n)

        # Campos de entrada e grandezas de envelope.
        def const_text(value):
            if large_mode:
                return pd.Categorical.from_codes(np.zeros(n, dtype=np.int8), categories=[str(value)])
            return value
        if large_mode:
            # Entradas textuais de baixa cardinalidade são categorizadas antes do DataFrame.
            if isinstance(panel, np.ndarray) and panel.dtype.kind in "OUS": panel = pd.Categorical(panel)
            if isinstance(node, np.ndarray) and node.dtype.kind in "OUS": node = pd.Categorical(node)
            if isinstance(case, np.ndarray) and case.dtype.kind in "OUS": case = pd.Categorical(case)
            modes_out = pd.Categorical(modes)
        else:
            modes_out = modes.to_numpy()
        data = {
            "Panel":panel,"Node":node,"Case":case,"Case_classification":cc,
            "ULS_cases":const_text(self._uls_cases_label),"ELS_QP_cases":const_text(self._qp_cases_label),
            "ELS_Frequent_cases":const_text(self._freq_cases_label),"ELS_Characteristic_cases":const_text(self._char_cases_label),
            "MXX_raw":np.where(direct, np.nan, mxx_raw),"MYY_raw":np.where(direct, np.nan, myy_raw),"MXY_raw":np.where(direct, np.nan, mxy_raw),
            "MXX+_equiv_raw":np.where(direct, wxp_raw, np.nan),"MXX-_equiv_raw":np.where(direct, wxn_raw, np.nan),
            "MYY+_equiv_raw":np.where(direct, wyp_raw, np.nan),"MYY-_equiv_raw":np.where(direct, wyn_raw, np.nan),
            "Moment_input_mode":modes_out,"QXX_raw":qxx_raw,"QYY_raw":qyy_raw,"UGZ_raw":ugz_raw,
            "QXX_input_status":const_text("Fornecido" if provided["qxx"] else "Não fornecido"),
            "QYY_input_status":const_text("Fornecido" if provided["qyy"] else "Não fornecido"),
            "UGZ_input_status":const_text("Fornecido" if provided["ugz"] else "Não fornecido"),
            "NXX_input_status":const_text("Fornecido" if provided["nxx"] else "Não fornecido"),
            "NYY_input_status":const_text("Fornecido" if provided["nyy"] else "Não fornecido"),
            "NXY_input_status":const_text("Fornecido" if provided["nxy"] else "Não fornecido"),
            "UGZ_unit":const_text(self.deflection_unit),"UGZ_mm":ugz_mm,"UGZ_down_mm":ugz_down,
            "Deflection_limit":const_text(self.deflection_limit),"Deflection_limit_mm":0.0,"util_deflection":0.0,
            "Deflection_status":defl_status,"Deflection_note":defl_note,
            "Moment_unit":const_text(self.moment_unit),"Shear_unit":const_text(self.shear_unit),"Membrane_unit":const_text(self.membrane_unit),"Combo_type":const_text(self.combo_type),
            "QP_crack_case":const_text(self._qp_cases_label),"QP_crack_cases":const_text(self._qp_cases_label),
            "wk_check_enabled":const_text("Sim" if self.wk_check_enabled else "Não"),
            "is_QP_crack_case":(pd.Categorical.from_codes(np.where(np.asarray(cc == "ELS-QP"), 0, 1).astype(np.int8), categories=["Sim", "Não"]) if large_mode else np.where(cc=="ELS-QP","Sim","Não")),
            "MXX_kNm_m":np.where(direct, np.nan, mxx),"MYY_kNm_m":np.where(direct, np.nan, myy),"MXY_kNm_m":np.where(direct, np.nan, mxy),
            "MXX+_equiv_kNm_m":np.where(direct, wxp, np.nan),"MXX-_equiv_kNm_m":np.where(direct, wxn, np.nan),
            "MYY+_equiv_kNm_m":np.where(direct, wyp, np.nan),"MYY-_equiv_kNm_m":np.where(direct, wyn, np.nan),
            "Equivalent_moment_source":eq_source,"QXX_kN_m":qxx,"QYY_kN_m":qyy,
            "NXX_kN_m":nxx,"NYY_kN_m":nyy,"NXY_kN_m":nxy,
            "Mx+_WA":mxp,"Mx-_WA":mxn,"My+_WA":myp,"My-_WA":myn,
            "MEd_x_sup_kNm_m":mxp,"MEd_x_inf_kNm_m":mxn,"MEd_y_sup_kNm_m":myp,"MEd_y_inf_kNm_m":myn,
            "Moment_sign_convention":const_text(("M>0 -> face superior; M<0 -> face inferior" if self.positive_moment_face=="Superior" else "M>0 -> face inferior; M<0 -> face superior")),
            "WA_method":wa_label,"WA_transformation_applied":wa_applied,"MXY_ratio":mxy_ratio,"MXY_abs_kNm_m":np.abs(mxy),
            "WA_X+_direct_kNm_m":wa_xp_direct,"WA_X+_MXY_add_kNm_m":wa_xp_mxy,
            "WA_X-_direct_kNm_m":wa_xn_direct,"WA_X-_MXY_add_kNm_m":wa_xn_mxy,
            "WA_Y+_direct_kNm_m":wa_yp_direct,"WA_Y+_MXY_add_kNm_m":wa_yp_mxy,
            "WA_Y-_direct_kNm_m":wa_yn_direct,"WA_Y-_MXY_add_kNm_m":wa_yn_mxy,
            "Design_relevant":relevant,
            "sigma_N_membrane_MPa":sigma_n,"util_N_prelim":util_n,
            "VRdc_x_kN_m":0.0,"VRdc_y_kN_m":0.0,"VRdmax_x_kN_m":0.0,"VRdmax_y_kN_m":0.0,
            "util_Qx":0.0,"util_Qy":0.0,"util_Qx_VRdmax":0.0,"util_Qy_VRdmax":0.0,
            "Transverse_links_required":const_text("Não"),
            "Transverse_links_note":const_text("Não aplicável a lajes maciças correntes; verificar punçoamento separadamente em lajes apoiadas directamente em pilares."),
        }
        out = pd.DataFrame(data, index=df.index)
        return out.reset_index(drop=True)

    def design_one(self, row: pd.Series) -> Dict[str, object]:
        mxx_raw = safe_float(row.get("mxx", 0.0), 0.0)
        myy_raw = safe_float(row.get("myy", 0.0), 0.0)
        mxy_raw = safe_float(row.get("mxy", 0.0), 0.0)
        mxx_wa_pos_raw = safe_float(row.get("mxx_wa_pos", 0.0), 0.0)
        mxx_wa_neg_raw = safe_float(row.get("mxx_wa_neg", 0.0), 0.0)
        myy_wa_pos_raw = safe_float(row.get("myy_wa_pos", 0.0), 0.0)
        myy_wa_neg_raw = safe_float(row.get("myy_wa_neg", 0.0), 0.0)
        input_mode = str(row.get("__moment_input_mode", "raw_plate"))
        qxx_raw = safe_float(row.get("qxx", 0.0), 0.0)
        qyy_raw = safe_float(row.get("qyy", 0.0), 0.0)
        ugz_raw = safe_float(row.get("ugz", 0.0), 0.0)
        defl = self.evaluate_deflection(ugz_raw)
        case_class = self.classify_case(row.get("case", ""))
        mxx = mxx_raw * self.moment_factor
        myy = myy_raw * self.moment_factor
        mxy = mxy_raw * self.moment_factor
        mxx_wa_pos = abs(mxx_wa_pos_raw * self.moment_factor)
        mxx_wa_neg = abs(mxx_wa_neg_raw * self.moment_factor)
        myy_wa_pos = abs(myy_wa_pos_raw * self.moment_factor)
        myy_wa_neg = abs(myy_wa_neg_raw * self.moment_factor)
        qxx = qxx_raw * self.shear_factor
        qyy = qyy_raw * self.shear_factor
        nxx = safe_float(row.get("nxx", 0.0), 0.0) * self.membrane_factor
        nyy = safe_float(row.get("nyy", 0.0), 0.0) * self.membrane_factor
        nxy = safe_float(row.get("nxy", 0.0), 0.0) * self.membrane_factor

        if self.swap_local_axes:
            mxx, myy = myy, mxx
            qxx, qyy = qyy, qxx
            nxx, nyy = nyy, nxx

        if input_mode.startswith("direct_wa"):
            mx_pos, mx_neg, my_pos, my_neg = mxx_wa_pos, mxx_wa_neg, myy_wa_pos, myy_wa_neg
            if self.swap_local_axes:
                mx_pos, my_pos = my_pos, mx_pos
                mx_neg, my_neg = my_neg, mx_neg
            wa_method_used = "Momentos equivalentes importados do software de análise/cálculo"
            m_ref = max(mx_pos, mx_neg, my_pos, my_neg, 1e-9)
            mxy_ratio = 0.0
            wa_detail = {
                "X+_direct": mx_pos, "X-_direct": mx_neg, "Y+_direct": my_pos, "Y-_direct": my_neg,
                "X+_mxy": 0.0, "X-_mxy": 0.0, "Y+_mxy": 0.0, "Y-_mxy": 0.0,
            }
            wa_applied = "Não"
        else:
            wa_sign = self.wood_armer_detail(mxx, myy, mxy)
            if self.positive_moment_face == "Superior":
                mx_pos, mx_neg, my_pos, my_neg = wa_sign["X+"], wa_sign["X-"], wa_sign["Y+"], wa_sign["Y-"]
                wa_detail = dict(wa_sign)
            else:
                mx_pos, mx_neg, my_pos, my_neg = wa_sign["X-"], wa_sign["X+"], wa_sign["Y-"], wa_sign["Y+"]
                wa_detail = {
                    "X+_direct": wa_sign["X-_direct"], "X-_direct": wa_sign["X+_direct"],
                    "Y+_direct": wa_sign["Y-_direct"], "Y-_direct": wa_sign["Y+_direct"],
                    "X+_mxy": wa_sign["X-_mxy"], "X-_mxy": wa_sign["X+_mxy"],
                    "Y+_mxy": wa_sign["Y-_mxy"], "Y-_mxy": wa_sign["Y+_mxy"],
                }
            wa_method_used = str(wa_sign["method"])
            m_ref = max(abs(mxx), abs(myy), 1e-9)
            mxy_ratio = abs(mxy) / m_ref
            wa_applied = "Sim"

        top_outer_axis_auto = self.top_outer_axis
        bottom_outer_axis_auto = self.bottom_outer_axis

        # Profundidades úteis preliminares por face/direcção, com Ø12 assumido.
        # As designações +/− abaixo representam faces físicas superior/inferior após mapear a convenção RAW configurada.
        d_x_sup_pre = self.layer_effective_depth("sup", "X", 12.0, 12.0, outer_axis=top_outer_axis_auto)
        d_x_inf_pre = self.layer_effective_depth("inf", "X", 12.0, 12.0, outer_axis=bottom_outer_axis_auto)
        d_y_sup_pre = self.layer_effective_depth("sup", "Y", 12.0, 12.0, outer_axis=top_outer_axis_auto)
        d_y_inf_pre = self.layer_effective_depth("inf", "Y", 12.0, 12.0, outer_axis=bottom_outer_axis_auto)

        asx_pos_flex = self.flexural_as_required(mx_pos, d_mm=d_x_sup_pre)
        asx_neg_flex = self.flexural_as_required(mx_neg, d_mm=d_x_inf_pre)
        asy_pos_flex = self.flexural_as_required(my_pos, d_mm=d_y_sup_pre)
        asy_neg_flex = self.flexural_as_required(my_neg, d_mm=d_y_inf_pre)

        as_main_min_face, as_secondary_min_face, as_slab_max_total = self.min_slab_reinf_limits(12.0)
        as_crack_min_face = self.crack_min_as_per_face()

        # As,min depende de d. Como as malhas X/Y ocupam posições físicas diferentes,
        # calcula-se o mínimo separadamente por face/direcção.
        as_min_by_face = {
            "X+": max(self.slab_flexural_min_for_d(d_x_sup_pre), as_crack_min_face),
            "X-": max(self.slab_flexural_min_for_d(d_x_inf_pre), as_crack_min_face),
            "Y+": max(self.slab_flexural_min_for_d(d_y_sup_pre), as_crack_min_face),
            "Y-": max(self.slab_flexural_min_for_d(d_y_inf_pre), as_crack_min_face),
        }
        as_slab_min_face = max(self.slab_flexural_min_for_d(d_x_sup_pre), self.slab_flexural_min_for_d(d_x_inf_pre),
                               self.slab_flexural_min_for_d(d_y_sup_pre), self.slab_flexural_min_for_d(d_y_inf_pre))
        asx_min_face = max(as_min_by_face["X+"], as_min_by_face["X-"])
        asy_min_face = max(as_min_by_face["Y+"], as_min_by_face["Y-"])

        x_is_main = not self.local_y_is_vertical
        y_is_main = self.local_y_is_vertical
        sx_max = self.max_spacing_for_direction(x_is_main)
        sy_max = self.max_spacing_for_direction(y_is_main)

        asx_pos_req = max(asx_pos_flex, as_min_by_face["X+"])
        asx_neg_req = max(asx_neg_flex, as_min_by_face["X-"])
        asy_pos_req = max(asy_pos_flex, as_min_by_face["Y+"])
        asy_neg_req = max(asy_neg_flex, as_min_by_face["Y-"])

        sol_x_pos = self.optimize_rebar_solution(asx_pos_req, sx_max, x_is_main, "X+")
        sol_x_neg = self.optimize_rebar_solution(asx_neg_req, sx_max, x_is_main, "X-")
        sol_y_pos = self.optimize_rebar_solution(asy_pos_req, sy_max, y_is_main, "Y+")
        sol_y_neg = self.optimize_rebar_solution(asy_neg_req, sy_max, y_is_main, "Y-")

        # QXX/QYY não são usados no dimensionamento desta versão.
        # O SlabsEC2 fica limitado ao cálculo à flexão de lajes maciças;
        # corte unidireccional e punçoamento devem ser verificados em módulos específicos.

        # Iteração específica para fendilhação com a combinações quase-permanentes.
        # A optimização usa a armadura final real da face traccionada e, no modo base + reforços,
        # privilegia reforços intercalados com o mesmo espaçamento da armadura base.
        if self.wk_check_enabled and self.is_qp_case(row.get("case", "")):
            sol_x_pos = self.optimize_solution_for_cracking(mx_pos, sol_x_pos, asx_pos_req, sx_max, x_is_main, "X+", d_mm=d_x_sup_pre)
            sol_x_neg = self.optimize_solution_for_cracking(mx_neg, sol_x_neg, asx_neg_req, sx_max, x_is_main, "X-", d_mm=d_x_inf_pre)
            sol_y_pos = self.optimize_solution_for_cracking(my_pos, sol_y_pos, asy_pos_req, sy_max, y_is_main, "Y+", d_mm=d_y_sup_pre)
            sol_y_neg = self.optimize_solution_for_cracking(my_neg, sol_y_neg, asy_neg_req, sy_max, y_is_main, "Y-", d_mm=d_y_inf_pre)

        # Profundidades úteis finais com as armaduras adoptadas por camada.
        d_x_sup = self.layer_effective_depth_from_solutions("sup", "X", sol_x_pos, sol_y_pos)
        d_x_inf = self.layer_effective_depth_from_solutions("inf", "X", sol_x_neg, sol_y_neg)
        d_y_sup = self.layer_effective_depth_from_solutions("sup", "Y", sol_y_pos, sol_x_pos)
        d_y_inf = self.layer_effective_depth_from_solutions("inf", "Y", sol_y_neg, sol_x_neg)

        # Reavaliação final da armadura com a profundidade útil efectiva.
        # Esta iteração evita que uma camada interior, com d ligeiramente menor, fique subdimensionada
        # depois da selecção inicial baseada em Ø preliminar.
        asx_pos_req_final = max(self.flexural_as_required(mx_pos, d_mm=d_x_sup), asx_min_face)
        asx_neg_req_final = max(self.flexural_as_required(mx_neg, d_mm=d_x_inf), asx_min_face)
        asy_pos_req_final = max(self.flexural_as_required(my_pos, d_mm=d_y_sup), asy_min_face)
        asy_neg_req_final = max(self.flexural_as_required(my_neg, d_mm=d_y_inf), asy_min_face)

        if asx_pos_req_final > sol_x_pos.as_prov + 1e-9:
            sol_x_pos = self.optimize_rebar_solution(asx_pos_req_final, sx_max, x_is_main, "X+")
        if asx_neg_req_final > sol_x_neg.as_prov + 1e-9:
            sol_x_neg = self.optimize_rebar_solution(asx_neg_req_final, sx_max, x_is_main, "X-")
        if asy_pos_req_final > sol_y_pos.as_prov + 1e-9:
            sol_y_pos = self.optimize_rebar_solution(asy_pos_req_final, sy_max, y_is_main, "Y+")
        if asy_neg_req_final > sol_y_neg.as_prov + 1e-9:
            sol_y_neg = self.optimize_rebar_solution(asy_neg_req_final, sy_max, y_is_main, "Y-")

        if self.wk_check_enabled and self.is_qp_case(row.get("case", "")):
            sol_x_pos = self.optimize_solution_for_cracking(mx_pos, sol_x_pos, asx_pos_req_final, sx_max, x_is_main, "X+", d_mm=d_x_sup)
            sol_x_neg = self.optimize_solution_for_cracking(mx_neg, sol_x_neg, asx_neg_req_final, sx_max, x_is_main, "X-", d_mm=d_x_inf)
            sol_y_pos = self.optimize_solution_for_cracking(my_pos, sol_y_pos, asy_pos_req_final, sy_max, y_is_main, "Y+", d_mm=d_y_sup)
            sol_y_neg = self.optimize_solution_for_cracking(my_neg, sol_y_neg, asy_neg_req_final, sy_max, y_is_main, "Y-", d_mm=d_y_inf)

        # Actualiza d após eventual alteração de diâmetros.
        d_x_sup = self.layer_effective_depth_from_solutions("sup", "X", sol_x_pos, sol_y_pos)
        d_x_inf = self.layer_effective_depth_from_solutions("inf", "X", sol_x_neg, sol_y_neg)
        d_y_sup = self.layer_effective_depth_from_solutions("sup", "Y", sol_y_pos, sol_x_pos)
        d_y_inf = self.layer_effective_depth_from_solutions("inf", "Y", sol_y_neg, sol_x_neg)

        fs_x_pos = self.flexural_section_state(sol_x_pos.as_prov, d_x_sup)
        fs_x_neg = self.flexural_section_state(sol_x_neg.as_prov, d_x_inf)
        fs_y_pos = self.flexural_section_state(sol_y_pos.as_prov, d_y_sup)
        fs_y_neg = self.flexural_section_state(sol_y_neg.as_prov, d_y_inf)
        mrd_x_pos, x_x_sup, z_x_sup, xd_x_sup = self.flexural_metrics(sol_x_pos.as_prov, d_x_sup)
        mrd_x_neg, x_x_inf, z_x_inf, xd_x_inf = self.flexural_metrics(sol_x_neg.as_prov, d_x_inf)
        mrd_y_pos, x_y_sup, z_y_sup, xd_y_sup = self.flexural_metrics(sol_y_pos.as_prov, d_y_sup)
        mrd_y_neg, x_y_inf, z_y_inf, xd_y_inf = self.flexural_metrics(sol_y_neg.as_prov, d_y_inf)
        section_domain_valid = all(str(x.get("section_domain_valid", "Não")) == "Sim" for x in (fs_x_pos, fs_x_neg, fs_y_pos, fs_y_neg))
        steel_yields_all_faces = all(str(x.get("steel_yields", "Não")) == "Sim" for x in (fs_x_pos, fs_x_neg, fs_y_pos, fs_y_neg))
        mrd_singly_lim_min = min(float(x.get("MRd_singly_lim_kNm_m", 0.0)) for x in (fs_x_pos, fs_x_neg, fs_y_pos, fs_y_neg))
        xi_bal_min = min(float(x.get("xi_bal", 0.0)) for x in (fs_x_pos, fs_x_neg, fs_y_pos, fs_y_neg))

        util_m = max(
            mx_pos / mrd_x_pos if mrd_x_pos > 0 else 0.0,
            mx_neg / mrd_x_neg if mrd_x_neg > 0 else 0.0,
            my_pos / mrd_y_pos if mrd_y_pos > 0 else 0.0,
            my_neg / mrd_y_neg if mrd_y_neg > 0 else 0.0,
        )

        # QXX/QYY são importados e reportados, mas não participam no dimensionamento automático desta versão.
        vrdc_x = vrdc_y = vrdmax_x = vrdmax_y = 0.0
        util_qx = util_qy = util_qx_max = util_qy_max = 0.0
        util = util_m

        # As,max é controlado na face/direcção que resiste ao estado de flexão considerado.
        # A soma superior+inferior é mantida apenas como grandeza diagnóstica.
        asx_total = sol_x_pos.as_prov + sol_x_neg.as_prov
        asy_total = sol_y_pos.as_prov + sol_y_neg.as_prov
        as_face_governing = max(sol_x_pos.as_prov, sol_x_neg.as_prov, sol_y_pos.as_prov, sol_y_neg.as_prov)
        max_ok = as_face_governing <= as_slab_max_total + 1e-9

        # Não há armadura transversal de ligação entre faces em lajes maciças correntes.
        transverse_links_required = False
        transverse_links_note = "Não aplicável a lajes maciças correntes; verificar punçoamento separadamente em lajes apoiadas directamente em pilares."
        # Controlo de fendilhação.
        # Quando a verificação directa por wk está activada, só as combinações ELS quase-permanentes
        # indicadas podem condicionar wk. ELS frequente/característica permanecem classificadas, mas informativas.
        crack_x_pos = self.crack_check_detail(mx_pos, sol_x_pos, "superior", "X", d_mm=d_x_sup)
        crack_x_neg = self.crack_check_detail(mx_neg, sol_x_neg, "inferior", "X", d_mm=d_x_inf)
        crack_y_pos = self.crack_check_detail(my_pos, sol_y_pos, "superior", "Y", d_mm=d_y_sup)
        crack_y_neg = self.crack_check_detail(my_neg, sol_y_neg, "inferior", "Y", d_mm=d_y_inf)
        wk_x_pos = float(crack_x_pos["wk_mm"]); sig_x_pos = float(crack_x_pos["sigma_s_MPa"]); sr_x_pos = float(crack_x_pos["sr_max_mm"])
        wk_x_neg = float(crack_x_neg["wk_mm"]); sig_x_neg = float(crack_x_neg["sigma_s_MPa"]); sr_x_neg = float(crack_x_neg["sr_max_mm"])
        wk_y_pos = float(crack_y_pos["wk_mm"]); sig_y_pos = float(crack_y_pos["sigma_s_MPa"]); sr_y_pos = float(crack_y_pos["sr_max_mm"])
        wk_y_neg = float(crack_y_neg["wk_mm"]); sig_y_neg = float(crack_y_neg["sigma_s_MPa"]); sr_y_neg = float(crack_y_neg["sr_max_mm"])

        if self.wk_check_enabled:
            if self.is_qp_case(row.get("case", "")):
                crack_full_status, crack_full_note = self.crack_full_status([wk_x_pos, wk_x_neg, wk_y_pos, wk_y_neg], row.get("case", ""))
                # Com cálculo directo de wk, as tabelas Ø/s são apenas diagnóstico complementar;
                # não podem transformar uma verificação directa satisfeita numa falsa não conformidade.
                crack_status = crack_full_status
                crack_note = crack_full_note + " | limites simplificados de Ø/s apresentados apenas para auditoria"
            else:
                crack_status = "Não avaliado"
                crack_full_note = f"wk não avaliado nesta linha; verificação directa limitada às combinações ELS-QP {self._qp_cases_label}"
                crack_note = crack_full_note
        else:
            crack_items = [
                self.crack_simplified_status(sol_x_pos),
                self.crack_simplified_status(sol_x_neg),
                self.crack_simplified_status(sol_y_pos),
                self.crack_simplified_status(sol_y_neg),
            ]
            crack_rank = {"OK": 0, "OK*": 1, "Não avaliado": 1, "Verificar": 2}
            crack_status = max((st for st, _ in crack_items), key=lambda st: crack_rank.get(st, 2))
            crack_full_note = "wk não seleccionado; fendilhação controlada por diâmetro/espaçamento"
            crack_note = " | ".join(sorted(set(note for _, note in crack_items))) + " | " + crack_full_note

        # Esforços de membrana NXX/NYY/NXY podem existir em modelos de casca, mas não fazem parte
        # do dimensionamento corrente de lajes desta versão. Mantém-se apenas um indicador informativo.
        n_ref = max(abs(nxx), abs(nyy), abs(nxy))
        sigma_n_mpa = n_ref / self.t if self.t > 0 else 0.0
        axial_prelim_util = sigma_n_mpa / self.cp["fcd"] if self.cp["fcd"] > 0 else 0.0

        notes = []
        zero_efforts = max(mx_pos, mx_neg, my_pos, my_neg) < 1e-9
        if self.moment_factor != 1.0 or self.shear_factor != 1.0 or self.membrane_factor != 1.0:
            notes.append(f"unidades convertidas: M x{self.moment_factor:g}; Q x{self.shear_factor:g}; N x{self.membrane_factor:g}")
        if abs(ugz_raw) > 1e-12:
            notes.append(defl["Deflection_note"])
        if self.wk_check_enabled:
            if not self.qp_case_ids:
                notes.append("wk seleccionado, mas faltam combinações ELS quase-permanentes")
            elif self.is_qp_case(row.get("case", "")):
                notes.append(f"wk avaliado para ELS-QP {canonical_case_id(row.get('case', ''))}")
        else:
            notes.append("wk não seleccionado: fendilhação controlada apenas por diâmetro/espaçamento")
        membrane_present = n_ref > 1e-6
        if membrane_present:
            notes.append("NXX/NYY/NXY fornecido: interação N-M não implementada; resultado resistente requer verificação adicional")
        if max(abs(qxx), abs(qyy)) > 1e-9:
            notes.append("QXX/QYY fornecidos: apresentados apenas como informação do modelo FEM; não entram no cálculo de armaduras")
        if input_mode.startswith("direct_wa"):
            notes.append("momentos equivalentes importados: usados directamente; não foi aplicada nova transformação Wood & Armer interna")
        elif input_mode == "undefined":
            notes.append("colunas de momentos não reconhecidas; confirmar formato da tabela")
        if not max_ok:
            notes.append("As numa face/direcção > 0,04 Ac")
        if transverse_links_required:
            notes.append("As elevada; confirmar pormenorização local")
        if not section_domain_valid:
            notes.append("domínio da secção simplesmente armada excedido numa das faces/direcções; não é creditada capacidade adicional por aumento de armadura traccionada")
        if crack_status == "Verificar":
            notes.append("controlo de fendilhação simplificado não satisfeito")
        if self.swap_local_axes:
            notes.append("eixos locais X/Y trocados antes do cálculo")
        if self.optimize_rebar:
            notes.append(f"harmonização/optimização de armadura activada ({self.rebar_strategy})")
        else:
            notes.append("dimensionamento automático directo; harmonização/optimização desactivada")
        if zero_efforts:
            notes.append("linha sem esforços relevantes")

        if zero_efforts:
            status = "Informativo"
        elif case_class == "ELU":
            if not max_ok or util_m > 1.0 or not section_domain_valid:
                status = "Não conforme"
            elif membrane_present:
                status = "Verificar"
            elif util_m >= 0.98:
                status = "OK*"
            else:
                status = "OK"
        elif case_class == "ELS-QP":
            if not self.wk_check_enabled:
                status = "Não avaliado"
            elif crack_status == "Verificar":
                status = "Não conforme"
            elif membrane_present:
                status = "Verificar"
            elif crack_status == "OK*":
                status = "OK*"
            else:
                status = "OK"
        else:
            status = "Informativo"

        # Clarificação explícita do estado atribuído.
        reason_items = []
        action_items = []
        if zero_efforts:
            reason_items.append("linha sem momento de dimensionamento relevante; mantida apenas para rastreabilidade")
            action_items.append("não condiciona a armadura; pode ser ignorada no resumo de dimensionamento")
        if not max_ok:
            reason_items.append("As numa face/direcção excede o limite adoptado de 0,04 Ac")
            action_items.append("rever espessura, diâmetros, espaçamentos e eventual necessidade de solução localizada")
        if util_m > 1.0:
            reason_items.append(f"utilização à flexão superior a 1,00 (util_M={util_m:.2f})")
            action_items.append("aumentar a armadura adoptada, reduzir o espaçamento ou rever os esforços de cálculo")
        if crack_status == "Verificar":
            reason_items.append(crack_full_note if self.wk_check_enabled else "controlo simplificado de fendilhação não satisfeito")
            action_items.append("usar combinação quase-permanente de ELS, reduzir diâmetro/espaçamento ou aumentar a armadura")
        if crack_status == "OK*":
            reason_items.append("controlo de fendilhação preliminar no limite")
            action_items.append("confirmar por wk em ELS se a fendilhação for condicionante")
        if membrane_present:
            reason_items.append("esforço de membrana NXX/NYY/NXY presente; interação N-M não avaliada")
            action_items.append("efectuar verificação N-M separada ou confirmar que os esforços de membrana podem ser negligenciados")
        if transverse_links_required:
            reason_items.append("As elevada; confirmar pormenorização local")
            action_items.append("confirmar solução local e pormenorização da laje")
        if not section_domain_valid:
            reason_items.append("domínio resistente da secção simplesmente armada excedido numa das faces/direcções")
            action_items.append("não aumentar apenas a armadura traccionada; rever espessura/secção ou adoptar modelo específico com armadura de compressão")
        if self.moment_factor != 1.0 or self.shear_factor != 1.0 or self.membrane_factor != 1.0:
            reason_items.append("unidades importadas convertidas antes do cálculo")
            action_items.append("confirmar unidades da tabela de origem")

        if not reason_items:
            if status == "OK":
                reason_items.append("cumpre as verificações implementadas")
                action_items.append("validar hipóteses gerais, eixos locais e dados de entrada")
            elif status == "OK*":
                reason_items.append("cumpre, mas com aviso menor")
                action_items.append("rever notas antes de adoptar em projecto")
            else:
                reason_items.append("estado atribuído por combinação de avisos")
                action_items.append("rever notas de cálculo")

        verification_reason = " | ".join(dict.fromkeys(str(x) for x in reason_items if str(x).strip()))
        recommended_action = " | ".join(dict.fromkeys(str(x) for x in action_items if str(x).strip()))

        # Separação explícita entre ELU e ELS/fendilhação.
        # wk só é válido para as combinações ELS quase-permanentes indicadas; os valores calculados
        # em linhas de ELU não devem condicionar o estado de fendilhação nem aparecer como governantes ELS.
        is_qp_crack_case = self.is_qp_case(row.get("case", ""))
        wk_unfiltered_max = max(wk_x_pos, wk_x_neg, wk_y_pos, wk_y_neg)
        wk_eval_enabled = bool(self.wk_check_enabled and is_qp_crack_case)
        wk_eval_max = wk_unfiltered_max if wk_eval_enabled else float("nan")
        wk_eval_ratio = (wk_eval_max / self.wmax_mm) if (wk_eval_enabled and self.wmax_mm > 0) else float("nan")
        if not self.wk_check_enabled:
            els_wk_status = "Não avaliado"
            els_wk_note = "wk não seleccionado; sem verificação directa de fendilhação."
        elif not self.qp_case_ids:
            els_wk_status = "Verificar"
            els_wk_note = "wk seleccionado, mas não foram indicadas combinações ELS quase-permanentes."
        elif not is_qp_crack_case:
            els_wk_status = "Não avaliado"
            els_wk_note = f"linha fora das combinações quase-permanentes {self._qp_cases_label}; wk não é usado nesta linha."
        elif wk_eval_max <= self.wmax_mm + 1e-9:
            els_wk_status = "OK*" if wk_eval_ratio >= 0.90 else "OK"
            els_wk_note = f"ELS-QP {canonical_case_id(row.get('case', ''))}: wk,max={wk_eval_max:.3f} mm; wk/wmax={wk_eval_ratio:.3f}."
        else:
            els_wk_status = "Verificar"
            els_wk_note = f"ELS-QP {canonical_case_id(row.get('case', ''))}: wk,max={wk_eval_max:.3f} mm > wmax={self.wmax_mm:.3f} mm; wk/wmax={wk_eval_ratio:.3f}."

        return {
            "Panel": row.get("panel", ""),
            "Node": row.get("node", ""),
            "Case": row.get("case", ""),
            "Case_classification": case_class,
            "ULS_cases": self._uls_cases_label,
            "ELS_QP_cases": self._qp_cases_label,
            "ELS_Frequent_cases": self._freq_cases_label,
            "ELS_Characteristic_cases": self._char_cases_label,
            "MXX_raw": float("nan") if input_mode.startswith("direct_wa") else mxx_raw,
            "MYY_raw": float("nan") if input_mode.startswith("direct_wa") else myy_raw,
            "MXY_raw": float("nan") if input_mode.startswith("direct_wa") else mxy_raw,
            "MXX+_equiv_raw": mxx_wa_pos_raw if input_mode.startswith("direct_wa") else float("nan"),
            "MXX-_equiv_raw": mxx_wa_neg_raw if input_mode.startswith("direct_wa") else float("nan"),
            "MYY+_equiv_raw": myy_wa_pos_raw if input_mode.startswith("direct_wa") else float("nan"),
            "MYY-_equiv_raw": myy_wa_neg_raw if input_mode.startswith("direct_wa") else float("nan"),
            "Moment_input_mode": input_mode,
            "QXX_raw": qxx_raw,
            "QYY_raw": qyy_raw,
            "UGZ_raw": ugz_raw,
            "UGZ_unit": self.deflection_unit,
            "UGZ_mm": defl["UGZ_mm"],
            "UGZ_down_mm": defl["UGZ_down_mm"],
            "Deflection_limit": self.deflection_limit,
            "Deflection_limit_mm": defl["Deflection_limit_mm"],
            "util_deflection": defl["util_deflection"],
            "Deflection_status": defl["Deflection_status"],
            "Deflection_note": defl["Deflection_note"],
            "Moment_unit": self.moment_unit,
            "Shear_unit": self.shear_unit,
            "Membrane_unit": self.membrane_unit,
            "Combo_type": self.combo_type,
            "QP_crack_case": self._qp_cases_label,
            "QP_crack_cases": self._qp_cases_label,
            "wk_check_enabled": "Sim" if self.wk_check_enabled else "Não",
            "is_QP_crack_case": "Sim" if is_qp_crack_case else "Não",
            "ELS_wk_evaluated": "Sim" if wk_eval_enabled else "Não",
            "ELS_wk_case": row.get("case", "") if wk_eval_enabled else "",
            "ELS_wk_node": row.get("node", "") if wk_eval_enabled else "",
            "ELS_wk_max_mm": wk_eval_max,
            "ELS_wk_ratio": wk_eval_ratio,
            "ELS_wk_status": els_wk_status,
            "ELS_wk_note": els_wk_note,
            "MXX_kNm_m": float("nan") if input_mode.startswith("direct_wa") else mxx,
            "MYY_kNm_m": float("nan") if input_mode.startswith("direct_wa") else myy,
            "MXY_kNm_m": float("nan") if input_mode.startswith("direct_wa") else mxy,
            "MXX+_equiv_kNm_m": mxx_wa_pos if input_mode.startswith("direct_wa") else float("nan"),
            "MXX-_equiv_kNm_m": mxx_wa_neg if input_mode.startswith("direct_wa") else float("nan"),
            "MYY+_equiv_kNm_m": myy_wa_pos if input_mode.startswith("direct_wa") else float("nan"),
            "MYY-_equiv_kNm_m": myy_wa_neg if input_mode.startswith("direct_wa") else float("nan"),
            "Equivalent_moment_source": "importado" if input_mode.startswith("direct_wa") else "calculado internamente",
            "QXX_kN_m": qxx,
            "QYY_kN_m": qyy,
            "NXX_kN_m": nxx,
            "NYY_kN_m": nyy,
            "NXY_kN_m": nxy,
            "Mx+_WA": mx_pos,
            "Mx-_WA": mx_neg,
            "My+_WA": my_pos,
            "My-_WA": my_neg,
            "MEd_x_sup_kNm_m": mx_pos,
            "MEd_x_inf_kNm_m": mx_neg,
            "MEd_y_sup_kNm_m": my_pos,
            "MEd_y_inf_kNm_m": my_neg,
            "Moment_sign_convention": ("M>0 -> face superior; M<0 -> face inferior" if self.positive_moment_face=="Superior" else "M>0 -> face inferior; M<0 -> face superior"),
            "Layer_order_mode": "Ordem física configurada das malhas X/Y",
            "Bottom_outer_axis": bottom_outer_axis_auto,
            "Top_outer_axis": top_outer_axis_auto,
            "Design_relevant": "Não" if zero_efforts else "Sim",
            "d_x_sup_mm": d_x_sup,
            "d_x_inf_mm": d_x_inf,
            "d_y_sup_mm": d_y_sup,
            "d_y_inf_mm": d_y_inf,
            "WA_method": wa_method_used,
            "WA_transformation_applied": wa_applied,
            "MXY_ratio": mxy_ratio,
            "MXY_abs_kNm_m": abs(mxy),
            "WA_X+_direct_kNm_m": wa_detail["X+_direct"], "WA_X+_MXY_add_kNm_m": wa_detail["X+_mxy"],
            "WA_X-_direct_kNm_m": wa_detail["X-_direct"], "WA_X-_MXY_add_kNm_m": wa_detail["X-_mxy"],
            "WA_Y+_direct_kNm_m": wa_detail["Y+_direct"], "WA_Y+_MXY_add_kNm_m": wa_detail["Y+_mxy"],
            "WA_Y-_direct_kNm_m": wa_detail["Y-_direct"], "WA_Y-_MXY_add_kNm_m": wa_detail["Y-_mxy"],
            "Asx+_req_mm2_m": max(asx_pos_req, locals().get("asx_pos_req_final", asx_pos_req)),
            "Asx-_req_mm2_m": max(asx_neg_req, locals().get("asx_neg_req_final", asx_neg_req)),
            "Asy+_req_mm2_m": max(asy_pos_req, locals().get("asy_pos_req_final", asy_pos_req)),
            "Asy-_req_mm2_m": max(asy_neg_req, locals().get("asy_neg_req_final", asy_neg_req)),
            "As_main_min_mm2_m": as_main_min_face,
            "As_secondary_min_mm2_m": as_secondary_min_face,
            "As_slab_min_face_mm2_m": as_slab_min_face,
            "As_crack_min_face_mm2_m": as_crack_min_face,
            "As_min_x+_mm2_m": as_min_by_face["X+"], "As_min_x-_mm2_m": as_min_by_face["X-"],
            "As_min_y+_mm2_m": as_min_by_face["Y+"], "As_min_y-_mm2_m": as_min_by_face["Y-"],
            "sX_max_mm": sx_max,
            "sY_max_mm": sy_max,
            "X+_rebar": sol_x_pos.text,
            "X-_rebar": sol_x_neg.text,
            "Y+_rebar": sol_y_pos.text,
            "Y-_rebar": sol_y_neg.text,
            "X_sup_rebar": sol_x_pos.text,
            "X_inf_rebar": sol_x_neg.text,
            "Y_sup_rebar": sol_y_pos.text,
            "Y_inf_rebar": sol_y_neg.text,
            "X+_base": sol_x_pos.base_text or "-",
            "X-_base": sol_x_neg.base_text or "-",
            "Y+_base": sol_y_pos.base_text or "-",
            "Y-_base": sol_y_neg.base_text or "-",
            "X+_additional": sol_x_pos.add_text or "-",
            "X-_additional": sol_x_neg.add_text or "-",
            "Y+_additional": sol_y_pos.add_text or "-",
            "Y-_additional": sol_y_neg.add_text or "-",
            "X+_minimum_valid": sol_x_pos.minimum_valid_text or sol_x_pos.text,
            "X-_minimum_valid": sol_x_neg.minimum_valid_text or sol_x_neg.text,
            "Y+_minimum_valid": sol_y_pos.minimum_valid_text or sol_y_pos.text,
            "Y-_minimum_valid": sol_y_neg.minimum_valid_text or sol_y_neg.text,
            "X+_constructability": sol_x_pos.constructability_status,
            "X-_constructability": sol_x_neg.constructability_status,
            "Y+_constructability": sol_y_pos.constructability_status,
            "Y-_constructability": sol_y_neg.constructability_status,
            "X+_constructability_note": sol_x_pos.constructability_note,
            "X-_constructability_note": sol_x_neg.constructability_note,
            "Y+_constructability_note": sol_y_pos.constructability_note,
            "Y-_constructability_note": sol_y_neg.constructability_note,
            "X+_As_ref_base_ratio": sol_x_pos.reinforcement_ratio_add_base,
            "X-_As_ref_base_ratio": sol_x_neg.reinforcement_ratio_add_base,
            "Y+_As_ref_base_ratio": sol_y_pos.reinforcement_ratio_add_base,
            "Y-_As_ref_base_ratio": sol_y_neg.reinforcement_ratio_add_base,
            "Asx+_base_mm2_m": sol_x_pos.as_base, "Asx+_add_mm2_m": sol_x_pos.as_add,
            "Asx-_base_mm2_m": sol_x_neg.as_base, "Asx-_add_mm2_m": sol_x_neg.as_add,
            "Asy+_base_mm2_m": sol_y_pos.as_base, "Asy+_add_mm2_m": sol_y_pos.as_add,
            "Asy-_base_mm2_m": sol_y_neg.as_base, "Asy-_add_mm2_m": sol_y_neg.as_add,
            "X+_optimization": sol_x_pos.optimization_note,
            "X-_optimization": sol_x_neg.optimization_note,
            "Y+_optimization": sol_y_pos.optimization_note,
            "Y-_optimization": sol_y_neg.optimization_note,
            "Optimization_iterations": max(sol_x_pos.n_iterations, sol_x_neg.n_iterations, sol_y_pos.n_iterations, sol_y_neg.n_iterations),
            "Optimization_mode": (f"Harmonização/optimização — {self.rebar_strategy}" if self.optimize_rebar else "Dimensionamento automático directo — sem harmonização"),
            "Asx+_prov_mm2_m": sol_x_pos.as_prov,
            "Asx-_prov_mm2_m": sol_x_neg.as_prov,
            "Asy+_prov_mm2_m": sol_y_pos.as_prov,
            "Asy-_prov_mm2_m": sol_y_neg.as_prov,
            "MRd_x+_kNm_m": mrd_x_pos,
            "MRd_x-_kNm_m": mrd_x_neg,
            "MRd_y+_kNm_m": mrd_y_pos,
            "MRd_y-_kNm_m": mrd_y_neg,
            "Section_domain_valid": "Sim" if section_domain_valid else "Não",
            "MRd_singly_lim_min_kNm_m": mrd_singly_lim_min,
            "xi_bal_min": xi_bal_min,
            "steel_yields_all_faces": "Sim" if steel_yields_all_faces else "Não",
            "x_d_x_sup": xd_x_sup,
            "x_d_x_inf": xd_x_inf,
            "x_d_y_sup": xd_y_sup,
            "x_d_y_inf": xd_y_inf,
            "VRdc_x_kN_m": vrdc_x,
            "VRdc_y_kN_m": vrdc_y,
            "VRdmax_x_kN_m": vrdmax_x,
            "VRdmax_y_kN_m": vrdmax_y,
            "util_M": util_m,
            "util_Qx": util_qx,
            "util_Qy": util_qy,
            "util_Qx_VRdmax": util_qx_max,
            "util_Qy_VRdmax": util_qy_max,
            "util_max": util,
            "Asx_total_mm2_m": asx_total,
            "Asy_total_mm2_m": asy_total,
            "As_slab_max_mm2_m": as_slab_max_total,
            "sigma_N_membrane_MPa": sigma_n_mpa,
            "util_N_prelim": axial_prelim_util,
            "Transverse_links_required": "Sim" if transverse_links_required else "Não",
            "Transverse_links_note": transverse_links_note,
            "wk_x+_mm": wk_x_pos,
            "wk_x-_mm": wk_x_neg,
            "wk_y+_mm": wk_y_pos,
            "wk_y-_mm": wk_y_neg,
            "wk_max_mm": wk_eval_max,
            "wk_calc_unfiltered_max_mm": wk_unfiltered_max,
            "sigma_s_x+_MPa": sig_x_pos,
            "sigma_s_x-_MPa": sig_x_neg,
            "sigma_s_y+_MPa": sig_y_pos,
            "sigma_s_y-_MPa": sig_y_neg,
            "phi_ctrl_x+_mm": crack_x_pos["phi_control_mm"],
            "phi_ctrl_x-_mm": crack_x_neg["phi_control_mm"],
            "phi_ctrl_y+_mm": crack_y_pos["phi_control_mm"],
            "phi_ctrl_y-_mm": crack_y_neg["phi_control_mm"],
            "s_eff_x+_mm": crack_x_pos["s_eff_mm"],
            "s_eff_x-_mm": crack_x_neg["s_eff_mm"],
            "s_eff_y+_mm": crack_y_pos["s_eff_mm"],
            "s_eff_y-_mm": crack_y_neg["s_eff_mm"],
            "c_eff_x+_mm": crack_x_pos["c_eff_mm"],
            "c_eff_x-_mm": crack_x_neg["c_eff_mm"],
            "c_eff_y+_mm": crack_y_pos["c_eff_mm"],
            "c_eff_y-_mm": crack_y_neg["c_eff_mm"],
            "phi_eq_x+_mm": crack_x_pos["phi_eq_mm"],
            "phi_eq_x-_mm": crack_x_neg["phi_eq_mm"],
            "phi_eq_y+_mm": crack_y_pos["phi_eq_mm"],
            "phi_eq_y-_mm": crack_y_neg["phi_eq_mm"],
            "phi_lim_x+_EC2_mm": crack_x_pos["phi_lim_EC2_mm"],
            "phi_lim_x-_EC2_mm": crack_x_neg["phi_lim_EC2_mm"],
            "phi_lim_y+_EC2_mm": crack_y_pos["phi_lim_EC2_mm"],
            "phi_lim_y-_EC2_mm": crack_y_neg["phi_lim_EC2_mm"],
            "s_lim_x+_EC2_mm": crack_x_pos["s_lim_EC2_mm"],
            "s_lim_x-_EC2_mm": crack_x_neg["s_lim_EC2_mm"],
            "s_lim_y+_EC2_mm": crack_y_pos["s_lim_EC2_mm"],
            "s_lim_y-_EC2_mm": crack_y_neg["s_lim_EC2_mm"],
            "sr_max_x+_mm": sr_x_pos,
            "sr_max_x-_mm": sr_x_neg,
            "sr_max_y+_mm": sr_y_pos,
            "sr_max_y-_mm": sr_y_neg,
            "x_cr_x+_mm": crack_x_pos["x_cr_mm"],
            "x_cr_x-_mm": crack_x_neg["x_cr_mm"],
            "x_cr_y+_mm": crack_y_pos["x_cr_mm"],
            "x_cr_y-_mm": crack_y_neg["x_cr_mm"],
            "h_ceff_x+_mm": crack_x_pos["h_ceff_mm"],
            "h_ceff_x-_mm": crack_x_neg["h_ceff_mm"],
            "h_ceff_y+_mm": crack_y_pos["h_ceff_mm"],
            "h_ceff_y-_mm": crack_y_neg["h_ceff_mm"],
            "Ac_eff_x+_mm2": crack_x_pos["Ac_eff_mm2"],
            "Ac_eff_x-_mm2": crack_x_neg["Ac_eff_mm2"],
            "Ac_eff_y+_mm2": crack_y_pos["Ac_eff_mm2"],
            "Ac_eff_y-_mm2": crack_y_neg["Ac_eff_mm2"],
            "rho_p_eff_x+": crack_x_pos["rho_p_eff"],
            "rho_p_eff_x-": crack_x_neg["rho_p_eff"],
            "rho_p_eff_y+": crack_y_pos["rho_p_eff"],
            "rho_p_eff_y-": crack_y_neg["rho_p_eff"],
            "eps_diff_x+": crack_x_pos["eps_sm_minus_eps_cm"],
            "eps_diff_x-": crack_x_neg["eps_sm_minus_eps_cm"],
            "eps_diff_y+": crack_y_pos["eps_sm_minus_eps_cm"],
            "eps_diff_y-": crack_y_neg["eps_sm_minus_eps_cm"],
            "Crack_status_x+": crack_x_pos["Status"],
            "Crack_status_x-": crack_x_neg["Status"],
            "Crack_status_y+": crack_y_pos["Status"],
            "Crack_status_y-": crack_y_neg["Status"],
            "Crack_reason_x+": crack_x_pos["Reason"],
            "Crack_reason_x-": crack_x_neg["Reason"],
            "Crack_reason_y+": crack_y_pos["Reason"],
            "Crack_reason_y-": crack_y_neg["Reason"],
            "wmax_mm": self.wmax_mm,
            "Crack_control_status": crack_status,
            "Crack_control_note": crack_note,
            "Status": status,
            "Verification_reason": verification_reason,
            "Recommended_action": recommended_action,
            "Notes": "; ".join(notes),
        }

    def _automatic_statistical_local_nodes(self, grp: pd.DataFrame) -> Tuple[set, Dict[str, object]]:
        """Identifica concentrações nodais muito localizadas para separar o envelope distribuído.

        Este é um pós-processamento estatístico, não uma regra do EC2. Só actua quando:
        - o utilizador selecciona ``P99 nodal + RAW local``;
        - existem pelo menos 100 nós no painel;
        - max/P95 excede o limiar geral de pico;
        - max/P99 é ainda >= ao limiar adicional;
        - menos de ``auto_peak_max_fraction`` dos nós atingem 90% do máximo.

        Os nós identificados NÃO desaparecem: ficam integralmente no resultado RAW e passam
        para estado ``Verificar localmente``. A armadura distribuída é dimensionada com as
        restantes linhas. Sem geometria, esta separação nunca produz OK global definitivo.
        """
        policy = normalize_text(self.distributed_peak_policy)
        if "p99" not in policy:
            return set(), {"applied": False, "reason": "política RAW integral", "directions": {}}
        if grp is None or grp.empty or "Node" not in grp.columns:
            return set(), {"applied": False, "reason": "sem nós", "directions": {}}
        g = grp[grp["Case_classification"].astype(str) == "ELU"].copy() if "Case_classification" in grp.columns else grp.copy()
        if g.empty:
            return set(), {"applied": False, "reason": "sem ELU", "directions": {}}
        node_ids = g["Node"].map(canonical_node_id)
        n_nodes = int(node_ids.nunique())
        if n_nodes < 100:
            return set(), {"applied": False, "reason": f"apenas {n_nodes} nós (<100)", "directions": {}}

        mapping = {
            "X+": "MEd_x_sup_kNm_m", "X-": "MEd_x_inf_kNm_m",
            "Y+": "MEd_y_sup_kNm_m", "Y-": "MEd_y_inf_kNm_m",
        }
        selected = set()
        details = {}
        q = self.distributed_peak_percentile
        for lab, col in mapping.items():
            if col not in g.columns:
                continue
            vals = pd.to_numeric(g[col], errors="coerce").fillna(0.0).clip(lower=0.0)
            nodal = vals.groupby(node_ids, observed=True).max()
            nodal = nodal[nodal.index.astype(str) != ""]
            if nodal.empty:
                continue
            mmax = safe_float(nodal.max(), 0.0)
            p95 = safe_float(nodal.quantile(0.95), 0.0)
            pq = safe_float(nodal.quantile(q), 0.0)
            ratio95 = mmax / p95 if p95 > 1e-9 else (999.0 if mmax > 1e-9 else 1.0)
            ratioq = mmax / pq if pq > 1e-9 else (999.0 if mmax > 1e-9 else 1.0)
            frac90 = float((nodal >= 0.90 * mmax - 1e-9).mean()) if mmax > 1e-9 else 0.0
            qualifies = bool(
                mmax > 1e-6
                and ratio95 > self.peak_ratio_threshold
                and ratioq >= self.auto_peak_ratio_p99_threshold
                and frac90 <= self.auto_peak_max_fraction + 1e-12
            )
            cand = set()
            if qualifies:
                tol = max(1e-9, 1e-9 * max(abs(pq), 1.0))
                cand = {canonical_node_id(v) for v in nodal[nodal > pq + tol].index if canonical_node_id(v)}
                selected.update(cand)
            details[lab] = {
                "Mmax_RAW": mmax, "P95_nodal": p95, "Pq_nodal": pq,
                "ratio_max_P95": ratio95, "ratio_max_Pq": ratioq,
                "frac_nodes_ge_90pct": frac90, "qualifies": qualifies,
                "n_candidate_nodes": len(cand),
            }

        # A heurística só pode representar uma zona verdadeiramente pequena do painel.
        frac_selected = len(selected) / max(n_nodes, 1)
        if selected and frac_selected > 0.05:
            return set(), {
                "applied": False, "reason": f"candidatos abrangem {frac_selected:.1%} dos nós (>5% de segurança global)",
                "directions": details, "n_nodes": n_nodes, "n_selected": len(selected),
            }
        return selected, {
            "applied": bool(selected),
            "reason": "concentração nodal robusta separada do envelope distribuído" if selected else "sem concentração elegível",
            "directions": details, "n_nodes": n_nodes, "n_selected": len(selected),
            "fraction_selected": frac_selected, "percentile": q,
        }

    def is_confirmed_singular_node(self, value: object) -> bool:
        return canonical_node_id(value) in self.singular_node_ids

    def _panel_closure_candidates(self, max_spacing: float, is_vertical_direction: bool) -> List[RebarSolution]:
        """Gera a grelha finita de soluções admissíveis usada no fecho resistente do painel.

        A rotina respeita integralmente a estratégia construtiva seleccionada. Em ``Base +
        reforços`` a base permanece fixa e só é permitida uma família adicional com o mesmo
        espaçamento. Em ``Substituir base``/dimensionamento directo são avaliadas as soluções
        uniformes da grelha configurada. Esta enumeração é pequena e é executada apenas uma vez
        por painel/face, permitindo fechar o ciclo MEd -> solução -> d real -> MRd sem depender
        de aproximações sucessivas de As,req.
        """
        out: List[RebarSolution] = []
        if self.optimize_rebar and "substituir" not in normalize_text(self.rebar_strategy):
            base = self.base_solution_for_direction(is_vertical_direction)
            ok_base, _ = self.base_solution_is_valid(base, max_spacing)
            if not ok_base:
                return [base]
            # Base isolada.
            b = RebarSolution(
                base.phi, base.spacing, base.as_prov, text_override=base.text,
                base_text=base.text, add_text="-", as_base=base.as_prov, as_add=0.0,
                minimum_valid_text=base.text, optimization_note="candidato de fecho: base fixa",
            )
            b.constructability_status, b.constructability_note, b.reinforcement_ratio_add_base = self.review_solution_constructability(b)
            out.append(b)
            # Base + uma única família intercalada com a mesma modulação.
            for phi_add in sorted(float(v) for v in self.phi_candidates):
                s = float(base.spacing)
                clear_interleaved = s / 2.0 - (float(base.phi) + phi_add) / 2.0
                min_clear = max(float(base.phi), phi_add, self.aggregate_mm + 5.0, 20.0)
                if clear_interleaved + 1e-9 < min_clear:
                    continue
                as_add = bar_area_mm2(phi_add) * 1000.0 / s
                cand = RebarSolution(
                    max(float(base.phi), phi_add), s, base.as_prov + as_add,
                    text_override=f"{base.text} + Ø{int(phi_add)}//{int(s)}",
                    base_text=base.text, add_text=f"Ø{int(phi_add)}//{int(s)}",
                    as_base=base.as_prov, as_add=as_add,
                    minimum_valid_text=f"{base.text} + Ø{int(phi_add)}//{int(s)}",
                    optimization_note="candidato de fecho resistente com base fixa",
                    reinforcement_ratio_add_base=as_add / max(base.as_prov, 1e-12),
                )
                cand.constructability_status, cand.constructability_note, cand.reinforcement_ratio_add_base = self.review_solution_constructability(cand)
                out.append(cand)
        else:
            for phi in sorted(float(v) for v in self.phi_candidates):
                for spacing in sorted(float(v) for v in self.spacing_candidates):
                    if spacing > max_spacing + 1e-9:
                        continue
                    clear = spacing - phi
                    if clear + 1e-9 < max(phi, self.aggregate_mm + 5.0, 20.0):
                        continue
                    cand = self.rebar_from_phi_spacing(phi, spacing)
                    cand.minimum_valid_text = cand.text
                    cand.optimization_note = "candidato de fecho resistente uniforme"
                    cand.constructability_status, cand.constructability_note, cand.reinforcement_ratio_add_base = self.review_solution_constructability(cand)
                    out.append(cand)
        # Remove duplicados mantendo a solução de menor As para cada texto (normalmente idêntica).
        uniq = {}
        for sol in out:
            uniq.setdefault(sol.text, sol)
        return list(uniq.values())

    def _close_panel_face_pair(self, face_sign: str, sx: RebarSolution, sy: RebarSolution,
                               g_uls: pd.DataFrame, g_qp: pd.DataFrame, g_char: pd.DataFrame,
                               sx_max: float, sy_max: float, x_is_main: bool, y_is_main: bool,
                               as_crack_min: float) -> Tuple[RebarSolution, RebarSolution]:
        """Fecha simultaneamente X/Y de uma face usando a profundidade útil física final.

        O problema que motivou a v2.15.2 era um ciclo incompleto: a selecção de armadura podia
        alterar a posição real das duas camadas, reduzir ``d`` e deixar ``MEd/MRd>1`` após a
        própria harmonização. Aqui todas as combinações construtivamente admissíveis das duas
        direcções são avaliadas com o ``d`` que elas próprias produzem. A solução escolhida deve
        satisfazer ELU; quando wk/tensão de aço ELS estavam activos, estes critérios são também
        usados para ordenar/filtrar a solução, sem transformar o limite de compressão do betão
        em falsa não conformidade automática.
        """
        face = "sup" if face_sign == "+" else "inf"
        lx, ly = "X" + face_sign, "Y" + face_sign
        mx_col = "MEd_x_sup_kNm_m" if face_sign == "+" else "MEd_x_inf_kNm_m"
        my_col = "MEd_y_sup_kNm_m" if face_sign == "+" else "MEd_y_inf_kNm_m"
        mx_uls = safe_float(g_uls[mx_col].max(), 0.0) if (not g_uls.empty and mx_col in g_uls.columns) else 0.0
        my_uls = safe_float(g_uls[my_col].max(), 0.0) if (not g_uls.empty and my_col in g_uls.columns) else 0.0
        mx_qp = safe_float(g_qp[mx_col].max(), 0.0) if (not g_qp.empty and mx_col in g_qp.columns) else 0.0
        my_qp = safe_float(g_qp[my_col].max(), 0.0) if (not g_qp.empty and my_col in g_qp.columns) else 0.0
        mx_char = safe_float(g_char[mx_col].max(), 0.0) if (not g_char.empty and mx_col in g_char.columns) else 0.0
        my_char = safe_float(g_char[my_col].max(), 0.0) if (not g_char.empty and my_col in g_char.columns) else 0.0
        cx_list = self._panel_closure_candidates(sx_max, x_is_main)
        cy_list = self._panel_closure_candidates(sy_max, y_is_main)
        _, _, as_max = self.min_slab_reinf_limits(12.0)

        candidates = []
        elu_only = []
        for cx in cx_list:
            for cy in cy_list:
                dx = self.layer_effective_depth_from_solutions(face, "X", cx, cy)
                dy = self.layer_effective_depth_from_solutions(face, "Y", cy, cx)
                if cx.as_prov + 1e-9 < max(self.slab_flexural_min_for_d(dx), as_crack_min):
                    continue
                if cy.as_prov + 1e-9 < max(self.slab_flexural_min_for_d(dy), as_crack_min):
                    continue
                if cx.as_prov > as_max + 1e-9 or cy.as_prov > as_max + 1e-9:
                    continue
                stx = self.flexural_section_state(cx.as_prov, dx)
                sty = self.flexural_section_state(cy.as_prov, dy)
                ux = mx_uls / max(float(stx["MRd_kNm_m"]), 1e-12) if mx_uls > 1e-12 else 0.0
                uy = my_uls / max(float(sty["MRd_kNm_m"]), 1e-12) if my_uls > 1e-12 else 0.0
                if ux > 1.0 + 1e-9 or uy > 1.0 + 1e-9:
                    continue

                wk_pen = 0.0
                wk_ok = True
                if self.wk_check_enabled and not g_qp.empty:
                    wx = self.crack_check_detail(mx_qp, cx, face_sign, "X", d_mm=dx)["wk_mm"] if mx_qp > 1e-12 else 0.0
                    wy = self.crack_check_detail(my_qp, cy, face_sign, "Y", d_mm=dy)["wk_mm"] if my_qp > 1e-12 else 0.0
                    wr = max(wx, wy) / max(self.wmax_mm, 1e-12)
                    wk_pen = max(0.0, wr - 0.95)
                    wk_ok = wr <= 1.0 + 1e-9

                stress_pen = 0.0
                stress_ok = True
                if self.stress_check_enabled and not g_char.empty:
                    sx_chk = self.service_stress_check_detail(mx_char, cx, "ELS-CHAR", d_mm=dx) if mx_char > 1e-12 else None
                    sy_chk = self.service_stress_check_detail(my_char, cy, "ELS-CHAR", d_mm=dy) if my_char > 1e-12 else None
                    vals = []
                    if sx_chk is not None:
                        vals.append(sx_chk["sigma_s_MPa"] / max(sx_chk["sigma_s_lim_MPa"], 1e-12))
                    if sy_chk is not None:
                        vals.append(sy_chk["sigma_s_MPa"] / max(sy_chk["sigma_s_lim_MPa"], 1e-12))
                    sr = max(vals) if vals else 0.0
                    stress_pen = max(0.0, sr - 0.95)
                    stress_ok = sr <= 1.0 + 1e-9

                construct_pen = sum(1 for z in (cx, cy) if z.constructability_status == "OK*")
                large_phi_pen = max(0.0, cx.phi - 16.0) + max(0.0, cy.phi - 16.0)
                util_peak = max(ux, uy)
                score = (construct_pen, wk_pen + stress_pen, cx.as_prov + cy.as_prov, large_phi_pen, util_peak, cx.phi + cy.phi)
                elu_only.append((score, cx, cy))
                if wk_ok and stress_ok:
                    candidates.append((score, cx, cy))

        pool = candidates if candidates else elu_only
        if pool:
            _score, bx, by = min(pool, key=lambda z: z[0])
            bx.optimization_note = (bx.optimization_note + "; " if bx.optimization_note else "") + "fecho final MEd/MRd com d físico"
            by.optimization_note = (by.optimization_note + "; " if by.optimization_note else "") + "fecho final MEd/MRd com d físico"
            return bx, by

        # Nenhuma combinação da grelha consegue fechar ELU: preservar a solução anterior, mas
        # marcar explicitamente que o limite é real e não um erro de convergência.
        for sol, lab, med in ((sx, lx, mx_uls), (sy, ly, my_uls)):
            sol.capacity_limited = True
            # Não apresentar a base isolada como se fosse uma solução adoptável quando a grelha não fecha ELU.
            # A geometria/As máximos tentados permanecem nos campos numéricos para auditoria e a alternativa
            # uniforme preliminar continua em minimum_valid_text.
            sol.text_override = "SEM SOLUÇÃO Base+reforço"
            sol.constructability_status = "Não conforme"
            sol.constructability_note = "A estratégia Base + reforço não contém solução resistente admissível na grelha configurada."
            sol.limit_note = (sol.limit_note + " | " if sol.limit_note else "") + (
                f"Fecho resistente final sem solução admissível para {lab}: MEd={med:.3f} kNm/m. "
                "A armadura base não é apresentada como solução adoptada. Rever base/Ømáx/espessura ou o significado do esforço governante."
            )
        return sx, sy

    def _panel_solution_from_envelope(self, grp: pd.DataFrame) -> Dict[str, RebarSolution]:
        """Selecciona uma única armadura por painel, face e direcção e verifica ELU+ELS.

        A solução é obtida a partir do envelope dos casos explicitamente classificados como ELU e,
        quando aplicável, do envelope da combinação ELS-QP. A mesma solução é depois usada em
        todas as linhas do painel.
        """
        g_uls = grp[grp["Case_classification"].astype(str) == "ELU"].copy()
        g_qp = grp[grp["Case_classification"].astype(str) == "ELS-QP"].copy()
        g_char = grp[grp["Case_classification"].astype(str) == "ELS-CHAR"].copy()
        panel_key = str(grp.iloc[0].get("Panel", "")) if not grp.empty else ""
        # Singularidades confirmadas pelo utilizador mantêm a política anterior.
        if self.singular_node_ids:
            if not g_uls.empty and "Node" in g_uls.columns:
                mask_singular = g_uls["Node"].map(self.is_confirmed_singular_node)
                g_uls = g_uls[~mask_singular].copy()
            if not g_qp.empty and "Node" in g_qp.columns:
                mask_singular_qp = g_qp["Node"].map(self.is_confirmed_singular_node)
                g_qp = g_qp[~mask_singular_qp].copy()
            if not g_char.empty and "Node" in g_char.columns:
                mask_singular_char = g_char["Node"].map(self.is_confirmed_singular_node)
                g_char = g_char[~mask_singular_char].copy()

        # v2.15.1: quando existe uma concentração nodal estatisticamente muito localizada,
        # separar automaticamente apenas o envelope DISTRIBUÍDO. Os valores RAW continuam
        # na tabela e exigem verificação local; sem geometria, o painel nunca recebe OK global
        # definitivo apenas por esta separação.
        auto_nodes, auto_info = self._automatic_statistical_local_nodes(grp)
        self._auto_peak_panel_info[panel_key] = {**auto_info, "nodes": set(auto_nodes)}
        if auto_nodes:
            for name, gg in (("uls", g_uls), ("qp", g_qp), ("char", g_char)):
                if not gg.empty and "Node" in gg.columns:
                    mask_auto = gg["Node"].map(lambda v: canonical_node_id(v) in auto_nodes)
                    if name == "uls":
                        g_uls = gg[~mask_auto].copy()
                    elif name == "qp":
                        g_qp = gg[~mask_auto].copy()
                    else:
                        g_char = gg[~mask_auto].copy()
            # Fail-safe: nunca aceitar uma exclusão que esvazie o envelope ELU.
            if g_uls.empty:
                g_uls = grp[grp["Case_classification"].astype(str) == "ELU"].copy()
                self._auto_peak_panel_info[panel_key] = {**auto_info, "nodes": set(), "applied": False, "reason": "filtro estatístico esvaziaria o ELU"}
                auto_nodes = set()

        as_crack_min = self.crack_min_as_per_face()
        # A solução inicial usa o pior d físico preliminar; a iteração seguinte actualiza por face.
        d0 = [
            self.layer_effective_depth("sup", "X", 12.0, 12.0),
            self.layer_effective_depth("inf", "X", 12.0, 12.0),
            self.layer_effective_depth("sup", "Y", 12.0, 12.0),
            self.layer_effective_depth("inf", "Y", 12.0, 12.0),
        ]
        as_min = max(max(self.slab_flexural_min_for_d(d) for d in d0), as_crack_min)
        x_is_main = not self.local_y_is_vertical
        y_is_main = self.local_y_is_vertical
        sx_max = self.max_spacing_for_direction(x_is_main)
        sy_max = self.max_spacing_for_direction(y_is_main)
        mapping = {
            "X+": ("MEd_x_sup_kNm_m", sx_max, x_is_main),
            "X-": ("MEd_x_inf_kNm_m", sx_max, x_is_main),
            "Y+": ("MEd_y_sup_kNm_m", sy_max, y_is_main),
            "Y-": ("MEd_y_inf_kNm_m", sy_max, y_is_main),
        }
        sols = {k: self.choose_rebar(as_min, max_spacing=v[1]) for k, v in mapping.items()}
        for _ in range(5):
            previous = {k: v.text for k, v in sols.items()}
            for face_sign in ("+", "-"):
                sx = sols["X" + face_sign]
                sy = sols["Y" + face_sign]
                dx = self.layer_effective_depth_from_solutions("sup" if face_sign == "+" else "inf", "X", sx, sy)
                dy = self.layer_effective_depth_from_solutions("sup" if face_sign == "+" else "inf", "Y", sy, sx)
                for label, d in (("X" + face_sign, dx), ("Y" + face_sign, dy)):
                    mcol, smax, ismain = mapping[label]
                    m_uls = safe_float(g_uls[mcol].max(), 0.0) if (not g_uls.empty and mcol in g_uls.columns) else 0.0
                    req = max(self.flexural_as_required(m_uls, d_mm=d), self.slab_flexural_min_for_d(d), as_crack_min)
                    sol = self.optimize_rebar_solution(req, smax, ismain, label)
                    if self.wk_check_enabled and not g_qp.empty and mcol in g_qp.columns:
                        m_qp = safe_float(g_qp[mcol].max(), 0.0)
                        sol = self.optimize_solution_for_cracking(m_qp, sol, req, smax, ismain, label, d_mm=d)
                    if self.stress_check_enabled and not g_char.empty and mcol in g_char.columns:
                        m_char = safe_float(g_char[mcol].max(), 0.0)
                        sol = self.optimize_solution_for_service_stress(m_char, sol, req, smax, label, d_mm=d)
                    sols[label] = sol
            if previous == {k: v.text for k, v in sols.items()}:
                break

        # v2.15.2: fecho resistente final com a posição física REAL das duas camadas.
        # A procura é simultânea X/Y por face e impede que uma alteração de diâmetro reduza d
        # depois da selecção e deixe MEd/MRd>1 sem nova iteração.
        for face_sign in ("+", "-"):
            sx, sy = self._close_panel_face_pair(
                face_sign, sols["X" + face_sign], sols["Y" + face_sign],
                g_uls, g_qp, g_char, sx_max, sy_max, x_is_main, y_is_main, as_crack_min,
            )
            sols["X" + face_sign] = sx
            sols["Y" + face_sign] = sy
        return sols

    def _apply_fixed_panel_solution(self, row: Dict[str, object], sols: Dict[str, RebarSolution]) -> Dict[str, object]:
        """Reavalia uma linha usando a solução harmonizada do painel."""
        r = dict(row)
        sxp, sxn, syp, syn = sols["X+"], sols["X-"], sols["Y+"], sols["Y-"]
        dxp = self.layer_effective_depth_from_solutions("sup", "X", sxp, syp)
        dyp = self.layer_effective_depth_from_solutions("sup", "Y", syp, sxp)
        dxn = self.layer_effective_depth_from_solutions("inf", "X", sxn, syn)
        dyn = self.layer_effective_depth_from_solutions("inf", "Y", syn, sxn)
        mm = {
            "X+": safe_float(r.get("MEd_x_sup_kNm_m", 0.0), 0.0),
            "X-": safe_float(r.get("MEd_x_inf_kNm_m", 0.0), 0.0),
            "Y+": safe_float(r.get("MEd_y_sup_kNm_m", 0.0), 0.0),
            "Y-": safe_float(r.get("MEd_y_inf_kNm_m", 0.0), 0.0),
        }
        ds = {"X+": dxp, "X-": dxn, "Y+": dyp, "Y-": dyn}
        solmap = {"X+": sxp, "X-": sxn, "Y+": syp, "Y-": syn}
        mrds, xds, section_states = {}, {}, {}
        utils = []
        for lab in ("X+", "X-", "Y+", "Y-"):
            fs = self.flexural_section_state(solmap[lab].as_prov, ds[lab])
            section_states[lab] = fs
            mrd = float(fs["MRd_kNm_m"]); xd = float(fs["x_d"])
            mrds[lab] = mrd; xds[lab] = xd
            utils.append(mm[lab] / mrd if mrd > 1e-9 else (999.0 if mm[lab] > 1e-9 else 0.0))
        util_m = max(utils)
        section_domain_valid = all(str(section_states[k]["section_domain_valid"]) == "Sim" for k in section_states)
        steel_yields_all_faces = all(str(section_states[k].get("steel_yields", "Não")) == "Sim" for k in section_states)
        mrd_singly_limit = min(float(section_states[k]["MRd_singly_lim_kNm_m"]) for k in section_states)

        case_class = str(r.get("Case_classification", self.classify_case(r.get("Case", ""))))

        # Performance + coerência ELS: o cálculo directo de fendilhação pertence às combinações
        # de serviço. Nas centenas de milhares de linhas ELU não há qualquer razão técnica para
        # resolver quatro secções fendilhadas que depois não entram em wk.
        def empty_crack(sol):
            geom = self.rebar_crack_geometry(sol)
            return {
                "wk_mm": float("nan"), "sigma_s_MPa": float("nan"), "sigma_c_MPa": float("nan"),
                "phi_control_mm": geom[0], "s_eff_mm": geom[1], "phi_lim_EC2_mm": float("nan"),
                "s_lim_EC2_mm": float("nan"), "x_cr_mm": float("nan"), "I_cr_mm4": float("nan"),
                "h_ceff_mm": float("nan"), "Ac_eff_mm2": float("nan"), "rho_p_eff": float("nan"),
                "alpha_e": float("nan"), "eps_sm_minus_eps_cm": float("nan"), "kt": float("nan"),
                "c_eff_mm": float("nan"), "phi_eq_mm": geom[0], "sr_max_mm": float("nan"),
                "Status": "Não avaliado", "Reason": "wk apenas em ELS-QP", "Note": "não avaliado nesta classe de combinação",
            }

        evaluate_crack = (case_class == "ELS-QP") if self.wk_check_enabled else (case_class in ("ELS-QP", "ELS-CHAR", "ELS-FREQ"))
        if evaluate_crack:
            cracks = {
                "X+": self.crack_check_detail(mm["X+"], sxp, "superior", "X", d_mm=dxp),
                "X-": self.crack_check_detail(mm["X-"], sxn, "inferior", "X", d_mm=dxn),
                "Y+": self.crack_check_detail(mm["Y+"], syp, "superior", "Y", d_mm=dyp),
                "Y-": self.crack_check_detail(mm["Y-"], syn, "inferior", "Y", d_mm=dyn),
            }
            wkmax = max(c["wk_mm"] for c in cracks.values())
        else:
            cracks = {lab: empty_crack(solmap[lab]) for lab in ("X+", "X-", "Y+", "Y-")}
            wkmax = float("nan")
        wkratio = wkmax / self.wmax_mm if (self.wmax_mm > 0 and math.isfinite(wkmax)) else float("nan")
        if not self.wk_check_enabled or case_class != "ELS-QP":
            wk_status_fixed = "Não avaliado"
        elif wkmax > self.wmax_mm + 1e-9:
            wk_status_fixed = "Não conforme"
        elif wkratio >= 0.90:
            wk_status_fixed = "OK*"
        else:
            wk_status_fixed = "OK"

        if self.stress_check_enabled and case_class in ("ELS-CHAR", "ELS-QP", "ELS-FREQ"):
            service_checks = {
                lab: self.service_stress_check_detail(mm[lab], solmap[lab], case_class, d_mm=ds[lab])
                for lab in ("X+", "X-", "Y+", "Y-")
            }
            sigma_s_service_max = max(float(v["sigma_s_MPa"]) for v in service_checks.values())
            sigma_c_service_max = max(float(v["sigma_c_MPa"]) for v in service_checks.values())
        else:
            service_checks = {lab: {"sigma_s_MPa": float("nan"), "sigma_c_MPa": float("nan"), "Status": "Não avaliado", "Note": "verificação ELS não aplicável a esta classe de combinação"} for lab in ("X+", "X-", "Y+", "Y-")}
            sigma_s_service_max = float("nan")
            sigma_c_service_max = float("nan")
        service_statuses = [str(v["Status"]) for v in service_checks.values()]
        if "Não conforme" in service_statuses:
            service_stress_status = "Não conforme"
        elif "Verificar" in service_statuses:
            service_stress_status = "Verificar"
        elif "OK*" in service_statuses:
            service_stress_status = "OK*"
        elif "OK" in service_statuses:
            service_stress_status = "OK"
        elif "Informativo" in service_statuses:
            service_stress_status = "Informativo"
        else:
            service_stress_status = "Não avaliado"
        constructability_states = [solmap[k].constructability_status for k in ("X+", "X-", "Y+", "Y-")]
        if "Não conforme" in constructability_states:
            constructability_status = "Não conforme"
        elif "Rever" in constructability_states:
            constructability_status = "Verificar"
        elif "OK*" in constructability_states:
            constructability_status = "OK*"
        else:
            constructability_status = "OK"
        constructability_note = " | ".join(dict.fromkeys([solmap[k].constructability_note for k in ("X+", "X-", "Y+", "Y-") if solmap[k].constructability_note]))

        n_ref = max(abs(safe_float(r.get("NXX_kN_m", 0.0), 0.0)), abs(safe_float(r.get("NYY_kN_m", 0.0), 0.0)), abs(safe_float(r.get("NXY_kN_m", 0.0), 0.0)))
        membrane_present = n_ref > 1e-6
        _, _, as_slab_max = self.min_slab_reinf_limits(12.0)
        max_ok = max(sxp.as_prov, sxn.as_prov, syp.as_prov, syn.as_prov) <= as_slab_max + 1e-9
        singular_confirmed = bool(case_class in ("ELU", "ELS-QP") and self.is_confirmed_singular_node(r.get("Node", "")))
        relevant = str(r.get("Design_relevant", "Sim")) != "Não"
        if singular_confirmed:
            # O esforço bruto é preservado e reavaliado com a armadura distribuída, mas o nó
            # confirmado como singular deixa de governar o envelope distribuído. O painel
            # nunca é declarado totalmente verificado por causa desta exclusão manual.
            status = "Informativo"
        elif not relevant:
            status = "Informativo"
        elif case_class == "ELU":
            if util_m > 1.0 + 1e-9 or not section_domain_valid or not max_ok:
                status = "Não conforme"
            elif membrane_present:
                status = "Verificar"
            else:
                status = "OK*" if util_m >= 0.98 else "OK"
        elif case_class == "ELS-CHAR":
            status = service_stress_status if self.stress_check_enabled else "Não avaliado"
        elif case_class == "ELS-QP":
            if self.wk_check_enabled and wkmax > self.wmax_mm + 1e-9:
                status = "Não conforme"
            elif membrane_present or service_stress_status == "Verificar":
                status = "Verificar"
            elif not self.wk_check_enabled and not self.stress_check_enabled:
                status = "Não avaliado"
            else:
                status = "OK*" if (self.wk_check_enabled and wkratio >= 0.90) else "OK"
        else:
            status = "Informativo"

        if relevant and not singular_confirmed and constructability_status == "Não conforme":
            status = "Não conforme"
        elif relevant and not singular_confirmed and status in ("OK", "OK*") and constructability_status == "Verificar":
            status = "Verificar"

        # Grandezas finais dependentes da solução única do painel. São calculadas aqui para
        # que a preparação rápida não necessite de pesquisar armadura em cada linha.
        as_main_min, as_secondary_min, as_slab_max = self.min_slab_reinf_limits(12.0)
        as_crack_min = self.crack_min_as_per_face()
        as_min_fixed = {lab: max(self.slab_flexural_min_for_d(ds[lab]), as_crack_min) for lab in ("X+", "X-", "Y+", "Y-")}
        as_req_fixed = {lab: max(self.flexural_as_required(mm[lab], d_mm=ds[lab]), as_min_fixed[lab]) for lab in ("X+", "X-", "Y+", "Y-")}
        x_is_main = not self.local_y_is_vertical
        y_is_main = self.local_y_is_vertical
        sx_max = self.max_spacing_for_direction(x_is_main)
        sy_max = self.max_spacing_for_direction(y_is_main)
        if self.wk_check_enabled and case_class == "ELS-QP":
            crack_control_status = wk_status_fixed
            crack_control_note = f"ELS-QP: wk,max={wkmax:.3f} mm; wmax={self.wmax_mm:.3f} mm."
        elif self.wk_check_enabled:
            crack_control_status = "Não avaliado"
            crack_control_note = f"wk apenas nas combinações ELS-QP {self._qp_cases_label}."
        else:
            crack_states = [str(cracks[k]["Status"]) for k in ("X+", "X-", "Y+", "Y-")]
            crack_control_status = "Verificar" if "Verificar" in crack_states else ("OK*" if "OK*" in crack_states else "OK")
            crack_control_note = "controlo de fendilhação por critérios configurados"

        r.update({
            "Panel_solution_mode": "Única por painel/face/direcção",
            "Layer_order_mode": "Ordem física configurada das malhas X/Y",
            "Bottom_outer_axis": self.bottom_outer_axis, "Top_outer_axis": self.top_outer_axis,
            "d_x_sup_mm": dxp, "d_x_inf_mm": dxn, "d_y_sup_mm": dyp, "d_y_inf_mm": dyn,
            "d_calculation_mode": "Centróide real da armadura adoptada e ordem física configurada X/Y",
            "Asx+_req_mm2_m": as_req_fixed["X+"], "Asx-_req_mm2_m": as_req_fixed["X-"],
            "Asy+_req_mm2_m": as_req_fixed["Y+"], "Asy-_req_mm2_m": as_req_fixed["Y-"],
            "As_main_min_mm2_m": max(self.slab_flexural_min_for_d(v) for v in ds.values()), "As_secondary_min_mm2_m": as_secondary_min,
            "As_slab_min_face_mm2_m": max(self.slab_flexural_min_for_d(v) for v in ds.values()), "As_crack_min_face_mm2_m": as_crack_min,
            "As_min_x+_mm2_m": as_min_fixed["X+"], "As_min_x-_mm2_m": as_min_fixed["X-"],
            "As_min_y+_mm2_m": as_min_fixed["Y+"], "As_min_y-_mm2_m": as_min_fixed["Y-"],
            "As_slab_max_mm2_m": as_slab_max, "sX_max_mm": sx_max, "sY_max_mm": sy_max,
            "phi_layer_x+_centroid_mm": self.rebar_layer_geometry(sxp)["phi_centroid_mm"],
            "phi_layer_x-_centroid_mm": self.rebar_layer_geometry(sxn)["phi_centroid_mm"],
            "phi_layer_y+_centroid_mm": self.rebar_layer_geometry(syp)["phi_centroid_mm"],
            "phi_layer_y-_centroid_mm": self.rebar_layer_geometry(syn)["phi_centroid_mm"],
            "X+_rebar": sxp.text, "X-_rebar": sxn.text, "Y+_rebar": syp.text, "Y-_rebar": syn.text,
            "X_sup_rebar": sxp.text, "X_inf_rebar": sxn.text, "Y_sup_rebar": syp.text, "Y_inf_rebar": syn.text,
            "X+_base": sxp.base_text or "-", "X-_base": sxn.base_text or "-", "Y+_base": syp.base_text or "-", "Y-_base": syn.base_text or "-",
            "X+_additional": sxp.add_text or "-", "X-_additional": sxn.add_text or "-", "Y+_additional": syp.add_text or "-", "Y-_additional": syn.add_text or "-",
            "X+_minimum_valid": sxp.minimum_valid_text or sxp.text, "X-_minimum_valid": sxn.minimum_valid_text or sxn.text,
            "Y+_minimum_valid": syp.minimum_valid_text or syp.text, "Y-_minimum_valid": syn.minimum_valid_text or syn.text,
            "X+_constructability": sxp.constructability_status, "X-_constructability": sxn.constructability_status,
            "Y+_constructability": syp.constructability_status, "Y-_constructability": syn.constructability_status,
            "X+_constructability_note": sxp.constructability_note, "X-_constructability_note": sxn.constructability_note,
            "Y+_constructability_note": syp.constructability_note, "Y-_constructability_note": syn.constructability_note,
            "X+_As_ref_base_ratio": sxp.reinforcement_ratio_add_base, "X-_As_ref_base_ratio": sxn.reinforcement_ratio_add_base,
            "Y+_As_ref_base_ratio": syp.reinforcement_ratio_add_base, "Y-_As_ref_base_ratio": syn.reinforcement_ratio_add_base,
            "X+_optimization": sxp.optimization_note, "X-_optimization": sxn.optimization_note,
            "Y+_optimization": syp.optimization_note, "Y-_optimization": syn.optimization_note,
            "Optimization_iterations": max(sxp.n_iterations, sxn.n_iterations, syp.n_iterations, syn.n_iterations),
            "Optimization_mode": (f"Harmonização/optimização — {self.rebar_strategy}" if self.optimize_rebar else "Dimensionamento automático directo — sem harmonização"),
            "Asx+_base_mm2_m": sxp.as_base, "Asx+_add_mm2_m": sxp.as_add,
            "Asx-_base_mm2_m": sxn.as_base, "Asx-_add_mm2_m": sxn.as_add,
            "Asy+_base_mm2_m": syp.as_base, "Asy+_add_mm2_m": syp.as_add,
            "Asy-_base_mm2_m": syn.as_base, "Asy-_add_mm2_m": syn.as_add,
            "Asx+_prov_mm2_m": sxp.as_prov, "Asx-_prov_mm2_m": sxn.as_prov,
            "Asy+_prov_mm2_m": syp.as_prov, "Asy-_prov_mm2_m": syn.as_prov,
            "Asx_total_mm2_m": sxp.as_prov + sxn.as_prov, "Asy_total_mm2_m": syp.as_prov + syn.as_prov,
            "MRd_x+_kNm_m": mrds["X+"], "MRd_x-_kNm_m": mrds["X-"],
            "MRd_y+_kNm_m": mrds["Y+"], "MRd_y-_kNm_m": mrds["Y-"],
            "x_d_x_sup": xds["X+"], "x_d_x_inf": xds["X-"], "x_d_y_sup": xds["Y+"], "x_d_y_inf": xds["Y-"],
            "Section_domain_valid": "Sim" if section_domain_valid else "Não",
            "MRd_singly_lim_min_kNm_m": mrd_singly_limit,
            "xi_bal_min": min(float(section_states[k]["xi_bal"]) for k in section_states),
            "steel_yields_all_faces": "Sim" if steel_yields_all_faces else "Não",
            "util_M": util_m, "util_max": util_m,
            "wk_x+_mm": cracks["X+"]["wk_mm"], "wk_x-_mm": cracks["X-"]["wk_mm"],
            "wk_y+_mm": cracks["Y+"]["wk_mm"], "wk_y-_mm": cracks["Y-"]["wk_mm"],
            "wk_max_mm": wkmax if case_class == "ELS-QP" and self.wk_check_enabled else float("nan"),
            "wmax_mm": self.wmax_mm, "Crack_control_status": crack_control_status, "Crack_control_note": crack_control_note,
            "Crack_status_x+": cracks["X+"]["Status"], "Crack_status_x-": cracks["X-"]["Status"],
            "Crack_status_y+": cracks["Y+"]["Status"], "Crack_status_y-": cracks["Y-"]["Status"],
            "Crack_reason_x+": cracks["X+"]["Reason"], "Crack_reason_x-": cracks["X-"]["Reason"],
            "Crack_reason_y+": cracks["Y+"]["Reason"], "Crack_reason_y-": cracks["Y-"]["Reason"],
            "phi_ctrl_x+_mm": cracks["X+"]["phi_control_mm"], "phi_ctrl_x-_mm": cracks["X-"]["phi_control_mm"],
            "phi_ctrl_y+_mm": cracks["Y+"]["phi_control_mm"], "phi_ctrl_y-_mm": cracks["Y-"]["phi_control_mm"],
            "s_eff_x+_mm": cracks["X+"]["s_eff_mm"], "s_eff_x-_mm": cracks["X-"]["s_eff_mm"],
            "s_eff_y+_mm": cracks["Y+"]["s_eff_mm"], "s_eff_y-_mm": cracks["Y-"]["s_eff_mm"],
            "phi_lim_x+_EC2_mm": cracks["X+"]["phi_lim_EC2_mm"], "phi_lim_x-_EC2_mm": cracks["X-"]["phi_lim_EC2_mm"],
            "phi_lim_y+_EC2_mm": cracks["Y+"]["phi_lim_EC2_mm"], "phi_lim_y-_EC2_mm": cracks["Y-"]["phi_lim_EC2_mm"],
            "s_lim_x+_EC2_mm": cracks["X+"]["s_lim_EC2_mm"], "s_lim_x-_EC2_mm": cracks["X-"]["s_lim_EC2_mm"],
            "s_lim_y+_EC2_mm": cracks["Y+"]["s_lim_EC2_mm"], "s_lim_y-_EC2_mm": cracks["Y-"]["s_lim_EC2_mm"],
            "sigma_s_x+_MPa": cracks["X+"]["sigma_s_MPa"], "sigma_s_x-_MPa": cracks["X-"]["sigma_s_MPa"],
            "sigma_s_y+_MPa": cracks["Y+"]["sigma_s_MPa"], "sigma_s_y-_MPa": cracks["Y-"]["sigma_s_MPa"],
            "sigma_c_x+_MPa": cracks["X+"]["sigma_c_MPa"], "sigma_c_x-_MPa": cracks["X-"]["sigma_c_MPa"],
            "sigma_c_y+_MPa": cracks["Y+"]["sigma_c_MPa"], "sigma_c_y-_MPa": cracks["Y-"]["sigma_c_MPa"],
            "ELS_stress_check_enabled": "Sim" if self.stress_check_enabled else "Não",
            "ELS_stress_status": service_stress_status,
            "ELS_sigma_s_max_MPa": sigma_s_service_max,
            "ELS_sigma_c_max_MPa": sigma_c_service_max,
            "ELS_sigma_s_limit_MPa": self.stress_limits["sigma_s_char_lim_MPa"],
            "ELS_sigma_c_char_limit_MPa": self.stress_limits["sigma_c_char_lim_MPa"],
            "ELS_sigma_c_qp_linear_limit_MPa": self.stress_limits["sigma_c_qp_linear_creep_lim_MPa"],
            "ELS_stress_note": " | ".join(dict.fromkeys(str(v["Note"]) for v in service_checks.values())),
            "sr_max_x+_mm": cracks["X+"]["sr_max_mm"], "sr_max_x-_mm": cracks["X-"]["sr_max_mm"],
            "sr_max_y+_mm": cracks["Y+"]["sr_max_mm"], "sr_max_y-_mm": cracks["Y-"]["sr_max_mm"],
            "x_cr_x+_mm": cracks["X+"]["x_cr_mm"], "x_cr_x-_mm": cracks["X-"]["x_cr_mm"],
            "x_cr_y+_mm": cracks["Y+"]["x_cr_mm"], "x_cr_y-_mm": cracks["Y-"]["x_cr_mm"],
            "h_ceff_x+_mm": cracks["X+"]["h_ceff_mm"], "h_ceff_x-_mm": cracks["X-"]["h_ceff_mm"],
            "h_ceff_y+_mm": cracks["Y+"]["h_ceff_mm"], "h_ceff_y-_mm": cracks["Y-"]["h_ceff_mm"],
            "Ac_eff_x+_mm2": cracks["X+"]["Ac_eff_mm2"], "Ac_eff_x-_mm2": cracks["X-"]["Ac_eff_mm2"],
            "Ac_eff_y+_mm2": cracks["Y+"]["Ac_eff_mm2"], "Ac_eff_y-_mm2": cracks["Y-"]["Ac_eff_mm2"],
            "rho_p_eff_x+": cracks["X+"]["rho_p_eff"], "rho_p_eff_x-": cracks["X-"]["rho_p_eff"],
            "rho_p_eff_y+": cracks["Y+"]["rho_p_eff"], "rho_p_eff_y-": cracks["Y-"]["rho_p_eff"],
            "c_eff_x+_mm": cracks["X+"]["c_eff_mm"], "c_eff_x-_mm": cracks["X-"]["c_eff_mm"],
            "c_eff_y+_mm": cracks["Y+"]["c_eff_mm"], "c_eff_y-_mm": cracks["Y-"]["c_eff_mm"],
            "phi_eq_x+_mm": cracks["X+"]["phi_eq_mm"], "phi_eq_x-_mm": cracks["X-"]["phi_eq_mm"],
            "phi_eq_y+_mm": cracks["Y+"]["phi_eq_mm"], "phi_eq_y-_mm": cracks["Y-"]["phi_eq_mm"],
            "eps_diff_x+": cracks["X+"]["eps_sm_minus_eps_cm"], "eps_diff_x-": cracks["X-"]["eps_sm_minus_eps_cm"],
            "eps_diff_y+": cracks["Y+"]["eps_sm_minus_eps_cm"], "eps_diff_y-": cracks["Y-"]["eps_sm_minus_eps_cm"],
            "wk_calc_unfiltered_max_mm": wkmax,
            "ELS_wk_max_mm": wkmax if case_class == "ELS-QP" and self.wk_check_enabled else float("nan"),
            "ELS_wk_ratio": wkratio if case_class == "ELS-QP" and self.wk_check_enabled else float("nan"),
            "ELS_wk_evaluated": "Sim" if case_class == "ELS-QP" and self.wk_check_enabled else "Não",
            "ELS_wk_case": r.get("Case", "") if case_class == "ELS-QP" and self.wk_check_enabled else "",
            "ELS_wk_node": r.get("Node", "") if case_class == "ELS-QP" and self.wk_check_enabled else "",
            "ELS_wk_status": wk_status_fixed,
            "ELS_wk_note": crack_control_note,
            "Constructability_status": constructability_status,
            "Constructability_note": constructability_note,
            "Rebar_limit_reached": "Sim" if any(solmap[k].capacity_limited for k in solmap) else "Não",
            "Rebar_limit_note": " | ".join(dict.fromkeys([solmap[k].limit_note for k in solmap if solmap[k].limit_note])),
            "Singular_node_confirmed": "Sim" if singular_confirmed else "Não",
            "Excluded_from_distributed_envelope": "Sim" if singular_confirmed else "Não",
            "Design_relevant": "Não" if singular_confirmed else r.get("Design_relevant", "Sim"),
            "Local_peak_util_raw": util_m if (singular_confirmed and case_class == "ELU") else float("nan"),
            "Local_peak_wk_ratio_raw": wkratio if (singular_confirmed and case_class == "ELS-QP" and self.wk_check_enabled) else float("nan"),
            "Local_peak_status": (
                ("Não conforme local" if util_m > 1.0 + 1e-9 else "OK local") if case_class == "ELU"
                else (("Não conforme local" if wkratio > 1.0 + 1e-9 else "OK local") if (case_class == "ELS-QP" and self.wk_check_enabled) else "Não avaliado local")
            ) if singular_confirmed else "Não aplicável",
            "Status": status,
        })
        if singular_confirmed:
            if case_class == "ELU":
                local_metric = f"utilização local bruta com a armadura distribuída={util_m:.3f}"
            elif case_class == "ELS-QP" and self.wk_check_enabled:
                local_metric = f"wk/wmax local bruto={wkratio:.3f}"
            else:
                local_metric = "verificação local não avaliada"
            r["Verification_reason"] = (
                f"Nó {r.get('Node','')} confirmado pelo utilizador como singularidade local e excluído do envelope distribuído; {local_metric}."
            )
            r["Recommended_action"] = (
                "Executar verificação e pormenorização local específica. A exclusão manual não equivale a conformidade estrutural do pico e permanece registada no relatório."
            )
        elif case_class == "ELU":
            if not section_domain_valid:
                r["Verification_reason"] = (f"ELU/flexão fora do domínio válido da secção simplesmente armada: "
                                              f"a armadura traccionada não atinge fyd em pelo menos uma face/direcção; utilização={util_m:.3f}.")
                r["Recommended_action"] = ("Não aumentar simplesmente As de tracção. Rever espessura/geometria ou adoptar um modelo de secção diferente; "
                                            "o SlabsEC2 não dimensiona armadura de compressão nesta versão.")
            elif not max_ok:
                r["Verification_reason"] = f"ELU: As numa face/direcção excede o limite adoptado de 0,04Ac; utilização à flexão={util_m:.3f}."
                r["Recommended_action"] = "Rever espessura, geometria e estratégia de armadura; não adoptar a solução automaticamente."
            elif membrane_present:
                r["Verification_reason"] = f"ELU/flexão com esforço de membrana presente; utilização de flexão={util_m:.3f}, mas a interação N-M não é avaliada nesta versão."
                r["Recommended_action"] = "Executar verificação N-M separada ou confirmar tecnicamente que os esforços de membrana podem ser desprezados."
            else:
                r["Verification_reason"] = f"ELU/flexão com solução harmonizada do painel: utilização={util_m:.3f}."
                if util_m <= 1.0:
                    r["Recommended_action"] = "Sem acção correctiva no âmbito de flexão considerado."
                elif r.get("Rebar_limit_reached") == "Sim":
                    r["Recommended_action"] = (
                        "A capacidade da armadura uniforme atingiu o limite Ø/s configurado; não foi ultrapassado Ømax. "
                        "Confirmar o esforço governante e, se representativo, rever espessura, limites de armadura ou solução construtiva."
                    )
                else:
                    r["Recommended_action"] = "Rever armadura/espessura ou esforços de cálculo."
        elif case_class == "ELS-CHAR" and self.stress_check_enabled:
            r["Verification_reason"] = (f"ELS característica/limitação de tensões: sigma_s,max={sigma_s_service_max:.1f} MPa; "
                                         f"sigma_c,max={sigma_c_service_max:.1f} MPa; estado={service_stress_status}.")
            r["Recommended_action"] = "Sem acção correctiva." if service_stress_status == "OK" else "Rever armadura e aplicabilidade dos limites EC2 7.2 à classe de exposição/critério de projecto."
        elif case_class == "ELS-QP":
            parts = []
            if self.wk_check_enabled:
                parts.append(f"wk={wkmax:.3f} mm; wk/wmax={wkratio:.3f}")
            if self.stress_check_enabled:
                parts.append(f"sigma_c,max={sigma_c_service_max:.1f} MPa; limite fluência linear={self.stress_limits['sigma_c_qp_linear_creep_lim_MPa']:.1f} MPa")
            if membrane_present:
                parts.append("esforço de membrana presente; interação N-M não avaliada")
            r["Verification_reason"] = "ELS-QP com solução harmonizada do painel: " + "; ".join(parts) + "."
            if membrane_present:
                r["Recommended_action"] = "Executar verificação N-M separada antes de aceitar o estado ELS."
            else:
                r["Recommended_action"] = "Sem acção correctiva no âmbito avaliado." if status in ("OK", "OK*") else "Rever fendilhação/armadura e, se sigma_c,QP exceder 0,45fck, considerar fluência não linear."
        return r

    def _compact_chunk_strings(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compacta strings dentro de um bloco antes de o acumular em memória."""
        if df is None or df.empty:
            return df
        for c in list(df.select_dtypes(include="object").columns):
            try:
                nun = int(df[c].nunique(dropna=False))
                if nun <= 5000 and nun <= max(100, int(0.50 * len(df))):
                    df[c] = df[c].astype("category")
            except Exception:
                pass
        return df

    def _concat_result_chunks_compact(self, chunks: List[pd.DataFrame]) -> pd.DataFrame:
        """Concatena blocos grandes sem expandir simultaneamente todas as strings.

        ``pandas.concat`` pode converter categorias com dicionários diferentes para ``object`` e
        multiplicar a memória por vários GB. Esta rotina concatena colunas numéricas com NumPy e
        reconstrói textos de baixa cardinalidade como categorias globais, coluna a coluna.
        """
        if not chunks:
            return pd.DataFrame()
        if len(chunks) == 1:
            return chunks[0].reset_index(drop=True)
        cols = list(chunks[0].columns)
        total = sum(len(x) for x in chunks)
        data = {}
        for c in cols:
            series = [x[c] for x in chunks]
            # Todas numéricas/bool: concatenação directa sem object arrays.
            if all(pd.api.types.is_numeric_dtype(v.dtype) or pd.api.types.is_bool_dtype(v.dtype) for v in series):
                data[c] = np.concatenate([v.to_numpy(copy=False) for v in series])
                continue
            # Texto/categoria: processar uma coluna de cada vez.
            vals = np.concatenate([v.astype(object).to_numpy(copy=False) for v in series])
            try:
                codes, uniques = pd.factorize(vals, sort=False, use_na_sentinel=True)
                if len(uniques) <= 5000 and len(uniques) <= max(100, int(0.10 * total)):
                    data[c] = pd.Categorical.from_codes(codes, categories=uniques)
                else:
                    data[c] = vals
            except Exception:
                data[c] = vals
        return pd.DataFrame(data)

    def _harmonize_panel_results_large(self, preliminary: pd.DataFrame) -> pd.DataFrame:
        """Reavaliação vectorizada para tabelas FEM >= LARGE_DATASET_THRESHOLD.

        Mantém todas as linhas e as mesmas equações do caminho detalhado, mas evita criar um
        dicionário Python com centenas de campos para cada linha. A solução continua a ser
        escolhida pelo envelope completo de cada painel e todos os ELU/ELS relevantes são
        reavaliados com essa solução.
        """
        if preliminary is None or preliminary.empty:
            return preliminary
        chunks = []
        _, _, as_max_global = self.min_slab_reinf_limits(12.0)
        for panel, grp in preliminary.groupby("Panel", dropna=False, sort=False, observed=True):
            sols = self._panel_solution_from_envelope(grp)
            sxp, sxn, syp, syn = sols["X+"], sols["X-"], sols["Y+"], sols["Y-"]
            solmap = {"X+": sxp, "X-": sxn, "Y+": syp, "Y-": syn}
            dxp = self.layer_effective_depth_from_solutions("sup", "X", sxp, syp)
            dyp = self.layer_effective_depth_from_solutions("sup", "Y", syp, sxp)
            dxn = self.layer_effective_depth_from_solutions("inf", "X", sxn, syn)
            dyn = self.layer_effective_depth_from_solutions("inf", "Y", syn, sxn)
            ds = {"X+": dxp, "X-": dxn, "Y+": dyp, "Y-": dyn}
            mcols = {"X+": "MEd_x_sup_kNm_m", "X-": "MEd_x_inf_kNm_m", "Y+": "MEd_y_sup_kNm_m", "Y-": "MEd_y_inf_kNm_m"}

            gdf = grp.copy().reset_index(drop=True)
            n = len(gdf)
            cc = gdf["Case_classification"].astype(str).to_numpy()
            moment_arrays = {lab: pd.to_numeric(gdf[col], errors="coerce").fillna(0.0).to_numpy(dtype=float, copy=False) for lab, col in mcols.items()}

            section_states = {lab: self.flexural_section_state(solmap[lab].as_prov, ds[lab]) for lab in solmap}
            mrds = {lab: float(section_states[lab]["MRd_kNm_m"]) for lab in solmap}
            xds = {lab: float(section_states[lab]["x_d"]) for lab in solmap}
            section_domain_valid = all(str(section_states[k].get("section_domain_valid", "Não")) == "Sim" for k in section_states)
            steel_yields_all = all(str(section_states[k].get("steel_yields", "Não")) == "Sim" for k in section_states)
            mrd_lim = min(float(section_states[k].get("MRd_singly_lim_kNm_m", 0.0)) for k in section_states)
            xi_bal_min = min(float(section_states[k].get("xi_bal", 0.0)) for k in section_states)

            util_components = []
            for lab in solmap:
                mrd = mrds[lab]
                util_components.append(moment_arrays[lab] / mrd if mrd > 1e-12 else np.where(moment_arrays[lab] > 1e-12, 999.0, 0.0))
            util_m = np.maximum.reduce(util_components)

            as_crack_min = self.crack_min_as_per_face()
            as_min_fixed = {lab: max(self.slab_flexural_min_for_d(ds[lab]), as_crack_min) for lab in solmap}
            as_req = {lab: np.maximum(self._flexural_as_required_array(moment_arrays[lab], ds[lab]), as_min_fixed[lab]) for lab in solmap}

            # ELS vectorizado. O estado físico é calculado para todas as linhas por operações
            # NumPy; apenas as classes ELS usam estes valores nos estados finais.
            svc = {lab: self._service_state_arrays(moment_arrays[lab], solmap[lab], ds[lab]) for lab in solmap}
            sigma_s_max = np.maximum.reduce([svc[lab]["sigma_s"] for lab in solmap])
            sigma_c_max = np.maximum.reduce([svc[lab]["sigma_c"] for lab in solmap])
            wk_dirs = [svc[lab]["wk"] for lab in solmap]
            wkmax_all = np.maximum.reduce(wk_dirs)
            qp_mask = cc == "ELS-QP"
            char_mask = cc == "ELS-CHAR"
            freq_mask = cc == "ELS-FREQ"
            elu_mask = cc == "ELU"
            service_mask = qp_mask | char_mask | freq_mask

            wkmax = np.where(qp_mask & self.wk_check_enabled, wkmax_all, np.nan)
            wkratio = np.where(qp_mask & self.wk_check_enabled & (self.wmax_mm > 0), wkmax_all / max(self.wmax_mm, 1e-12), np.nan)
            wk_status = np.full(n, "Não avaliado", dtype=object)
            if self.wk_check_enabled:
                wk_status[qp_mask & (wkmax_all > self.wmax_mm + 1e-9)] = "Não conforme"
                wk_status[qp_mask & (wkmax_all <= self.wmax_mm + 1e-9)] = "OK"
                wk_status[qp_mask & (wkmax_all <= self.wmax_mm + 1e-9) & (wkmax_all / max(self.wmax_mm, 1e-12) >= 0.90)] = "OK*"

            stress_status = np.full(n, "Não avaliado", dtype=object)
            if self.stress_check_enabled:
                lim_s = self.stress_limits["sigma_s_char_lim_MPa"]
                lim_c_char = self.stress_limits["sigma_c_char_lim_MPa"]
                lim_c_qp = self.stress_limits["sigma_c_qp_linear_creep_lim_MPa"]
                stress_status[char_mask] = "OK"
                stress_status[char_mask & (sigma_c_max > lim_c_char + 1e-9)] = "OK*"
                stress_status[char_mask & (sigma_s_max > lim_s + 1e-9)] = "Não conforme"
                stress_status[qp_mask] = "OK"
                stress_status[qp_mask & (sigma_c_max > lim_c_qp + 1e-9)] = "OK*"
                stress_status[freq_mask] = "Informativo"

            n_ref = np.maximum.reduce([
                np.abs(pd.to_numeric(gdf.get("NXX_kN_m", 0.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)),
                np.abs(pd.to_numeric(gdf.get("NYY_kN_m", 0.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)),
                np.abs(pd.to_numeric(gdf.get("NXY_kN_m", 0.0), errors="coerce").fillna(0.0).to_numpy(dtype=float)),
            ])
            membrane_present = n_ref > 1e-6
            original_relevant = gdf.get("Design_relevant", pd.Series("Sim", index=gdf.index)).astype(str).ne("Não").to_numpy()

            construct_states = [solmap[k].constructability_status for k in solmap]
            constructability_status = ("Não conforme" if "Não conforme" in construct_states else
                                       ("Verificar" if "Rever" in construct_states else
                                        ("OK*" if "OK*" in construct_states else "OK")))
            constructability_note = " | ".join(dict.fromkeys([solmap[k].constructability_note for k in solmap if solmap[k].constructability_note]))
            max_ok = max(solmap[k].as_prov for k in solmap) <= as_max_global + 1e-9

            status = np.full(n, "Informativo", dtype=object)
            rel_elu = elu_mask & original_relevant
            status[rel_elu] = "OK"
            status[rel_elu & (util_m >= 0.98)] = "OK*"
            status[rel_elu & membrane_present] = "Verificar"
            status[rel_elu & ((util_m > 1.0 + 1e-9) | (not section_domain_valid) | (not max_ok))] = "Não conforme"
            rel_char = char_mask & original_relevant
            status[rel_char] = stress_status[rel_char] if self.stress_check_enabled else "Não avaliado"
            rel_qp = qp_mask & original_relevant
            if np.any(rel_qp):
                if not self.wk_check_enabled and not self.stress_check_enabled:
                    status[rel_qp] = "Não avaliado"
                else:
                    status[rel_qp] = "OK"
                    if self.wk_check_enabled:
                        status[rel_qp & (wkratio >= 0.90)] = "OK*"
                        status[rel_qp & (wkratio > 1.0 + 1e-9)] = "Não conforme"
                    if self.stress_check_enabled:
                        status[rel_qp & (stress_status == "Verificar") & (status != "Não conforme")] = "Verificar"
                    status[rel_qp & membrane_present & (status != "Não conforme")] = "Verificar"
            if constructability_status == "Não conforme":
                status[original_relevant] = np.where(status[original_relevant] == "Não conforme", "Não conforme", "Não conforme")
            elif constructability_status == "Verificar":
                mask_upgrade = original_relevant & np.isin(status, ["OK", "OK*"])
                status[mask_upgrade] = "Verificar"

            node_vals = gdf.get("Node", pd.Series("", index=gdf.index))
            singular_mask = np.zeros(n, dtype=bool)
            if self.singular_node_ids:
                singular_mask = node_vals.map(self.is_confirmed_singular_node).to_numpy() & (elu_mask | qp_mask)
                status[singular_mask] = "Informativo"

            auto_info = self._auto_peak_panel_info.get(str(panel), {})
            auto_nodes = set(auto_info.get("nodes", set()) or set())
            if auto_nodes:
                auto_mask = node_vals.map(lambda v: canonical_node_id(v) in auto_nodes).to_numpy()
            else:
                auto_mask = np.zeros(n, dtype=bool)
            # A concentração automática é uma verificação LOCAL apenas nas classes de projecto.
            # Combinações ``Outro`` e ELS-FREQ permanecem informativas e nunca contaminam o estado global.
            auto_project_mask = auto_mask & np.isin(cc, ["ELU", "ELS-QP", "ELS-CHAR"])
            status[auto_project_mask] = "Verificar"
            excluded = singular_mask | auto_mask
            design_relevant = np.where(excluded, "Não", np.where(original_relevant, "Sim", "Não"))

            # Campos fixos da solução adoptada.
            static = {
                "d_x_sup_mm": dxp, "d_x_inf_mm": dxn, "d_y_sup_mm": dyp, "d_y_inf_mm": dyn,
                "As_main_min_mm2_m": max(self.slab_flexural_min_for_d(v) for v in ds.values()),
                "As_secondary_min_mm2_m": self.min_slab_reinf_limits(12.0)[1],
                "As_slab_min_face_mm2_m": max(self.slab_flexural_min_for_d(v) for v in ds.values()),
                "As_crack_min_face_mm2_m": as_crack_min, "As_slab_max_mm2_m": as_max_global,
                "sX_max_mm": self.max_spacing_for_direction(not self.local_y_is_vertical),
                "sY_max_mm": self.max_spacing_for_direction(self.local_y_is_vertical),
                "X+_rebar": sxp.text, "X-_rebar": sxn.text, "Y+_rebar": syp.text, "Y-_rebar": syn.text,
                "X_sup_rebar": sxp.text, "X_inf_rebar": sxn.text, "Y_sup_rebar": syp.text, "Y_inf_rebar": syn.text,
                "X+_base": sxp.base_text or "-", "X-_base": sxn.base_text or "-", "Y+_base": syp.base_text or "-", "Y-_base": syn.base_text or "-",
                "X+_additional": sxp.add_text or "-", "X-_additional": sxn.add_text or "-", "Y+_additional": syp.add_text or "-", "Y-_additional": syn.add_text or "-",
                "X+_minimum_valid": sxp.minimum_valid_text or sxp.text, "X-_minimum_valid": sxn.minimum_valid_text or sxn.text,
                "Y+_minimum_valid": syp.minimum_valid_text or syp.text, "Y-_minimum_valid": syn.minimum_valid_text or syn.text,
                "X+_constructability": sxp.constructability_status, "X-_constructability": sxn.constructability_status,
                "Y+_constructability": syp.constructability_status, "Y-_constructability": syn.constructability_status,
                "Asx+_base_mm2_m": sxp.as_base, "Asx+_add_mm2_m": sxp.as_add, "Asx-_base_mm2_m": sxn.as_base, "Asx-_add_mm2_m": sxn.as_add,
                "Asy+_base_mm2_m": syp.as_base, "Asy+_add_mm2_m": syp.as_add, "Asy-_base_mm2_m": syn.as_base, "Asy-_add_mm2_m": syn.as_add,
                "Asx+_prov_mm2_m": sxp.as_prov, "Asx-_prov_mm2_m": sxn.as_prov, "Asy+_prov_mm2_m": syp.as_prov, "Asy-_prov_mm2_m": syn.as_prov,
                "Asx_total_mm2_m": sxp.as_prov+sxn.as_prov, "Asy_total_mm2_m": syp.as_prov+syn.as_prov,
                "MRd_x+_kNm_m": mrds["X+"], "MRd_x-_kNm_m": mrds["X-"], "MRd_y+_kNm_m": mrds["Y+"], "MRd_y-_kNm_m": mrds["Y-"],
                "x_d_x_sup": xds["X+"], "x_d_x_inf": xds["X-"], "x_d_y_sup": xds["Y+"], "x_d_y_inf": xds["Y-"],
                "Section_domain_valid": "Sim" if section_domain_valid else "Não", "MRd_singly_lim_min_kNm_m": mrd_lim,
                "xi_bal_min": xi_bal_min, "steel_yields_all_faces": "Sim" if steel_yields_all else "Não",
                "ELS_stress_check_enabled": "Sim" if self.stress_check_enabled else "Não",
                "ELS_sigma_s_limit_MPa": self.stress_limits["sigma_s_char_lim_MPa"],
                "ELS_sigma_c_char_limit_MPa": self.stress_limits["sigma_c_char_lim_MPa"],
                "ELS_sigma_c_qp_linear_limit_MPa": self.stress_limits["sigma_c_qp_linear_creep_lim_MPa"],
                "Constructability_status": constructability_status,
                "Rebar_limit_reached": "Sim" if any(solmap[k].capacity_limited for k in solmap) else "Não",
                "Rebar_limit_note": " | ".join(dict.fromkeys([solmap[k].limit_note for k in solmap if solmap[k].limit_note])),
            }
            for k, v in static.items():
                gdf[k] = v
            gdf["Asx+_req_mm2_m"] = as_req["X+"]; gdf["Asx-_req_mm2_m"] = as_req["X-"]
            gdf["Asy+_req_mm2_m"] = as_req["Y+"]; gdf["Asy-_req_mm2_m"] = as_req["Y-"]
            gdf["util_M"] = util_m; gdf["util_max"] = util_m
            gdf["ELS_sigma_s_max_MPa"] = np.where(service_mask, sigma_s_max, np.nan)
            gdf["ELS_sigma_c_max_MPa"] = np.where(service_mask, sigma_c_max, np.nan)
            gdf["ELS_stress_status"] = stress_status
            gdf["wk_x+_mm"] = np.where(qp_mask & self.wk_check_enabled, svc["X+"]["wk"], np.nan)
            gdf["wk_x-_mm"] = np.where(qp_mask & self.wk_check_enabled, svc["X-"]["wk"], np.nan)
            gdf["wk_y+_mm"] = np.where(qp_mask & self.wk_check_enabled, svc["Y+"]["wk"], np.nan)
            gdf["wk_y-_mm"] = np.where(qp_mask & self.wk_check_enabled, svc["Y-"]["wk"], np.nan)
            gdf["wk_max_mm"] = wkmax; gdf["wk_calc_unfiltered_max_mm"] = wkmax
            gdf["ELS_wk_max_mm"] = wkmax; gdf["ELS_wk_ratio"] = wkratio
            gdf["ELS_wk_evaluated"] = np.where(qp_mask & self.wk_check_enabled, "Sim", "Não")
            gdf["ELS_wk_case"] = np.where(qp_mask & self.wk_check_enabled, gdf["Case"].astype(str), "")
            gdf["ELS_wk_node"] = np.where(qp_mask & self.wk_check_enabled, gdf["Node"].astype(str), "")
            gdf["ELS_wk_status"] = wk_status; gdf["Crack_control_status"] = wk_status
            for lab, suf in (("X+","x+"),("X-","x-"),("Y+","y+"),("Y-","y-")):
                qpv = qp_mask & self.wk_check_enabled
                gdf[f"sigma_s_{suf}_MPa"] = np.where(qpv, svc[lab]["sigma_s"], np.nan)
                gdf[f"sigma_c_{suf}_MPa"] = np.where(qpv, svc[lab]["sigma_c"], np.nan)
                gdf[f"sr_max_{suf}_mm"] = np.where(qpv, svc[lab]["sr_max"], np.nan)
                gdf[f"x_cr_{suf}_mm"] = np.where(qpv, svc[lab]["x_cr"], np.nan)
                gdf[f"h_ceff_{suf}_mm"] = np.where(qpv, svc[lab]["h_ceff"], np.nan)
                gdf[f"Ac_eff_{suf}_mm2"] = np.where(qpv, svc[lab]["Ac_eff"], np.nan)
                gdf[f"rho_p_eff_{suf}"] = np.where(qpv, svc[lab]["rho"], np.nan)
                gdf[f"c_eff_{suf}_mm"] = np.where(qpv, svc[lab]["c_eff"], np.nan)
                gdf[f"phi_eq_{suf}_mm"] = np.where(qpv, svc[lab]["phi"], np.nan)
                gdf[f"eps_diff_{suf}"] = np.where(qpv, svc[lab]["eps_diff"], np.nan)
                gdf[f"phi_ctrl_{suf}_mm"] = svc[lab]["phi"]
                gdf[f"s_eff_{suf}_mm"] = svc[lab]["s_eff"]
            gdf["wmax_mm"] = self.wmax_mm
            gdf["Singular_node_confirmed"] = np.where(singular_mask, "Sim", "Não")
            gdf["Excluded_from_distributed_envelope"] = np.where(excluded, "Sim", "Não")
            gdf["Design_relevant"] = design_relevant
            local_mask = singular_mask | auto_mask
            gdf["Local_peak_util_raw"] = np.where(local_mask & elu_mask, util_m, np.nan)
            gdf["Local_peak_wk_ratio_raw"] = np.where(local_mask & qp_mask & self.wk_check_enabled, wkratio, np.nan)
            gdf["Local_peak_status"] = np.where(local_mask, "Verificar localmente", "Não aplicável")
            gdf["Auto_peak_local_node"] = np.where(auto_mask, "Sim", "Não")
            gdf["Distributed_peak_policy"] = self.distributed_peak_policy
            gdf["Distributed_peak_percentile"] = self.distributed_peak_percentile
            gdf["Auto_peak_n_nodes"] = int(len(auto_nodes))
            gdf["Auto_peak_fraction_nodes"] = safe_float(auto_info.get("fraction_selected", 0.0), 0.0)
            gdf["Status"] = status

            # Diagnóstico de pico do painel, integralmente RAW.
            peak_ass = assess_panel_peak(grp, ratio_threshold=self.peak_ratio_threshold)
            p95 = safe_float(peak_ass.get("P95_kNm_m", 0.0), 0.0); p99 = safe_float(peak_ass.get("P99_kNm_m", 0.0), 0.0)
            mmax = safe_float(peak_ass.get("Mmax_kNm_m", 0.0), 0.0); ratio = safe_float(peak_ass.get("Pico_ratio_max_P95", 1.0), 1.0)
            ratio99 = safe_float(peak_ass.get("Pico_ratio_max_P99", 1.0), 1.0); flag = str(peak_ass.get("Pico_FEM", "Não"))
            mag = np.maximum.reduce([moment_arrays[k] for k in solmap])
            peak_gov = (flag == "Sim") & (np.abs(mag-mmax) <= max(1e-6, 1e-6*max(mmax,1.0)))
            gdf["FEM_peak_max_kNm_m"] = mmax; gdf["FEM_peak_p95_kNm_m"] = p95; gdf["FEM_peak_p99_kNm_m"] = p99
            gdf["FEM_peak_ratio"] = ratio; gdf["FEM_peak_ratio_p99"] = ratio99; gdf["FEM_peak_flag"] = flag
            gdf["FEM_peak_classification"] = str(peak_ass.get("Classificação_pico", ""))
            gdf["FEM_peak_node_fraction_90"] = safe_float(peak_ass.get("Frac_nós_>=90%Mmax", 0.0), 0.0)
            gdf["FEM_peak_recurrence_cases"] = int(peak_ass.get("N_casos_mesmo_nó_>=80%Mmax", 0) or 0)
            gdf["FEM_peak_governing_row"] = np.where(peak_gov, "Sim", "Não")

            # Mensagens curtas, categorizáveis, suficientes no modo massivo.
            reason = np.full(n, "Linha informativa / combinação não governante.", dtype=object)
            action = np.full(n, "Sem acção automática.", dtype=object)
            reason[elu_mask] = "ELU/flexão reavaliado com a solução distribuída do painel."
            action[elu_mask] = "Rever apenas se a utilização/estado for condicionante."
            reason[char_mask] = "ELS característica/limitação de tensões reavaliada."
            action[char_mask] = "Rever armadura e aplicabilidade dos limites se o estado for Verificar/Não conforme."
            reason[qp_mask] = "ELS quase-permanente/fendilhação reavaliada."
            action[qp_mask] = "Rever fendilhação/fluência quando indicado pelo estado."
            reason[auto_mask] = "Concentração nodal local separada apenas do envelope de armadura distribuída; esforço RAW preservado."
            action[auto_mask] = "Verificação e pormenorização local obrigatórias; a separação estatística não constitui conformidade."
            gdf["Verification_reason"] = reason; gdf["Recommended_action"] = action

            gdf = audit_design_results(
                gdf, phi_min=self.phi_min_mm, phi_max=self.phi_max_mm,
                wmax_mm=self.wmax_mm, wk_enabled=self.wk_check_enabled,
                as_max_mm2_m=as_max_global, fck=self.fck, fyk=self.fyk,
                stress_check_enabled=self.stress_check_enabled, copy_data=False,
            )
            relmask = np.isin(cc, ["ELU", "ELS-QP", "ELS-CHAR"]) & (gdf["Excluded_from_distributed_envelope"].astype(str).to_numpy() != "Sim")
            verified = "Sim" if (np.any(relmask) and not gdf.loc[relmask, "Status"].astype(str).isin(["Não conforme", "Verificar", "Não avaliado"]).any()) else "Não"
            gdf["Panel_solution_verified_all_cases"] = verified
            gdf = self._compact_chunk_strings(gdf)
            chunks.append(gdf)
        if not chunks:
            return preliminary
        return self._concat_result_chunks_compact(chunks).reset_index(drop=True)

    def harmonize_panel_results(self, preliminary: pd.DataFrame) -> pd.DataFrame:
        """Aplica a solução única do painel em blocos, mantendo todas as linhas.

        A avaliação do pico é feita sobre os momentos preliminares (que são exactamente os
        mesmos momentos usados no resultado final). A reavaliação estrutural e a auditoria são
        executadas por blocos para limitar o pico de memória em tabelas com centenas de milhares
        de linhas.
        """
        if preliminary is None or preliminary.empty:
            return preliminary
        if getattr(self, "_large_dataset_mode", False):
            return self._harmonize_panel_results_large(preliminary)
        out_chunks = []
        batch_size = 15000
        _, _, as_max = self.min_slab_reinf_limits(12.0)

        for panel, grp in preliminary.groupby("Panel", dropna=False, sort=False, observed=True):
            sols = self._panel_solution_from_envelope(grp)
            auto_info = self._auto_peak_panel_info.get(str(panel), {})
            auto_nodes = set(auto_info.get("nodes", set()) or set())
            auto_applied = bool(auto_info.get("applied", False) and auto_nodes)
            peak_ass = assess_panel_peak(grp, ratio_threshold=self.peak_ratio_threshold)
            p95 = safe_float(peak_ass.get("P95_kNm_m", 0.0), 0.0)
            mmax = safe_float(peak_ass.get("Mmax_kNm_m", 0.0), 0.0)
            ratio = safe_float(peak_ass.get("Pico_ratio_max_P95", 1.0), 1.0)
            flag = str(peak_ass.get("Pico_FEM", "Não"))
            p99 = safe_float(peak_ass.get("P99_kNm_m", 0.0), 0.0)
            ratio99 = safe_float(peak_ass.get("Pico_ratio_max_P99", 1.0), 1.0)
            peak_class = str(peak_ass.get("Classificação_pico", ""))
            peak_frac = safe_float(peak_ass.get("Frac_nós_>=90%Mmax", 0.0), 0.0)
            peak_rec = int(peak_ass.get("N_casos_mesmo_nó_>=80%Mmax", 0) or 0)
            peak_note = str(peak_ass.get("Recomendação_pico", "")) if flag == "Sim" else "Sem pico local relevante pelo critério max/P95 adoptado."

            panel_chunks = []
            panel_has_relevant = False
            panel_all_ok = True
            for start_i in range(0, len(grp), batch_size):
                sub = grp.iloc[start_i:start_i + batch_size]
                records = sub.to_dict("records")
                gdf = pd.DataFrame.from_records(self._apply_fixed_panel_solution(r, sols) for r in records)
                if gdf.empty:
                    continue

                mcols = [c for c in ["MEd_x_sup_kNm_m", "MEd_x_inf_kNm_m", "MEd_y_sup_kNm_m", "MEd_y_inf_kNm_m"] if c in gdf.columns]
                mag = gdf[mcols].abs().max(axis=1) if mcols else pd.Series(0.0, index=gdf.index)
                peak_gov = (flag == "Sim") & ((mag - mmax).abs() <= max(1e-6, 1e-6 * max(mmax, 1.0)))
                gdf["FEM_peak_max_kNm_m"] = mmax
                gdf["FEM_peak_p95_kNm_m"] = p95
                gdf["FEM_peak_p99_kNm_m"] = p99
                gdf["FEM_peak_ratio"] = ratio
                gdf["FEM_peak_ratio_p99"] = ratio99
                gdf["FEM_peak_flag"] = flag
                gdf["FEM_peak_classification"] = peak_class
                gdf["FEM_peak_node_fraction_90"] = peak_frac
                gdf["FEM_peak_recurrence_cases"] = peak_rec
                gdf["FEM_peak_governing_row"] = np.where(peak_gov, "Sim", "Não")
                gdf["FEM_peak_note"] = peak_note

                # Separação estatística automática: não altera MEd RAW; apenas impede que
                # um conjunto nodal muito localizado dimensione a armadura distribuída de
                # todo o painel. Estes nós permanecem como verificação local obrigatória.
                if auto_applied and "Node" in gdf.columns:
                    auto_mask = gdf["Node"].map(lambda v: canonical_node_id(v) in auto_nodes).to_numpy()
                else:
                    auto_mask = np.zeros(len(gdf), dtype=bool)
                gdf["Auto_peak_local_node"] = np.where(auto_mask, "Sim", "Não")
                gdf["Distributed_peak_policy"] = self.distributed_peak_policy
                gdf["Distributed_peak_percentile"] = self.distributed_peak_percentile
                gdf["Auto_peak_n_nodes"] = int(len(auto_nodes))
                gdf["Auto_peak_fraction_nodes"] = safe_float(auto_info.get("fraction_selected", 0.0), 0.0)
                if np.any(auto_mask):
                    gdf.loc[auto_mask, "Excluded_from_distributed_envelope"] = "Sim"
                    gdf.loc[auto_mask, "Design_relevant"] = "Não"
                    gdf.loc[auto_mask, "Local_peak_status"] = "Verificar localmente — separação estatística"
                    # Não transformar combinação ``Outro``/ELS-FREQ em aviso estrutural.
                    # Apenas classes de projecto recebem ``Verificar``; todas ficam RAW auditáveis.
                    auto_project_mask = auto_mask & gdf["Case_classification"].astype(str).isin(["ELU", "ELS-QP", "ELS-CHAR"]).to_numpy()
                    gdf.loc[auto_project_mask, "Status"] = "Verificar"
                    for idx in gdf.index[auto_mask]:
                        util_raw = safe_float(gdf.at[idx, "util_M"], 0.0)
                        gdf.at[idx, "Verification_reason"] = (
                            f"Nó incluído na concentração local estatística P{int(round(self.distributed_peak_percentile*100))}; "
                            f"excluído apenas do envelope de armadura distribuída. Utilização RAW com a malha distribuída={util_raw:.3f}."
                        )
                        gdf.at[idx, "Recommended_action"] = (
                            "Confirmar a zona no modelo/geométria e efectuar pormenorização local específica. "
                            "O esforço RAW não foi suavizado nem eliminado; a separação estatística não constitui verificação local."
                        )

                mask_peak_fail = (
                    peak_gov
                    & (~auto_mask)
                    & gdf["Case_classification"].astype(str).eq("ELU").to_numpy()
                    & gdf["Status"].astype(str).eq("Não conforme").to_numpy()
                )
                if np.any(mask_peak_fail):
                    for idx in gdf.index[mask_peak_fail]:
                        util = safe_float(gdf.at[idx, "util_M"], 0.0)
                        gdf.at[idx, "Verification_reason"] = (
                            f"ELU/flexão não satisfeito — condicionado por pico local potencial de esforços: "
                            f"utilização={util:.3f}; max/P95={ratio:.2f}."
                        )
                        gdf.at[idx, "Recommended_action"] = (
                            "Localizar o nó/caso governante e confirmar significado físico, malha, apoio/carga concentrada ou singularidade. "
                            "O valor não foi suavizado. Se o pico for representativo, rever armadura/espessura; se for singular, proceder à avaliação local adequada."
                        )

                gdf = audit_design_results(
                    gdf,
                    phi_min=self.phi_min_mm,
                    phi_max=self.phi_max_mm,
                    wmax_mm=self.wmax_mm,
                    wk_enabled=self.wk_check_enabled,
                    as_max_mm2_m=as_max,
                    fck=self.fck, fyk=self.fyk,
                    stress_check_enabled=self.stress_check_enabled,
                    copy_data=False,
                )

                # Modo 100k+: não acumular em memória textos extensos repetidos em todas as
                # linhas. Nenhuma grandeza numérica ou estado estrutural é removido.
                if getattr(self, "_large_dataset_mode", False):
                    drop_cols = [c for c in LARGE_VERBOSE_RESULT_COLUMNS if c in gdf.columns]
                    if drop_cols:
                        gdf.drop(columns=drop_cols, inplace=True)

                relmask = gdf["Case_classification"].astype(str).isin(["ELU", "ELS-QP", "ELS-CHAR"])
                if "Excluded_from_distributed_envelope" in gdf.columns:
                    relmask &= gdf["Excluded_from_distributed_envelope"].astype(str).ne("Sim")
                if relmask.any():
                    panel_has_relevant = True
                    if gdf.loc[relmask, "Status"].astype(str).isin(["Não conforme", "Verificar", "Não avaliado"]).any():
                        panel_all_ok = False
                if getattr(self, "_large_dataset_mode", False):
                    gdf = self._compact_chunk_strings(gdf)
                panel_chunks.append(gdf)

            verified = "Sim" if (panel_has_relevant and panel_all_ok) else "Não"
            for gdf in panel_chunks:
                if getattr(self, "_large_dataset_mode", False):
                    gdf["Panel_solution_verified_all_cases"] = pd.Categorical([verified] * len(gdf), categories=["Sim", "Não"])
                else:
                    gdf["Panel_solution_verified_all_cases"] = verified
                out_chunks.append(gdf)

        if not out_chunks:
            return preliminary
        if getattr(self, "_large_dataset_mode", False):
            return self._concat_result_chunks_compact(out_chunks).reset_index(drop=True)
        return pd.concat(out_chunks, ignore_index=True, copy=False)

    def add_cross_panel_harmonization_suggestions(self, results: pd.DataFrame, max_extra_ratio: float = 1.20) -> pd.DataFrame:
        """Sugere, sem adoptar, malhas uniformes comuns entre painéis.

        Sem informação geométrica de adjacência, o programa não altera automaticamente armaduras
        entre painéis. A sugestão é apenas construtiva: quando existe noutro painel uma solução
        uniforme da mesma bitola, ligeiramente mais forte (até ``max_extra_ratio`` de As), essa
        solução é indicada como candidata a harmonização.
        """
        if results is None or results.empty or "Panel" not in results.columns:
            return results
        # O resultado já é uma tabela final nova; acrescentar sugestões in-place evita duplicar
        # centenas de MB em modelos extensos.
        out = results
        first = out.groupby("Panel", dropna=False, sort=False, observed=True).first().reset_index()
        labels = (("X+", "Asx+_prov_mm2_m"), ("X-", "Asx-_prov_mm2_m"),
                  ("Y+", "Asy+_prov_mm2_m"), ("Y-", "Asy-_prov_mm2_m"))
        suggestions = {}
        for lab, askey in labels:
            catalog = []
            for _, row in first.iterrows():
                txt = str(row.get(lab + "_rebar", "") or "")
                fam = self._parse_rebar_text(txt)
                if len(fam) != 1 or "+" in txt:
                    continue
                _n, phi, spacing = fam[0]
                av = safe_float(row.get(askey, 0.0), 0.0)
                catalog.append((str(row.get("Panel", "")), txt, float(phi), float(spacing), av))
            for panel, txt, phi, spacing, av in catalog:
                stronger = [x for x in catalog if x[2] == phi and x[4] > av + 1e-9 and x[4] <= max_extra_ratio * max(av, 1e-9)]
                if stronger:
                    target = min(stronger, key=lambda x: x[4])
                    suggestions[(panel, lab)] = (target[1], target[4] / max(av, 1e-9))
                else:
                    suggestions[(panel, lab)] = ("-", 1.0)
        for lab, _askey in labels:
            out[lab + "_harmonization_suggestion"] = [suggestions.get((str(p), lab), ("-", 1.0))[0] for p in out["Panel"]]
            out[lab + "_harmonization_As_ratio"] = [suggestions.get((str(p), lab), ("-", 1.0))[1] for p in out["Panel"]]
        out["Cross_panel_harmonization_note"] = (
            "Sugestão apenas construtiva; não aplicada automaticamente sem confirmação de continuidade/adjacência entre painéis."
        )
        return out

    def _compact_result_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Reduz memória de strings repetitivas sem alterar valores de cálculo.

        Em tabelas FEM extensas, dezenas de colunas textuais repetem apenas alguns valores
        (estado, solução Ø/s, classe de combinação, notas padronizadas). Convertê-las para
        ``category`` reduz tipicamente a memória do resultado em várias vezes.
        """
        if df is None or df.empty or len(df) < 50000:
            return df
        # Primeiro, lista conhecida de campos naturalmente categóricos.
        categorical_cols = [
            "Panel", "Case", "Case_classification", "ULS_cases", "ELS_QP_cases",
            "ELS_Frequent_cases", "ELS_Characteristic_cases", "Moment_input_mode",
            "UGZ_unit", "Deflection_status", "Moment_unit", "Shear_unit", "Combo_type",
            "QP_crack_case", "QP_crack_cases", "wk_check_enabled", "is_QP_crack_case",
            "Equivalent_moment_source", "WA_method", "Design_relevant",
            "X+_rebar", "X-_rebar", "Y+_rebar", "Y-_rebar", "X+_base", "X-_base",
            "Y+_base", "Y-_base", "X+_additional", "X-_additional", "Y+_additional",
            "Y-_additional", "X+_minimum_valid", "X-_minimum_valid", "Y+_minimum_valid", "Y-_minimum_valid",
            "Constructability_status", "Section_domain_valid", "steel_yields_all_faces",
            "ELS_stress_check_enabled", "ELS_stress_status", "ELS_wk_evaluated",
            "ELS_wk_status", "Crack_control_status", "Singular_node_confirmed",
            "Excluded_from_distributed_envelope", "Local_peak_status", "Status",
            "FEM_peak_flag", "FEM_peak_classification", "FEM_peak_governing_row",
            "Panel_solution_verified_all_cases", "Integrity_status", "Rebar_limit_reached",
            "X+_harmonization_suggestion", "X-_harmonization_suggestion",
            "Y+_harmonization_suggestion", "Y-_harmonization_suggestion",
        ]
        for c in categorical_cols:
            if c in df.columns and str(df[c].dtype) == "object":
                try:
                    df[c] = df[c].astype("category")
                except Exception:
                    pass
        # Depois, compactar automaticamente qualquer coluna object com cardinalidade baixa.
        # Limite de 5000 evita transformar textos quase únicos em categorias dispendiosas.
        for c in list(df.select_dtypes(include="object").columns):
            try:
                nunique = int(df[c].nunique(dropna=False))
                if nunique <= 5000 and nunique <= max(100, int(0.10 * len(df))):
                    df[c] = df[c].astype("category")
            except Exception:
                pass
        return df

    def design_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        # v2.10.1: preparação vectorizada. A pesquisa de armadura é feita apenas no envelope
        # do painel; todas as linhas continuam a ser reavaliadas com a solução final.
        self._large_dataset_mode = bool(df is not None and len(df) >= LARGE_DATASET_THRESHOLD)
        preliminary = self._prepare_preliminary_dataframe_fast(df)
        if self._large_dataset_mode:
            # A preparação vectorizada contém muitos textos constantes por linha. Compactá-los
            # antes da harmonização reduz várias centenas de MB em tabelas de 300k+ linhas.
            preliminary = self._compact_chunk_strings(preliminary)
        harmonized = self.harmonize_panel_results(preliminary)
        final = self.add_cross_panel_harmonization_suggestions(harmonized)
        return self._compact_result_dtypes(final)

