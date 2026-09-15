# -*- coding: utf-8 -*-
import json
from typing import Dict
import tkinter as tk
from tkinter import filedialog, messagebox

class ConfigIOMixin:
    def _config_vars(self) -> Dict[str, tk.Variable]:
        return {
            "thickness_mm": self.var_thickness,
            "cover_mm": self.var_cover,
            "span_x_m": self.var_span_x,
            "span_y_m": self.var_span_y,
            "concrete_class": self.var_concrete,
            "steel_fyk": self.var_steel,
            "gamma_c": self.var_gamma_c,
            "gamma_s": self.var_gamma_s,
            "alpha_cc": self.var_alpha_cc,
            "aggregate_mm": self.var_aggregate_mm,
            "stress_k1": self.var_stress_k1,
            "stress_k2": self.var_stress_k2,
            "stress_k3": self.var_stress_k3,
            "local_y_is_vertical": self.var_y_vertical,
            "swap_axes": self.var_swap_axes,
            "limit_spacing_250": self.var_crack_spacing,
            "wk_check": self.var_crack_check,
            "stress_check": self.var_stress_check,
            "uls_cases": self.var_uls_cases,
            "els_characteristic_cases": self.var_els_char_cases,
            "els_frequent_cases": self.var_els_freq_cases,
            "els_qp_cases": self.var_els_qp_cases,
            "combo_type": self.var_combo_type,
            "wmax_mm": self.var_wmax,
            "moment_unit": self.var_moment_unit,
            "shear_unit": self.var_shear_unit,
            "deflection_unit": self.var_deflection_unit,
            "deflection_limit": self.var_deflection_limit,
            "negative_z_is_down": self.var_negative_z_down,
            "phi_min": self.var_phi_min,
            "phi_max": self.var_phi_max,
            "optimize_rebar": self.var_optimize_rebar,
            "rebar_strategy": self.var_rebar_strategy,
            "base_vertical_phi": self.var_base_v_phi,
            "base_vertical_spacing": self.var_base_v_spacing,
            "base_horizontal_phi": self.var_base_h_phi,
            "base_horizontal_spacing": self.var_base_h_spacing,
            "mxy_method": self.var_wa_method,
            "membrane_unit": self.var_membrane_unit,
            "positive_moment_face": self.var_positive_moment_face,
            "bottom_outer_axis": self.var_bottom_outer_axis,
            "top_outer_axis": self.var_top_outer_axis,
            "reduce_governing_cases": self.var_reduce,
            "peak_ratio_threshold": self.var_peak_ratio_threshold,
            "distributed_peak_policy": self.var_distributed_peak_policy,
            "singular_nodes": self.var_singular_nodes,
            "geometry_local_design": self.var_geometry_local_design,
            "local_zone_factor": self.var_local_zone_factor,
        }

    def save_config(self):
        path = filedialog.asksaveasfilename(
            title="Guardar configurações",
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
        )
        if not path:
            return
        try:
            data = {k: v.get() for k, v in self._config_vars().items()}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.status_var.set(f"Configurações guardadas: {path}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def load_config(self):
        path = filedialog.askopenfilename(
            title="Carregar configurações",
            filetypes=[("JSON", "*.json"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            vars_map = self._config_vars()
            # Compatibilidade com configurações <= v2.2.
            if "qp_case" in data and "els_qp_cases" not in data:
                data["els_qp_cases"] = data.get("qp_case", "")
            # Compatibilidade v2.13: o método mantém a mesma formulação, apenas passa a ter
            # designação explícita Wood-Armer na v2.14.
            if str(data.get("mxy_method", "")).strip() in {"Conservativo |MXY|", "Wood-Armer completo |MXY|", "Momentos principais (diagnóstico)"}:
                data["mxy_method"] = "Wood-Armer ortogonal optimizado"
            for k, val in data.items():
                if k in vars_map:
                    vars_map[k].set(val)
            self.status_var.set(f"Configurações carregadas: {path}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

    def export_csv(self):
        if self.df_results is None or self.df_results.empty:
            messagebox.showwarning("Aviso", "Não há resultados para exportar.")
            return
        path = filedialog.asksaveasfilename(
            title="Exportar CSV",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
        )
        if not path:
            return
        try:
            self.df_results.to_csv(path, index=False, sep=";")
            self.status_var.set(f"Exportado: {path}")
        except Exception as e:
            messagebox.showerror("Erro", str(e))

