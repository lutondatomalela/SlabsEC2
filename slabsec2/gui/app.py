# -*- coding: utf-8 -*-
import math
import os
import re
import webbrowser
from datetime import datetime
from typing import Dict, Optional, Tuple
import pandas as pd
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..version import *
from ..runtime import apply_window_icon
from ..utils import safe_float
from ..importers import (
    parse_pasted_table, dataframe_to_tsv_preview, read_delimited_file_robust,
    clean_dataframe, canonical_case_id, rename_known_columns
)
from ..designer import SlabDesigner
from ..combinations import parse_case_spec, format_case_ids, find_overlaps, CombinationSpecError
from ..selftest import run_core_regression_tests
from ..validation import run_engineering_validation_suite
from ..manual_validation import run_manual_reference_validation
from ..diagnostics import assess_mxy_dominance, select_worst_els_wk_issue
from ..peaks import build_peak_assessment, build_peak_candidates, parse_node_spec, canonical_node_id, enrich_peak_assessment_spatial
from ..geometry import (
    read_geometry_file, enrich_peak_assessment_with_geometry, geometry_summary,
    build_geometry_peak_diagnostic, merge_geometry_peak_context_into_summary,
    build_geometry_local_design, merge_local_design_into_summary, build_local_design_diagnostic,
)
from ..spatial import build_spatial_rebar_zones
from ..traceability import build_governing_traceability
from .reporting import ReportExportMixin
from .config_io import ConfigIOMixin


class SlabsEC2App(ReportExportMixin, ConfigIOMixin, tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        apply_window_icon(self)
        self.geometry("1220x720")
        self.minsize(900, 560)

        self.df_raw = pd.DataFrame()
        self.df_clean = pd.DataFrame()
        self.df_results = pd.DataFrame()
        self.df_summary = pd.DataFrame()
        self.df_governing = pd.DataFrame()
        self.df_zones = pd.DataFrame()
        self.df_traceability = pd.DataFrame()
        self.df_unit_check = pd.DataFrame()
        self.df_detailed = pd.DataFrame()
        self.df_notes = pd.DataFrame()
        self.df_optimization = pd.DataFrame()
        self.df_diagnostic = pd.DataFrame()
        self.df_data_validation = pd.DataFrame()
        self.df_sketches = pd.DataFrame()
        self.df_peaks = pd.DataFrame()
        self.df_local_design = pd.DataFrame()
        self._last_designer = None
        # Contexto geométrico opcional: o núcleo ELU/ELS bruto é sempre preservado.
        self.df_geometry_nodes = pd.DataFrame()
        self.df_geometry_members = pd.DataFrame()
        self.df_geometry_walls = pd.DataFrame()
        self.df_geometry_openings = pd.DataFrame()
        self.geometry_sources = {}
        self.input_source_path = ""
        self.input_source_sheet = None

        self.var_thickness = tk.StringVar(value="200")
        self.var_cover = tk.StringVar(value="35")
        self.var_span_x = tk.StringVar(value="")
        self.var_span_y = tk.StringVar(value="")
        self.var_bottom_outer_axis = tk.StringVar(value="X")
        self.var_top_outer_axis = tk.StringVar(value="X")
        self.var_concrete = tk.StringVar(value="C30/37")
        self.var_steel = tk.StringVar(value="500")
        # Parâmetros EC2 avançados. Os valores por defeito mantêm o comportamento histórico
        # do programa; passam, desde v2.13, a ser explícitos, persistentes e auditáveis.
        self.var_gamma_c = tk.StringVar(value="1.50")
        self.var_gamma_s = tk.StringVar(value="1.15")
        self.var_alpha_cc = tk.StringVar(value="1.00")
        self.var_aggregate_mm = tk.StringVar(value="20")
        self.var_stress_k1 = tk.StringVar(value="0.60")
        self.var_stress_k2 = tk.StringVar(value="0.45")
        self.var_stress_k3 = tk.StringVar(value="0.80")
        self.var_y_vertical = tk.BooleanVar(value=True)
        self.var_swap_axes = tk.BooleanVar(value=False)
        self.var_crack_spacing = tk.BooleanVar(value=True)
        self.var_crack_check = tk.BooleanVar(value=False)
        self.var_stress_check = tk.BooleanVar(value=True)
        self.var_uls_cases = tk.StringVar(value="")
        self.var_els_char_cases = tk.StringVar(value="")
        self.var_els_freq_cases = tk.StringVar(value="")
        self.var_els_qp_cases = tk.StringVar(value="")
        # Alias temporário para compatibilidade com rotinas/configurações anteriores.
        self.var_qp_case = self.var_els_qp_cases
        self.var_combo_type = tk.StringVar(value="ELU")
        self.var_wmax = tk.StringVar(value="0.30")
        self.var_moment_unit = tk.StringVar(value="kNm/m")
        self.var_shear_unit = tk.StringVar(value="kN/m")
        self.var_membrane_unit = tk.StringVar(value="kN/m")
        self.var_positive_moment_face = tk.StringVar(value="Superior")
        self.var_deflection_unit = tk.StringVar(value="cm")
        self.var_deflection_limit = tk.StringVar(value="L/250")
        self.var_negative_z_down = tk.BooleanVar(value=True)
        self.var_phi_min = tk.StringVar(value="10")
        self.var_phi_max = tk.StringVar(value="32")
        self.var_optimize_rebar = tk.BooleanVar(value=True)
        self.var_rebar_strategy = tk.StringVar(value="Base + reforços")
        self.var_base_v_phi = tk.StringVar(value="12")
        self.var_base_v_spacing = tk.StringVar(value="200")
        self.var_base_h_phi = tk.StringVar(value="12")
        self.var_base_h_spacing = tk.StringVar(value="200")
        self.var_wa_method = tk.StringVar(value="Wood-Armer ortogonal optimizado")
        self.var_reduce = tk.BooleanVar(value=False)
        self.var_peak_ratio_threshold = tk.StringVar(value="1.50")
        self.var_distributed_peak_policy = tk.StringVar(value="P99 nodal + RAW local")
        self.var_singular_nodes = tk.StringVar(value="")
        self.var_geometry_local_design = tk.BooleanVar(value=False)
        self.var_local_zone_factor = tk.StringVar(value="2.50")
        self.status_var = tk.StringVar(value="Cole a tabela de esforços ou importe um ficheiro.")
        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_text_var = tk.StringVar(value="0%")
        self.progress_var.trace_add("write", lambda *args: self.progress_text_var.set(f"{self.progress_var.get():.0f}%"))

        self.summary_filter = tk.StringVar(value="Todos")
        self.kpi_vars: Dict[str, tk.StringVar] = {}
        self._tree_data: Dict[ttk.Treeview, pd.DataFrame] = {}
        self._tree_labels: Dict[ttk.Treeview, str] = {}
        self.detail_text = None
        self.dashboard_text = None
        self._cell_balloon = None
        self.import_source_note = ""

        self._build_ui()

    def _build_ui(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # ---- aparência geral ----
        bg = style.lookup("TFrame", "background") or "#f3f5f7"
        self.configure(background=bg)
        style.configure("TLabelframe", padding=8)
        style.configure("TLabelframe.Label", font=("Segoe UI", 9, "bold"))
        style.configure("TButton", padding=(8, 6))
        style.configure("Primary.TButton", padding=(10, 8))
        style.configure("Treeview", rowheight=24, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", font=("Segoe UI", 9, "bold"))
        style.configure("TNotebook.Tab", padding=(10, 6), font=("Segoe UI", 9))
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Subtle.TLabel", font=("Segoe UI", 8), foreground="#5f6b7a")
        style.configure("Status.TLabel", font=("Segoe UI", 9))

        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)
        self.columnconfigure(0, weight=1)

        root = ttk.Frame(self, padding=8)
        root.grid(row=0, column=0, sticky="nsew")
        root.rowconfigure(0, weight=1)
        root.columnconfigure(0, weight=1)

        paned = ttk.Panedwindow(root, orient="horizontal")
        paned.grid(row=0, column=0, sticky="nsew")

        # ---- barra lateral scrollable, mais adequada a ecrãs menores ----
        sidebar_host = ttk.Frame(paned, width=355)
        sidebar_host.pack_propagate(False)
        sidebar_host.rowconfigure(0, weight=1)
        sidebar_host.columnconfigure(0, weight=1)

        self.sidebar_canvas = tk.Canvas(sidebar_host, highlightthickness=0, borderwidth=0, background=bg)
        sb_y = ttk.Scrollbar(sidebar_host, orient="vertical", command=self.sidebar_canvas.yview)
        self.sidebar_canvas.configure(yscrollcommand=sb_y.set)
        self.sidebar_canvas.grid(row=0, column=0, sticky="nsew")
        sb_y.grid(row=0, column=1, sticky="ns")

        sidebar_inner = ttk.Frame(self.sidebar_canvas, padding=(0, 0, 6, 0))
        sidebar_window = self.sidebar_canvas.create_window((0, 0), window=sidebar_inner, anchor="nw")

        def _sync_sidebar(_event=None):
            self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all"))
            width = self.sidebar_canvas.winfo_width()
            self.sidebar_canvas.itemconfigure(sidebar_window, width=width)

        sidebar_inner.bind("<Configure>", _sync_sidebar)
        self.sidebar_canvas.bind("<Configure>", _sync_sidebar)

        def _on_mousewheel(event):
            try:
                self.sidebar_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            except Exception:
                pass

        self.sidebar_canvas.bind("<Enter>", lambda e: self.sidebar_canvas.bind_all("<MouseWheel>", _on_mousewheel))
        self.sidebar_canvas.bind("<Leave>", lambda e: self.sidebar_canvas.unbind_all("<MouseWheel>"))

        right = ttk.Frame(paned)
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        paned.add(sidebar_host, weight=0)
        paned.add(right, weight=1)

        # ---- rodapé sempre visível ----
        bottom = ttk.Frame(self, padding=(8, 4, 8, 8))
        bottom.grid(row=1, column=0, sticky="ew")
        bottom.columnconfigure(1, weight=1)
        ttk.Label(bottom, text="Estado:", style="Header.TLabel").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(bottom, textvariable=self.status_var, style="Status.TLabel").grid(row=0, column=1, sticky="ew")
        self.progress_bottom = ttk.Progressbar(bottom, variable=self.progress_var, maximum=100, length=260)
        self.progress_bottom.grid(row=0, column=2, sticky="e", padx=(12, 6))
        ttk.Label(bottom, textvariable=self.progress_text_var, width=6, anchor="e").grid(row=0, column=3, sticky="e")

        # ---- cabeçalho compacto ----
        hero = ttk.LabelFrame(sidebar_inner, text=f"SlabsEC2 {APP_VERSION}")
        hero.pack(fill="x", pady=(0, 8))
        program_link = ttk.Label(hero, text=f"SlabsEC2 {APP_VERSION}", style="Header.TLabel", cursor="hand2")
        program_link.pack(anchor="w")
        program_link.bind("<Button-1>", lambda _e: webbrowser.open_new(GITHUB_URL))
        ttk.Label(hero, text="Dimensionamento de lajes maciças de betão armado (EC2)", style="Header.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(
            hero,
            text="Ferramenta para o dimensionamento à flexão de lajes maciças de B.A. segundo o EC2, com armaduras por metro, Wood & Armer, controlo de fendilhação e relatórios .xlsx/.pdf",
            style="Subtle.TLabel",
            wraplength=310,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        # ---- secção 1: geometria e materiais ----
        basic = ttk.LabelFrame(sidebar_inner, text="1. Geometria e materiais")
        basic.pack(fill="x", pady=(0, 8))
        self._add_label_entry(basic, "Espessura [mm]", self.var_thickness, 0)
        self._add_label_entry(basic, "Recobrimento [mm]", self.var_cover, 1)
        ttk.Label(
            basic,
            text="Nota: a profundidade útil é calculada pela posição física configurada das malhas X/Y e pelo centróide real da armadura adoptada.",
            style="Subtle.TLabel",
            wraplength=300,
            justify="left",
        ).grid(row=2, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 6))
        ttk.Label(basic, text="Classe de Betão").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            basic, textvariable=self.var_concrete, width=12, state="readonly",
            values=["C20/25", "C25/30", "C30/37", "C35/45", "C40/50", "C45/55", "C50/60", "C55/67", "C60/75", "C70/85", "C80/95", "C90/105"]
        ).grid(row=3, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(basic, text="Classe de Aço [MPa]").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(basic, textvariable=self.var_steel, width=12, state="readonly", values=["400", "500"]).grid(
            row=4, column=1, sticky="ew", padx=6, pady=4
        )
        basic.columnconfigure(1, weight=1)

        # ---- secção 1A: parâmetros EC2 avançados ----
        ec2p = ttk.LabelFrame(sidebar_inner, text="1A. Parâmetros EC2 avançados")
        ec2p.pack(fill="x", pady=(0, 8))
        self._add_label_entry(ec2p, "γc", self.var_gamma_c, 0)
        self._add_label_entry(ec2p, "γs", self.var_gamma_s, 1)
        self._add_label_entry(ec2p, "αcc", self.var_alpha_cc, 2)
        self._add_label_entry(ec2p, "Agregado dg [mm]", self.var_aggregate_mm, 3)
        self._add_label_entry(ec2p, "k1 — σc característica", self.var_stress_k1, 4)
        self._add_label_entry(ec2p, "k2 — σc quase-perm.", self.var_stress_k2, 5)
        self._add_label_entry(ec2p, "k3 — σs característica", self.var_stress_k3, 6)
        ttk.Label(
            ec2p,
            text=("Valores por defeito: γc=1,50; γs=1,15; αcc=1,00; dg=20 mm; "
                  "k1/k2/k3=0,60/0,45/0,80. Alterar apenas quando tecnicamente justificado."),
            style="Subtle.TLabel", wraplength=300, justify="left"
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 6))
        ec2p.columnconfigure(1, weight=1)

        # ---- secção 2: modelação, verificações e unidades ----
        checks = ttk.LabelFrame(sidebar_inner, text="2. Modelação e verificações")
        checks.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(checks, text="Direcção local Y = direcção principal", variable=self.var_y_vertical).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=6, pady=3
        )
        ttk.Checkbutton(checks, text="Trocar eixos locais X ↔ Y antes do cálculo", variable=self.var_swap_axes).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6, pady=3
        )
        ttk.Label(checks, text="Esforços").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_wa_method, state="readonly",
                     values=["Wood-Armer ortogonal optimizado"]).grid(
            row=2, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Checkbutton(
            checks, text="Limitar espaçamento a 250 mm nas zonas condicionantes", variable=self.var_crack_spacing
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        ttk.Checkbutton(
            checks, text="Verificar wk nas combinações quase-permanentes", variable=self.var_crack_check
        ).grid(row=4, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        ttk.Checkbutton(
            checks, text="Verificar limitação de tensões ELS (EC2 7.2)", variable=self.var_stress_check
        ).grid(row=5, column=0, columnspan=2, sticky="w", padx=6, pady=3)
        ttk.Label(checks, text="Comb. ELU").grid(row=6, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(checks, textvariable=self.var_uls_cases, width=22).grid(row=6, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(checks, text="ELS característica").grid(row=7, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(checks, textvariable=self.var_els_char_cases, width=22).grid(row=7, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(checks, text="ELS frequente").grid(row=8, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(checks, textvariable=self.var_els_freq_cases, width=22).grid(row=8, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(checks, text="ELS quase-perm.").grid(row=9, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(checks, textvariable=self.var_els_qp_cases, width=22).grid(row=9, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(
            checks,
            text='Intervalos aceites: 101-117 201-216 ou 101para117; casos isolados também são aceites.',
            style="Subtle.TLabel", wraplength=300, justify="left"
        ).grid(row=10, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 5))
        ttk.Label(checks, text="wmax [mm]").grid(row=11, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(checks, textvariable=self.var_wmax, width=14).grid(row=11, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(checks, text="Unid. momentos").grid(row=12, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_moment_unit, state="readonly",
                     values=["kNm/m", "Nmm/mm", "Nm/m", "kNmm/m"]).grid(
            row=12, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Label(checks, text="Unid. QXX/QYY").grid(row=13, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_shear_unit, state="readonly", values=["kN/m", "N/mm", "N/m"]).grid(
            row=13, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Label(checks, text="Unid. UGZ").grid(row=14, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_deflection_unit, state="readonly", values=["cm", "mm", "m"]).grid(
            row=14, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Checkbutton(checks, text="UGZ negativo = para baixo", variable=self.var_negative_z_down).grid(
            row=15, column=0, columnspan=2, sticky="w", padx=6, pady=3
        )
        ttk.Label(checks, text="Camada exterior superior").grid(row=16, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_top_outer_axis, state="readonly", values=["X", "Y"], width=8).grid(row=16, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(checks, text="Camada exterior inferior").grid(row=17, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_bottom_outer_axis, state="readonly", values=["X", "Y"], width=8).grid(row=17, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(checks, text="RAW: M>0 tracciona face").grid(row=18, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_positive_moment_face, state="readonly", values=["Superior", "Inferior"]).grid(row=18, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(checks, text="Unid. NXX/NYY/NXY").grid(row=19, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(checks, textvariable=self.var_membrane_unit, state="readonly", values=["kN/m", "N/mm", "N/m"]).grid(row=19, column=1, sticky="ew", padx=6, pady=4)
        checks.columnconfigure(1, weight=1)

        # ---- secção 3: armaduras e harmonização ----
        rebar = ttk.LabelFrame(sidebar_inner, text="3. Armaduras / harmonização")
        rebar.pack(fill="x", pady=(0, 8))
        ttk.Label(rebar, text="Ø min / Ø max [mm]").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        phi_frame = ttk.Frame(rebar)
        phi_frame.grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Entry(phi_frame, textvariable=self.var_phi_min, width=5).pack(side="left")
        ttk.Label(phi_frame, text="  /  ").pack(side="left")
        ttk.Entry(phi_frame, textvariable=self.var_phi_max, width=5).pack(side="left")
        ttk.Checkbutton(rebar, text="Harmonizar/optimizar solução", variable=self.var_optimize_rebar).grid(
            row=1, column=0, columnspan=2, sticky="w", padx=6, pady=3
        )
        ttk.Label(rebar, text="Estratégia de harmonização").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(rebar, textvariable=self.var_rebar_strategy, state="readonly",
                     values=["Substituir base", "Base + reforços"]).grid(
            row=2, column=1, sticky="ew", padx=6, pady=4
        )
        ttk.Label(rebar, text="Base direcção principal Ø//s").grid(row=3, column=0, sticky="w", padx=6, pady=4)
        basev = ttk.Frame(rebar)
        basev.grid(row=3, column=1, sticky="ew", padx=6, pady=4)
        ttk.Entry(basev, textvariable=self.var_base_v_phi, width=5).pack(side="left")
        ttk.Label(basev, text=" // ").pack(side="left")
        ttk.Entry(basev, textvariable=self.var_base_v_spacing, width=6).pack(side="left")
        ttk.Label(rebar, text="Base direcção secundária Ø//s").grid(row=4, column=0, sticky="w", padx=6, pady=4)
        baseh = ttk.Frame(rebar)
        baseh.grid(row=4, column=1, sticky="ew", padx=6, pady=4)
        ttk.Entry(baseh, textvariable=self.var_base_h_phi, width=5).pack(side="left")
        ttk.Label(baseh, text=" // ").pack(side="left")
        ttk.Entry(baseh, textvariable=self.var_base_h_spacing, width=6).pack(side="left")
        ttk.Checkbutton(rebar, text="Reduzir visualização (cálculo final usa todos os casos)", variable=self.var_reduce).grid(
            row=5, column=0, columnspan=2, sticky="w", padx=6, pady=3
        )
        rebar.columnconfigure(1, weight=1)

        # ---- secção 4: picos FEM / singularidades ----
        peaks = ttk.LabelFrame(sidebar_inner, text="4. Picos FEM / singularidades")
        peaks.pack(fill="x", pady=(0, 8))
        ttk.Label(peaks, text="Limiar max/P95").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(peaks, textvariable=self.var_peak_ratio_threshold, width=10).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(peaks, text="Envelope distribuído").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        ttk.Combobox(
            peaks, textvariable=self.var_distributed_peak_policy, state="readonly",
            values=["P99 nodal + RAW local", "RAW integral"]
        ).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(peaks, text="Nós singulares confirmados").grid(row=2, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(peaks, textvariable=self.var_singular_nodes, width=22).grid(row=2, column=1, sticky="ew", padx=6, pady=4)
        ttk.Label(
            peaks,
            text=("P99 nodal + RAW local separa apenas concentrações muito localizadas (<~1% dos nós por direcção) do envelope distribuído. "
                  "Os valores RAW não são apagados: passam a verificação local obrigatória. RAW integral mantém o comportamento conservador anterior. "
                  "Nós confirmados manualmente continuam disponíveis para singularidades conhecidas."),
            style="Subtle.TLabel", wraplength=300, justify="left"
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=6, pady=(0, 5))
        peaks.columnconfigure(1, weight=1)

        # ---- secção 5: contexto geométrico opcional ----
        geo = ttk.LabelFrame(sidebar_inner, text="5. Geometria opcional")
        geo.pack(fill="x", pady=(0, 8))
        ttk.Label(
            geo,
            text=("Opcional. Os esforços FEM brutos nunca são modificados. Quando activado, o contexto geométrico pode separar armadura distribuída e armadura local."),
            style="Subtle.TLabel", wraplength=300, justify="left"
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 5))
        ttk.Checkbutton(
            geo, text="Usar contexto geométrico no dimensionamento local",
            variable=self.var_geometry_local_design
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 3))
        ttk.Label(geo, text="Factor de largura local × malha").grid(row=2, column=0, sticky="w", padx=6, pady=3)
        ttk.Entry(geo, textvariable=self.var_local_zone_factor, width=9).grid(row=2, column=1, sticky="ew", padx=6, pady=3)
        geo_btns = [
            ("Importar nós", lambda: self.import_geometry_file("nodes")),
            ("Importar vigas/pilares", lambda: self.import_geometry_file("members")),
            ("Importar paredes", lambda: self.import_geometry_file("walls")),
            ("Adicionar abertura/negativo", lambda: self.import_geometry_file("openings")),
        ]
        for i, (txt, cmd) in enumerate(geo_btns):
            ttk.Button(geo, text=txt, command=cmd).grid(row=3+i//2, column=i%2, sticky="ew", padx=4, pady=4)
        geo.columnconfigure(0, weight=1); geo.columnconfigure(1, weight=1)

        # ---- acções ----
        actions = ttk.LabelFrame(sidebar_inner, text="6. Ações")
        actions.pack(fill="x", pady=(0, 8))
        btns = [
            ("Colar área de transferência", self.paste_clipboard),
            ("Importar .xlsx/.csv", self.import_file),
            ("Calcular", self.run_design),
            ("Exportar .xlsx", self.export_excel),
            ("Relatório .pdf", self.export_pdf_report),
            ("Exportar .csv", self.export_csv),
            ("Guardar configuração", self.save_config),
            ("Carregar configuração", self.load_config),
            ("Autoteste núcleo", self.run_core_self_test),
            ("Validação técnica", self.run_engineering_validation),
            ("Validação independente", self.run_manual_reference_validation_ui),
        ]
        for i, (txt, cmd) in enumerate(btns):
            style_name = "Primary.TButton" if txt == "Calcular" else "TButton"
            ttk.Button(actions, text=txt, command=cmd, style=style_name).grid(
                row=i // 2, column=i % 2, sticky="ew", padx=4, pady=4
            )
        actions.columnconfigure(0, weight=1)
        actions.columnconfigure(1, weight=1)

        # ---- estado rápido ----
        progress_box = ttk.LabelFrame(sidebar_inner, text="7. Estado")
        progress_box.pack(fill="x", pady=(0, 8))
        ttk.Label(progress_box, textvariable=self.status_var, wraplength=310, justify="left").pack(fill="x", padx=6, pady=(4, 2))
        self.progress = ttk.Progressbar(progress_box, variable=self.progress_var, maximum=100)
        self.progress.pack(fill="x", padx=6, pady=(2, 2))
        ttk.Label(progress_box, textvariable=self.progress_text_var, anchor="e").pack(fill="x", padx=6, pady=(0, 4))

        # ---- notas rápidas mais compactas ----
        quick = ttk.LabelFrame(sidebar_inner, text="8. Notas rápidas")
        quick.pack(fill="x", pady=(0, 8))
        quick_text = (
            "• Lajes tratadas como painéis de placa.\n"
            "• Entrada preferencial: MXX+, MXX-, MYY+, MYY-; alternativa: MXX, MYY, MXY.\n"
            "• UGZ negativo = deslocamento para baixo.\n"
            "• Faixas de 1 m; momentos equivalentes importados ou Wood & Armer interno.\n"
            "• Pormenorização mínima EC2 9.3.\n"
            "• Picos FEM: detecção estatística sem suavização automática; exclusões só por confirmação explícita.\n"
            "• Nós/vigas/pilares/paredes/aberturas podem ser importados opcionalmente para contexto geométrico.\n"
            "• Punçoamento não incluído nesta versão; verificar separadamente junto a pilares/cargas concentradas."
        )
        ttk.Label(quick, text=quick_text, wraplength=310, justify="left").pack(fill="x", padx=6, pady=6)

        # ---- painel principal com tabs curtas ----
        self.nb = ttk.Notebook(right)
        nb = self.nb
        nb.grid(row=0, column=0, sticky="nsew")
        try:
            nb.enable_traversal()
        except Exception:
            pass

        self.tab_instructions = ttk.Frame(nb)
        self.tab_paste = ttk.Frame(nb)
        self.tab_dashboard = ttk.Frame(nb)
        self.tab_input = ttk.Frame(nb)
        self.tab_results = ttk.Frame(nb)
        self.tab_summary = ttk.Frame(nb)
        self.tab_governing = ttk.Frame(nb)
        self.tab_zones = ttk.Frame(nb)
        self.tab_traceability = ttk.Frame(nb)
        self.tab_optimization = ttk.Frame(nb)
        self.tab_diagnostic = ttk.Frame(nb)
        self.tab_peaks = ttk.Frame(nb)
        self.tab_geometry = ttk.Frame(nb)
        self.tab_validation = ttk.Frame(nb)
        self.tab_sketches = ttk.Frame(nb)
        self.tab_unit = ttk.Frame(nb)
        self.tab_detailed = ttk.Frame(nb)
        self.tab_notes = ttk.Frame(nb)
        tab_defs = [
            (self.tab_instructions, "Instruções"),
            (self.tab_paste, "Colar"),
            (self.tab_dashboard, "Dashboard"),
            (self.tab_input, "Tabela"),
            (self.tab_results, "Resultados"),
            (self.tab_summary, "Resumo"),
            (self.tab_governing, "Armaduras"),
            (self.tab_zones, "Zonas"),
            (self.tab_traceability, "Rastreabilidade"),
            (self.tab_optimization, "Harmonização"),
            (self.tab_diagnostic, "Diagnóstico"),
            (self.tab_peaks, "Picos FEM"),
            (self.tab_geometry, "Geometria"),
            (self.tab_validation, "Validação"),
            (self.tab_sketches, "Croquis"),
            (self.tab_unit, "Unidades"),
            (self.tab_detailed, "Detalhe"),
            (self.tab_notes, "Notas EC2"),
        ]
        for frame, title in tab_defs:
            nb.add(frame, text=title)

        self._build_instructions_tab(self.tab_instructions)
        self._build_paste_tab(self.tab_paste)
        self._build_dashboard_tab(self.tab_dashboard)
        self.tree_input = self._make_tree(self.tab_input)
        self.tree_results = self._make_tree(self.tab_results)
        self.tree_summary = self._build_summary_tab(self.tab_summary)
        self.tree_governing = self._make_tree(self.tab_governing)
        self.tree_zones = self._make_tree(self.tab_zones)
        self.tree_traceability = self._make_tree(self.tab_traceability)
        self.tree_optimization = self._make_tree(self.tab_optimization)
        self.tree_diagnostic = self._make_tree(self.tab_diagnostic)
        self.tree_peaks = self._build_peaks_tab(self.tab_peaks)
        self._build_geometry_tab(self.tab_geometry)
        self.tree_validation = self._make_tree(self.tab_validation)
        self.tree_sketches = self._make_tree(self.tab_sketches)
        self.tree_unit = self._make_tree(self.tab_unit)
        self.tree_detailed = self._make_tree(self.tab_detailed)
        self.tree_notes = self._make_tree(self.tab_notes)

        self._tree_labels.update({
            self.tree_input: "Tabela importada",
            self.tree_results: "Resultados linha a linha",
            self.tree_summary: "Resumo por painel",
            self.tree_governing: "Armaduras governantes",
            self.tree_zones: "Zonas de armadura",
            self.tree_traceability: "Rastreabilidade de governantes",
            self.tree_optimization: "Harmonização/optimização de armaduras",
            self.tree_diagnostic: "Diagnóstico",
            self.tree_peaks: "Avaliação de picos FEM",
            self.tree_geo_summary: "Contexto geométrico — resumo",
            self.tree_geo_nodes: "Contexto geométrico — nós",
            self.tree_geo_members: "Contexto geométrico — vigas/pilares",
            self.tree_geo_walls: "Contexto geométrico — paredes",
            self.tree_geo_openings: "Contexto geométrico — aberturas/negativos",
            self.tree_validation: "Validação",
            self.tree_sketches: "Croquis textuais",
            self.tree_unit: "Unidades",
            self.tree_detailed: "Detalhe técnico",
            self.tree_notes: "Notas EC2",
        })

        self.update_dashboard()

        # posição inicial da divisória pensada para ecrãs menores
        self.after(100, lambda: paned.sashpos(0, 370))

    def _build_peaks_tab(self, parent):
        """Constrói a aba de picos FEM com selecção explícita de zonas singulares."""
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(outer, padding=(6, 6, 6, 4))
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            toolbar,
            text="Seleccionar zona singular",
            command=self._open_singular_zone_dialog,
        ).pack(side="left")
        ttk.Button(
            toolbar,
            text="Remover confirmações do painel",
            command=self._clear_singular_zone_for_selected_panel,
        ).pack(side="left", padx=(6, 0))
        ttk.Label(
            toolbar,
            text="Selecção manual; o SlabsEC2 nunca exclui automaticamente um pico do envelope distribuído.",
            style="Subtle.TLabel",
        ).pack(side="left", padx=(12, 0))

        content = ttk.Frame(outer)
        content.grid(row=1, column=0, sticky="nsew")
        content.rowconfigure(0, weight=1)
        content.columnconfigure(0, weight=1)
        return self._make_tree(content)

    def _selected_peak_panel(self):
        tree = getattr(self, "tree_peaks", None)
        if tree is None:
            return None
        cols, row = self._tree_selected_row(tree)
        if row and str(row.get("Panel", "")).strip():
            return str(row.get("Panel", "")).strip()
        if self.df_peaks is not None and len(self.df_peaks) == 1 and "Panel" in self.df_peaks.columns:
            return str(self.df_peaks.iloc[0]["Panel"])
        return None

    @staticmethod
    def _sort_node_ids(values):
        def key(v):
            s = str(v)
            try:
                return (0, int(float(s)))
            except Exception:
                return (1, s)
        return sorted({str(v) for v in values if str(v).strip()}, key=key)

    def _open_singular_zone_dialog(self):
        if self.df_results is None or self.df_results.empty:
            messagebox.showinfo("Zona singular", "Execute primeiro o cálculo para obter os nós candidatos.")
            return
        panel = self._selected_peak_panel()
        if panel is None:
            messagebox.showinfo("Zona singular", "Seleccione primeiro um painel na tabela 'Picos FEM'.")
            return
        candidates = build_peak_candidates(self.df_results, panel, percentile=0.99)
        if candidates is None or candidates.empty:
            messagebox.showinfo("Zona singular", f"Não foram identificados candidatos P99 no painel {panel}.")
            return

        current = parse_node_spec(self.var_singular_nodes.get())
        candidate_ids = set(candidates["Node"].astype(str))

        win = tk.Toplevel(self)
        win.title(f"Confirmar zona singular — Painel {panel}")
        win.geometry("800x560")
        win.transient(self)
        win.grab_set()

        outer = ttk.Frame(win, padding=10)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(2, weight=1)
        outer.columnconfigure(0, weight=1)

        ttk.Label(outer, text=f"Painel {panel} — candidatos estatísticos P99", style="Header.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 4)
        )
        ttk.Label(
            outer,
            text=(
                "Assinale apenas os nós que, após revisão do modelo, reconhece como pertencentes à mesma descontinuidade/singularidade física. "
                "A confirmação retira esses nós apenas do envelope de armadura distribuída; os esforços brutos e a verificação local permanecem no relatório."
            ),
            wraplength=760,
            justify="left",
        ).grid(row=1, column=0, sticky="ew", pady=(0, 8))

        host = ttk.Frame(outer)
        host.grid(row=2, column=0, sticky="nsew")
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        canvas = tk.Canvas(host, highlightthickness=0)
        vsb = ttk.Scrollbar(host, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        inner = ttk.Frame(canvas)
        w_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(w_id, width=e.width))

        vars_by_node = {}
        header = ttk.Frame(inner)
        header.pack(fill="x", pady=(0, 3))
        ttk.Label(header, text="Confirmar", width=10, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Nó", width=10, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Mmax nodal", width=16, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Caso gov.", width=20, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(header, text="% Mmax painel", width=16, font=("Segoe UI", 9, "bold")).pack(side="left")
        ttk.Label(header, text="Recorrência", width=12, font=("Segoe UI", 9, "bold")).pack(side="left")

        for _, row in candidates.iterrows():
            node = str(row.get("Node", ""))
            var = tk.BooleanVar(value=node in current)
            vars_by_node[node] = var
            line = ttk.Frame(inner)
            line.pack(fill="x", pady=1)
            ttk.Checkbutton(line, variable=var).pack(side="left", padx=(4, 34))
            ttk.Label(line, text=node, width=10).pack(side="left")
            ttk.Label(line, text=f"{safe_float(row.get('Mmax_nodal_kNm_m',0),0):.1f} kNm/m", width=16).pack(side="left")
            ttk.Label(line, text=str(row.get("Caso_governante", "")), width=20).pack(side="left")
            ttk.Label(line, text=f"{100*safe_float(row.get('Mmax_rel_panel',0),0):.1f}%", width=16).pack(side="left")
            ttk.Label(line, text=str(row.get("N_casos_>=80%Mmax_nodal", "")), width=12).pack(side="left")

        buttons = ttk.Frame(outer)
        buttons.grid(row=3, column=0, sticky="ew", pady=(10, 0))
        ttk.Label(buttons, text=f"Nós candidatos: {len(candidates)}", style="Subtle.TLabel").pack(side="left")

        def apply_selection(recalculate=False):
            selected = {node for node, var in vars_by_node.items() if var.get()}
            # A edição deste diálogo afecta apenas os candidatos apresentados para o painel;
            # confirmações de outros painéis/nós são preservadas.
            updated = (current - candidate_ids) | selected
            self.var_singular_nodes.set(" ".join(self._sort_node_ids(updated)))
            win.destroy()
            self.status_var.set(
                f"Zona singular do painel {panel} actualizada: {len(selected)} nó(s) confirmado(s). "
                "Recalcular para actualizar o envelope distribuído."
            )
            if recalculate:
                self.after(80, self.run_design)

        ttk.Button(buttons, text="Cancelar", command=win.destroy).pack(side="right")
        ttk.Button(buttons, text="Aplicar", command=lambda: apply_selection(False)).pack(side="right", padx=6)
        ttk.Button(buttons, text="Aplicar e recalcular", command=lambda: apply_selection(True), style="Primary.TButton").pack(side="right")

    def _clear_singular_zone_for_selected_panel(self):
        if self.df_results is None or self.df_results.empty:
            return
        panel = self._selected_peak_panel()
        if panel is None:
            messagebox.showinfo("Zona singular", "Seleccione primeiro um painel na tabela 'Picos FEM'.")
            return
        g = self.df_results[self.df_results["Panel"].astype(str) == str(panel)] if "Panel" in self.df_results.columns else pd.DataFrame()
        panel_nodes = {canonical_node_id(v) for v in g.get("Node", pd.Series(dtype=object)) if canonical_node_id(v)}
        current = parse_node_spec(self.var_singular_nodes.get())
        removed = current & panel_nodes
        if not removed:
            messagebox.showinfo("Zona singular", f"O painel {panel} não tem nós singulares confirmados.")
            return
        updated = current - panel_nodes
        self.var_singular_nodes.set(" ".join(self._sort_node_ids(updated)))
        self.status_var.set(
            f"Removidas {len(removed)} confirmação(ões) de singularidade do painel {panel}. Recalcular para actualizar os resultados."
        )

    def _build_geometry_tab(self, parent):
        outer = ttk.Frame(parent, padding=6)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(1, weight=1); outer.columnconfigure(0, weight=1)
        toolbar = ttk.Frame(outer)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0,6))
        for txt, kind in [("Nós", "nodes"), ("Vigas/pilares", "members"), ("Paredes", "walls"), ("Abertura/negativo", "openings")]:
            ttk.Button(toolbar, text=f"Importar {txt}", command=lambda k=kind: self.import_geometry_file(k)).pack(side="left", padx=(0,6))
        ttk.Button(toolbar, text="Limpar geometria", command=self.clear_geometry_data).pack(side="right")
        ttk.Label(
            toolbar,
            text="Esforços FEM brutos preservados; modo local opcional pode alterar a proposta de armadura distribuída/local.",
            style="Subtle.TLabel",
        ).pack(side="right", padx=10)

        geo_nb = ttk.Notebook(outer)
        geo_nb.grid(row=1, column=0, sticky="nsew")
        tabs=[]
        for title in ["Resumo","Nós","Vigas/Pilares","Paredes","Aberturas/Negativos","Dimensionamento local"]:
            f=ttk.Frame(geo_nb); geo_nb.add(f,text=title); tabs.append(f)
        self.tree_geo_summary=self._make_tree(tabs[0])
        self.tree_geo_nodes=self._make_tree(tabs[1])
        self.tree_geo_members=self._make_tree(tabs[2])
        self.tree_geo_walls=self._make_tree(tabs[3])
        self.tree_geo_openings=self._make_tree(tabs[4])
        self.tree_local_design=self._make_tree(tabs[5])
        self._refresh_geometry_views()

    def _next_opening_name(self):
        if self.df_geometry_openings is None or self.df_geometry_openings.empty or "contour" not in self.df_geometry_openings.columns:
            return "Abertura 1"
        existing=set(self.df_geometry_openings["contour"].astype(str))
        i=1
        while f"Abertura {i}" in existing:
            i += 1
        return f"Abertura {i}"

    def import_geometry_file(self, kind):
        labels={"nodes":"tabela geral de nós","members":"tabela de vigas/pilares","walls":"tabela de paredes","openings":"abertura/negativo"}
        path=filedialog.askopenfilename(
            title=f"Importar {labels.get(kind, kind)}",
            filetypes=[("Excel", "*.xlsx *.xls"), ("CSV / TXT", "*.csv *.txt"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            default_contour=self._next_opening_name() if kind == "openings" else ""
            df,note,sheet=read_geometry_file(path, kind, default_contour=default_contour)
            if df is None or df.empty:
                raise ValueError("A tabela foi lida mas não contém registos geométricos válidos.")
            if kind == "nodes":
                self.df_geometry_nodes=df
            elif kind == "members":
                self.df_geometry_members=df
            elif kind == "walls":
                self.df_geometry_walls=df
            elif kind == "openings":
                # Cada importação pode acrescentar um ou vários contornos sem apagar os anteriores.
                if self.df_geometry_openings is None or self.df_geometry_openings.empty:
                    self.df_geometry_openings=df
                else:
                    self.df_geometry_openings=pd.concat([self.df_geometry_openings, df], ignore_index=True)
                    self.df_geometry_openings=self.df_geometry_openings.drop_duplicates(subset=["contour","sequence","x","y","z"], keep="last")
            self.geometry_sources[kind]=note
            self._refresh_geometry_views()
            self._refresh_peak_geometry_context()
            self.status_var.set(f"Geometria opcional carregada — {labels.get(kind,kind)}: {len(df)} registos. {note}")
            try:
                self.nb.select(self.tab_geometry)
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível importar {labels.get(kind,kind)}.\n\nDetalhe técnico: {e}")

    def clear_geometry_data(self):
        if not messagebox.askyesno("Geometria opcional", "Remover todas as tabelas geométricas opcionais carregadas?"):
            return
        self.df_geometry_nodes=pd.DataFrame(); self.df_geometry_members=pd.DataFrame(); self.df_geometry_walls=pd.DataFrame(); self.df_geometry_openings=pd.DataFrame()
        self.geometry_sources={}
        self.df_local_design=pd.DataFrame()
        self._refresh_geometry_views(); self._refresh_peak_geometry_context()
        self.status_var.set("Contexto geométrico opcional removido. O núcleo ELU/ELS permanece inalterado.")

    def _refresh_geometry_views(self):
        if not hasattr(self, "tree_geo_summary"):
            return
        summary=geometry_summary(self.df_geometry_nodes, self.df_geometry_members, self.df_geometry_walls, self.df_geometry_openings)
        mode = pd.DataFrame([[
            "Dimensionamento local geométrico",
            f"Activo; factor={self.var_local_zone_factor.get()}×malha" if self.var_geometry_local_design.get() else "Desactivado",
            "Projecto local; esforços FEM brutos preservados" if self.var_geometry_local_design.get() else "Diagnóstico apenas",
        ]], columns=["Fonte","Quantidade","Estado"])
        summary = pd.concat([summary, mode], ignore_index=True)
        if self.geometry_sources:
            src=pd.DataFrame([["Origem "+k, v, "Informativo"] for k,v in self.geometry_sources.items()], columns=["Fonte","Quantidade","Estado"])
            summary=pd.concat([summary,src],ignore_index=True)
        self.show_df(self.tree_geo_summary, summary)
        self.show_df(self.tree_geo_nodes, self.df_geometry_nodes)
        self.show_df(self.tree_geo_members, self.df_geometry_members)
        self.show_df(self.tree_geo_walls, self.df_geometry_walls)
        self.show_df(self.tree_geo_openings, self.df_geometry_openings)
        if hasattr(self, "tree_local_design"):
            self.show_df(self.tree_local_design, self.df_local_design)

    def _refresh_peak_geometry_context(self):
        if self.df_peaks is None or self.df_peaks.empty:
            return
        # Remove eventual enriquecimento anterior antes de recalcular o contexto.
        geo_cols = {
            "Geo_disponível","Pico_X_m","Pico_Y_m","Pico_Z_m","Pico_support",
            "Pilar_próximo","Dist_pilar_m","Viga_próxima","Dist_viga_m","Dist_extremidade_viga_m",
            "Parede_próxima","Dist_parede_m","Dist_extremidade_parede_m",
            "Abertura_próxima","Dist_abertura_m","Dist_canto_abertura_m",
            "Malha_local_estimada_m","Raio_contexto_m","N_candidatos_georreferenciados",
            "Extensão_P99_X_m","Extensão_P99_Y_m","Raio_P99_m","Compacidade_P99",
            "Tipo_zona_local","Natureza_pico_geométrica","Confiança_contexto",
            "Elemento_referência","Dist_referência_m","Tratamento_recomendado_geom","Contexto_geométrico",
        }
        base_cols=[c for c in self.df_peaks.columns if c not in geo_cols]
        base=self.df_peaks[base_cols].copy()
        self.df_peaks=enrich_peak_assessment_with_geometry(
            base, self.df_geometry_nodes, self.df_geometry_members, self.df_geometry_walls, self.df_geometry_openings
        )
        # A classificação geométrica não altera os esforços brutos. O modo local opcional é processado depois,
        # separando a proposta de armadura distribuída/local de forma auditável.
        if self.df_summary is not None and not self.df_summary.empty:
            self.df_summary = merge_geometry_peak_context_into_summary(self.df_summary, self.df_peaks)
        if self.df_diagnostic is not None and not self.df_diagnostic.empty:
            if "Origem" in self.df_diagnostic.columns:
                self.df_diagnostic = self.df_diagnostic[
                    self.df_diagnostic["Origem"].astype(str) != "Geometria opcional / Picos FEM"
                ].copy()
            geo_diag = build_geometry_peak_diagnostic(self.df_peaks)
            if geo_diag is not None and not geo_diag.empty:
                self.df_diagnostic = pd.concat([self.df_diagnostic, geo_diag], ignore_index=True)
        if hasattr(self,"tree_peaks"):
            self.show_df(self.tree_peaks,self.df_peaks)
        if hasattr(self,"tree_diagnostic") and self.df_diagnostic is not None:
            self.show_df(self.tree_diagnostic, self.df_diagnostic)
        if hasattr(self, "tree_summary") and self.df_summary is not None and not self.df_summary.empty:
            try:
                self.set_summary_filter(self.summary_filter.get())
            except Exception:
                self.show_df(self.tree_summary, self.df_summary)

        if self.var_geometry_local_design.get() and self._last_designer is not None and self.df_results is not None and not self.df_results.empty:
            self._refresh_local_geometry_design()

    def _refresh_local_geometry_design(self):
        """Recalcula a proposta distribuída/local sem tocar nos esforços FEM brutos."""
        if not self.var_geometry_local_design.get():
            self.df_local_design = pd.DataFrame()
            if self.df_summary is not None and not self.df_summary.empty and "Status_global_RAW" in self.df_summary.columns:
                self.df_summary["Status_global"] = self.df_summary["Status_global_RAW"]
                if "Motivo_estado_RAW" in self.df_summary.columns:
                    self.df_summary["Motivo_estado"] = self.df_summary["Motivo_estado_RAW"]
                if "Acção_recomendada_RAW" in self.df_summary.columns:
                    self.df_summary["Acção_recomendada"] = self.df_summary["Acção_recomendada_RAW"]
            if hasattr(self, "tree_local_design"):
                self.show_df(self.tree_local_design, self.df_local_design)
            return
        if self._last_designer is None or self.df_results is None or self.df_results.empty or self.df_peaks is None or self.df_peaks.empty:
            return
        factor = max(1.0, safe_float(self.var_local_zone_factor.get(), 2.5))
        self.df_local_design = build_geometry_local_design(
            self.df_results, self.df_peaks, self.df_geometry_nodes, self.df_geometry_members,
            self.df_geometry_walls, self.df_geometry_openings, self._last_designer,
            enabled=True, zone_factor=factor,
        )
        if self.df_summary is not None and not self.df_summary.empty and self.df_local_design is not None and not self.df_local_design.empty:
            self.df_summary = merge_local_design_into_summary(self.df_summary, self.df_local_design)
        elif self.df_summary is not None and not self.df_summary.empty and "Status_global_RAW" in self.df_summary.columns:
            self.df_summary["Status_global"] = self.df_summary["Status_global_RAW"]
            if "Motivo_estado_RAW" in self.df_summary.columns:
                self.df_summary["Motivo_estado"] = self.df_summary["Motivo_estado_RAW"]
            if "Acção_recomendada_RAW" in self.df_summary.columns:
                self.df_summary["Acção_recomendada"] = self.df_summary["Acção_recomendada_RAW"]
        if self.df_diagnostic is not None and not self.df_diagnostic.empty:
            self.df_diagnostic = self.df_diagnostic[
                self.df_diagnostic.get("Origem", pd.Series(index=self.df_diagnostic.index, dtype=str)).astype(str) != "Dimensionamento local geométrico"
            ].copy()
        ldiag = build_local_design_diagnostic(self.df_local_design)
        if ldiag is not None and not ldiag.empty:
            self.df_diagnostic = pd.concat([self.df_diagnostic, ldiag], ignore_index=True) if self.df_diagnostic is not None and not self.df_diagnostic.empty else ldiag
        if hasattr(self, "tree_local_design"):
            self.show_df(self.tree_local_design, self.df_local_design)

    def _add_label_entry(self, parent, label, var, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=6, pady=4)
        ttk.Entry(parent, textvariable=var, width=14).grid(row=row, column=1, sticky="ew", padx=6, pady=4)

    def _build_dashboard_tab(self, parent):
        outer = ttk.Frame(parent, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=0)
        outer.columnconfigure(1, weight=1)
        outer.rowconfigure(1, weight=1)

        ttk.Label(outer, text="Dashboard de resultados", style="Header.TLabel").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        kpi = ttk.LabelFrame(outer, text="Síntese")
        kpi.grid(row=1, column=0, sticky="nsw", padx=(0, 10))
        labels = [
            ("linhas", "Linhas analisadas"),
            ("paineis", "Painéis"),
            ("ok", "OK"),
            ("ok_alerta", "OK com observação"),
            ("verificar", "A verificar"),
            ("nao_conforme", "Não conformes"),
            ("ugz", "UGZ desc. máx."),
            ("input", "Formato de entrada"),
        ]
        for i, (key, title) in enumerate(labels):
            ttk.Label(kpi, text=title + ":", font=("Segoe UI", 9, "bold")).grid(row=i, column=0, sticky="w", padx=6, pady=4)
            var = tk.StringVar(value="-")
            self.kpi_vars[key] = var
            ttk.Label(kpi, textvariable=var, width=22).grid(row=i, column=1, sticky="w", padx=6, pady=4)

        detail = ttk.LabelFrame(outer, text="Leitura técnica")
        detail.grid(row=1, column=1, sticky="nsew")
        detail.rowconfigure(0, weight=1)
        detail.columnconfigure(0, weight=1)
        self.dashboard_text = tk.Text(detail, wrap="word", height=20, state="disabled")
        vsb = ttk.Scrollbar(detail, orient="vertical", command=self.dashboard_text.yview)
        self.dashboard_text.configure(yscrollcommand=vsb.set)
        self.dashboard_text.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    def _build_summary_tab(self, parent):
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        toolbar = ttk.Frame(outer, padding=(6, 6, 6, 2))
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(toolbar, text="Filtro:").pack(side="left")
        for txt, val in [("Todos", "Todos"), ("OK", "OK"), ("OK*", "OK*"), ("Verificar", "Verificar"), ("Não conforme", "Não conforme")]:
            ttk.Button(toolbar, text=txt, command=lambda v=val: self.set_summary_filter(v)).pack(side="left", padx=(4, 0))
        ttk.Button(toolbar, text="Abrir detalhe", command=self._show_selected_detail).pack(side="right")

        paned = ttk.Panedwindow(outer, orient="horizontal")
        paned.grid(row=1, column=0, sticky="nsew")

        left = ttk.Frame(paned)
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        tree = ttk.Treeview(left, show="headings")
        vsb = ttk.Scrollbar(left, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(left, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        paned.add(left, weight=3)

        right = ttk.LabelFrame(paned, text="Detalhe do painel seleccionado")
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        self.detail_text = tk.Text(right, wrap="word", width=46, state="disabled")
        rvsb = ttk.Scrollbar(right, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=rvsb.set)
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        rvsb.grid(row=0, column=1, sticky="ns")
        paned.add(right, weight=1)
        self.after(150, lambda: paned.sashpos(0, max(650, int(self.winfo_width() * 0.62))))
        return tree

    def set_summary_filter(self, value: str):
        self.summary_filter.set(value)
        if self.df_summary is None or self.df_summary.empty:
            self.show_df(self.tree_summary, self.df_summary)
            return
        if value == "Todos":
            df = self.df_summary
        else:
            df = self.df_summary[self.df_summary["Status_global"].astype(str) == value].copy()
        self.show_df(self.tree_summary, df)
        self._write_detail_text(f"Filtro activo: {value}\nLinhas visíveis: {len(df)}")

    def _set_text_widget(self, widget, text: str):
        if widget is None:
            return
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _write_detail_text(self, text: str):
        self._set_text_widget(self.detail_text, text)

    def _write_dashboard_text(self, text: str):
        self._set_text_widget(self.dashboard_text, text)

    def update_dashboard(self):
        if not self.kpi_vars:
            return
        if self.df_results is None or self.df_results.empty:
            values = {
                "linhas": "-", "paineis": "-", "ok": "-", "ok_alerta": "-",
                "verificar": "-", "nao_conforme": "-", "ugz": "-", "input": "-",
            }
            for k, v in values.items():
                self.kpi_vars[k].set(v)
            self._write_dashboard_text(
                "Sem cálculo executado.\n\n"
                "Carregue a tabela, confirme os parâmetros e execute o cálculo. "
                "Após o cálculo, esta área resume os estados por painel, os governantes e as acções recomendadas."
            )
            return

        counts = self.df_summary["Status_global"].astype(str).value_counts().to_dict() if self.df_summary is not None and not self.df_summary.empty and "Status_global" in self.df_summary.columns else {}
        input_mode = "-"
        if "Moment_input_mode" in self.df_results.columns:
            modes = sorted(set(str(x) for x in self.df_results["Moment_input_mode"].dropna()))
            if any("direct_wa" in m for m in modes):
                input_mode = "momentos equivalentes"
            elif any("raw" in m for m in modes):
                input_mode = "MXX/MYY/MXY"
            else:
                input_mode = ", ".join(modes[:2]) if modes else "-"
        ugz = "-"
        if "UGZ_down_mm" in self.df_results.columns:
            val = self.df_results["UGZ_down_mm"].max()
            if pd.notna(val) and math.isfinite(float(val)):
                ugz = f"{float(val):.2f} mm"

        self.kpi_vars["linhas"].set(str(len(self.df_results)))
        self.kpi_vars["paineis"].set(str(len(self.df_summary)) if self.df_summary is not None else "-")
        self.kpi_vars["ok"].set(str(counts.get("OK", 0)))
        self.kpi_vars["ok_alerta"].set(str(counts.get("OK*", 0)))
        self.kpi_vars["verificar"].set(str(counts.get("Verificar", 0)))
        self.kpi_vars["nao_conforme"].set(str(counts.get("Não conforme", 0)))
        self.kpi_vars["ugz"].set(ugz)
        self.kpi_vars["input"].set(input_mode)

        lines = [
            "Síntese técnica",
            "────────────────",
            f"Foram analisadas {len(self.df_results)} linhas de resultados de placa/FEM.",
            f"Painéis resumidos: {len(self.df_summary) if self.df_summary is not None else 0}.",
            f"Formato de entrada reconhecido: {input_mode}.",
            "",
            "Estados globais por painel:",
            f"- OK: {counts.get('OK', 0)}",
            f"- OK com observação: {counts.get('OK*', 0)}",
            f"- A verificar: {counts.get('Verificar', 0)}",
            f"- Não conforme: {counts.get('Não conforme', 0)}",
            "",
            "Notas de leitura:",
            "- QXX/QYY e UGZ são informativos nesta versão.",
            "- Picos locais são diagnosticados estatisticamente; nenhum esforço é suavizado ou eliminado automaticamente.",
            "- A conformidade automática refere-se ao dimensionamento à flexão, armadura mínima, espaçamento e controlo de fendilhação configurado.",
            "- Para lajes apoiadas directamente em pilares, cargas concentradas, aberturas ou descontinuidades, verificar punçoamento/corte separadamente.",
        ]
        if self.df_summary is not None and not self.df_summary.empty:
            worst = self.df_summary.sort_values("util_max", ascending=False).iloc[0]
            lines += [
                "",
                "Painel mais solicitado:",
                f"- Painel: {worst.get('Panel','')}",
                f"- Utilização ELU máxima: {safe_float(worst.get('util_ELU_max', worst.get('util_max',0)),0):.3f}",
                f"- Caso/nó governante ELU: {worst.get('caso_governante_ELU', worst.get('caso_governante',''))} / {worst.get('node_governante_ELU', worst.get('node_governante',''))}",
                f"- Caso/nó governante ELS/wk: {worst.get('caso_governante_ELS_wk','-')} / {worst.get('node_governante_ELS_wk','-')}",
                f"- wk/wmax: {safe_float(worst.get('wk_wmax_ratio', float('nan')), float('nan')):.3f}",
                f"- Estado: {worst.get('Status_global','')}",
            ]
        self._write_dashboard_text("\n".join(lines))

    def _tree_selected_row(self, tree: ttk.Treeview):
        sel = tree.selection()
        if not sel:
            return None, None
        item = sel[0]
        cols = list(tree["columns"])
        vals = list(tree.item(item, "values"))
        return cols, dict(zip(cols, vals))

    def _format_selected_row_detail(self, tree: ttk.Treeview) -> str:
        cols, row = self._tree_selected_row(tree)
        if not row:
            return ""
        title = self._tree_labels.get(tree, "Tabela")
        panel = row.get("Panel") or row.get("Painel") or row.get("panel") or ""
        zone = row.get("Zona") or row.get("Zone") or row.get("zone") or ""
        panels = row.get("Painéis") or row.get("Paineis") or row.get("Panels") or ""
        status = row.get("Status_global") or row.get("Status") or row.get("Estado") or ""
        lines = [title, "=" * len(title)]
        if zone:
            lines.append(f"Zona: {zone}")
        if panels:
            lines.append(f"Painéis incluídos: {panels}")
        if panel:
            lines.append(f"Painel: {panel}")
        if status:
            lines.append(f"Estado: {status}")
        if row.get("Motivo_estado"):
            lines += ["", "Motivo técnico:", str(row.get("Motivo_estado"))]
        if row.get("Acção_recomendada") or row.get("Acao_recomendada"):
            lines += ["", "Acção recomendada:", str(row.get("Acção_recomendada") or row.get("Acao_recomendada"))]
        lines.append("")
        lines.append("Valores da linha seleccionada:")
        for c in cols:
            val = row.get(c, "")
            if str(val).strip() != "":
                lines.append(f"- {c}: {val}")

        # Complementa o detalhe do resumo com a linha de armaduras governantes.
        if panel and self.df_governing is not None and not self.df_governing.empty and "Panel" in self.df_governing.columns:
            matches = self.df_governing[self.df_governing["Panel"].astype(str) == str(panel)]
            if not matches.empty:
                g = matches.iloc[0]
                lines += [
                    "",
                    "Armaduras governantes por face/direcção:",
                    f"- Superior X: {g.get('X+_adopted','-')}",
                    f"- Superior Y: {g.get('Y+_adopted','-')}",
                    f"- Inferior X: {g.get('X-_adopted','-')}",
                    f"- Inferior Y: {g.get('Y-_adopted','-')}",
                ]
        return "\n".join(lines)

    def _on_tree_select(self, event):
        tree = event.widget
        text = self._format_selected_row_detail(tree)
        if text:
            self._write_detail_text(text)

    def _show_selected_detail(self, event=None):
        if event is not None and isinstance(getattr(event, "widget", None), ttk.Treeview):
            tree = event.widget
        else:
            focus = self.focus_get()
            tree = focus if isinstance(focus, ttk.Treeview) else None
        if tree is None and hasattr(self, "tree_summary"):
            tree = self.tree_summary
        text = self._format_selected_row_detail(tree) if tree is not None else ""
        if not text:
            messagebox.showinfo("Detalhe", "Seleccione uma linha da tabela.")
            return
        win = tk.Toplevel(self)
        win.title("Detalhe técnico")
        win.geometry("760x560")
        win.transient(self)
        frame = ttk.Frame(win, padding=8)
        frame.pack(fill="both", expand=True)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        txt = tk.Text(frame, wrap="word")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        txt.insert("1.0", text)
        txt.config(state="disabled")
        ttk.Button(frame, text="Fechar", command=win.destroy).grid(row=1, column=0, columnspan=2, sticky="e", pady=(8, 0))

    def _close_cell_balloon(self, event=None):
        win = getattr(self, "_cell_balloon", None)
        if win is not None:
            try:
                win.destroy()
            except Exception:
                pass
        self._cell_balloon = None

    def _show_cell_balloon(self, event=None):
        """Mostra um balão não modal com o conteúdo completo da linha/célula seleccionada."""
        if event is None or not isinstance(getattr(event, "widget", None), ttk.Treeview):
            return
        tree = event.widget
        try:
            row_id = tree.identify_row(event.y)
            col_id = tree.identify_column(event.x)
            region = tree.identify("region", event.x, event.y)
        except Exception:
            return
        if not row_id or region not in ("cell", "tree"):
            return

        cols = list(tree["columns"])
        vals = list(tree.item(row_id, "values"))
        if not cols or not vals:
            return
        row = dict(zip(cols, vals))
        try:
            idx = int(str(col_id).replace("#", "")) - 1
        except Exception:
            idx = -1
        cell_col = cols[idx] if 0 <= idx < len(cols) else ""
        cell_val = str(row.get(cell_col, "")) if cell_col else ""

        important_tree = tree in {
            getattr(self, "tree_summary", None),
            getattr(self, "tree_zones", None),
            getattr(self, "tree_sketches", None),
            getattr(self, "tree_diagnostic", None),
            getattr(self, "tree_peaks", None),
            getattr(self, "tree_validation", None),
        }
        important_col = any(k in str(cell_col).lower() for k in [
            "zona", "panel", "painel", "status", "estado", "motivo", "reason",
            "acção", "acao", "action", "nota", "note", "croquis", "diagnóstico", "diagnostico"
        ])
        if not important_tree and not important_col and len(cell_val) < 28:
            return

        try:
            tree.selection_set(row_id)
            tree.focus(row_id)
        except Exception:
            pass

        self._close_cell_balloon()
        label = self._tree_labels.get(tree, "Tabela")
        text = self._format_selected_row_detail(tree)
        if not text:
            return

        win = tk.Toplevel(self)
        self._cell_balloon = win
        win.wm_overrideredirect(True)
        try:
            win.attributes("-topmost", True)
        except Exception:
            pass

        outer = ttk.Frame(win, padding=1, relief="solid", borderwidth=1)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer, padding=(8, 5, 6, 3))
        header.pack(fill="x")
        title = f"{label}"
        if cell_col:
            title += f" · {cell_col}"
        ttk.Label(header, text=title, font=("Segoe UI", 9, "bold")).pack(side="left", anchor="w")
        ttk.Button(header, text="×", width=3, command=self._close_cell_balloon).pack(side="right")

        body = ttk.Frame(outer, padding=(8, 0, 8, 8))
        body.pack(fill="both", expand=True)
        body.rowconfigure(0, weight=1)
        body.columnconfigure(0, weight=1)
        txt = tk.Text(body, wrap="word", width=76, height=18, font=("Segoe UI", 9))
        vsb = ttk.Scrollbar(body, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        txt.insert("1.0", text)
        txt.config(state="disabled")

        # Posicionamento junto à célula clicada, mantendo a janela dentro do ecrã.
        win.update_idletasks()
        w = max(520, min(win.winfo_reqwidth(), 760))
        h = max(240, min(win.winfo_reqheight(), 540))
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = min(max(event.x_root + 14, 10), max(10, screen_w - w - 20))
        y = min(max(event.y_root + 14, 10), max(10, screen_h - h - 60))
        win.geometry(f"{w}x{h}+{x}+{y}")
        try:
            win.bind("<Escape>", self._close_cell_balloon)
            txt.bind("<Escape>", self._close_cell_balloon)
            win.focus_force()
        except Exception:
            pass

    def _column_width(self, column: str) -> int:
        c = str(column).lower()
        if any(k in c for k in ["motivo", "reason", "acção", "acao", "action", "nota", "notes", "formula", "croquis"]):
            return 340
        if any(k in c for k in ["status", "estado", "severidade"]):
            return 130
        if any(k in c for k in ["rebar", "adopted", "adoptada", "armadura"]):
            return 135
        if any(k in c for k in ["case", "caso", "node", "nó", "no"]):
            return 115
        if any(k in c for k in ["panel", "painel"]):
            return 90
        if c.startswith("util") or "util_" in c:
            return 105
        return max(90, min(190, len(str(column)) * 9))

    def _tag_for_values(self, cols, vals):
        row = dict(zip(cols, [str(v) for v in vals]))
        txt = " ".join(row.get(k, "") for k in ["Status_global", "Status", "Estado", "Severidade"])
        if "Não conforme" in txt or "Alta" in txt:
            return "bad"
        if "Verificar" in txt or "Média" in txt:
            return "warn"
        if "OK*" in txt or "Baixa" in txt:
            return "info"
        if "OK" in txt:
            return "ok"
        return ""

    def _build_instructions_tab(self, parent):
        outer = ttk.Frame(parent, padding=10)
        outer.pack(fill="both", expand=True)
        outer.rowconfigure(1, weight=1)
        outer.columnconfigure(0, weight=1)

        ttk.Label(
            outer,
            text="Instruções de importação da tabela de esforços",
            style="Header.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        frame = ttk.Frame(outer)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        txt = tk.Text(frame, wrap="word", height=22, undo=False)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=txt.yview)
        txt.configure(yscrollcommand=vsb.set)
        txt.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        instructions = (
            "OBJECTIVO\n"
            "Esta ferramenta dimensiona armadura distribuída de lajes maciças de betão armado à flexão, a partir de momentos por metro importados de um modelo de placa/FEM.\n\n"
            "ÂMBITO DO PROGRAMA\n"
            "- Cálculo de armadura inferior e superior nas direcções X e Y.\n"
            "- Transformação de MXX, MYY e MXY por Wood & Armer.\n"
            "- Controlo de armadura mínima, espaçamentos máximos e fendilhação segundo lógica EC2.\n"
            "- QXX/QYY e UGZ são apresentados apenas como diagnóstico do modelo.\n"
            "- Punçoamento, corte unidireccional, deformação normativa e vibração não são verificados nesta versão.\n\n"
            "COMO USAR\n"
            "1. Copiar a tabela de esforços do software de análise ou de uma folha de cálculo.\n"
            "2. Abrir a aba 'Colar'.\n"
            "3. Colar a tabela.\n"
            "4. Clicar em 'Ler tabela colada'.\n"
            "5. Classificar explicitamente as combinações ELU e ELS; podem ser usados intervalos compactos.\n"
            "6. Se for verificar wk, indicar uma ou mais combinações ELS quase-permanentes.\n7. Se existir uma singularidade confirmada após revisão do modelo, usar a aba 'Picos FEM' para seleccionar os nós da zona singular (ou introduzi-los manualmente).\n8. Clicar em 'Calcular'.\n\n"
            "CONVENÇÃO DE SINAIS\n"
            "- M < 0: flexão para baixo; face inferior traccionada; armadura inferior.\n"
            "- M > 0: flexão para cima; face superior traccionada; armadura superior.\n"
            "- UGZ < 0: deslocamento para baixo, salvo alteração no painel lateral.\n"
            "- Quando a tabela já contém MXX+/MXX-/MYY+/MYY-, esses valores são usados directamente como momentos equivalentes por face.\n"
            "- MXY não é interpretado isoladamente; entra apenas quando o modo MXX/MYY/MXY é usado.\n\n"
            "COLUNAS RECOMENDADAS\n"
            "Formato preferencial, quando disponível no software de análise/cálculo:\n"
            "- Panel ou Painel\n"
            "- Node ou Nó\n"
            "- Case ou Caso/Combinação\n"
            "- MXX+ (momento equivalente para armadura superior X)\n"
            "- MXX- (momento equivalente para armadura inferior X)\n"
            "- MYY+ (momento equivalente para armadura superior Y)\n"
            "- MYY- (momento equivalente para armadura inferior Y)\n"
            "- UGZ, opcional e apenas informativo\n\n"
            "Formato alternativo, quando só existem momentos brutos de placa:\n"
            "- Panel ou Painel\n"
            "- Node ou Nó\n"
            "- Case ou Caso/Combinação\n"
            "- MXX\n"
            "- MYY\n"
            "- MXY\n"
            "- QXX, opcional e apenas informativo\n"
            "- QYY, opcional e apenas informativo\n"
            "- UGZ, opcional e apenas informativo\n\n"
            "CLASSIFICAÇÃO DAS COMBINAÇÕES\n"
            "- ELU: combinações usadas no envelope de resistência à flexão.\n"
            "- ELS característica: uma ou mais combinações de serviço características.\n"
            "- ELS frequente: uma ou mais combinações de serviço frequentes.\n"
            "- ELS quase-permanente: uma ou mais combinações de serviço quase-permanentes; são estas que governam o cálculo directo de wk nesta versão.\n"
            "- Intervalos aceites: 101-117 201-216; também 101para117, 101 a 117 ou casos isolados.\n"
            "- Uma mesma combinação não pode ser atribuída a mais do que uma classe.\n\n"
            "UNIDADES ESPERADAS\n"
            "- MXX+/MXX-/MYY+/MYY- ou MXX/MYY/MXY: normalmente em kNm/m.\n"
            "- QXX e QYY: normalmente em kN/m; são reportados mas não usados no dimensionamento.\n"
            "- UGZ: normalmente em cm, mm ou m; é convertido para mm e reportado como deslocamento vertical do modelo.\n"
            "As unidades podem ser alteradas no painel lateral.\n\n"
            "TABELA TIPO — MOMENTOS EQUIVALENTES RECOMENDADOS\n"
            "Panel\tNode\tCase\tMXX+\tMXX-\tMYY+\tMYY-\tUGZ (cm)\n"
            "43\t49\t101\t8.75\t12.40\t3.80\t2.60\t-0.18\n"
            "43\t49\t302 (QP)\t3.10\t5.10\t1.40\t0.90\t-0.08\n\n"
            "TABELA ALTERNATIVA COM MOMENTOS BRUTOS\n"
            "Panel\tNode\tCase\tMXX\tMYY\tMXY\tQXX\tQYY\n"
            "43\t49\t101\t-12.40\t3.80\t1.25\t18.50\t6.20\n"
            "43\t49\t302 (QP)\t-5.10\t1.40\t0.52\t7.20\t2.10\n\n"
            "FORMATO COM COLUNA ÚNICA PANEL/NODE/CASE\n"
            "Também é aceite uma coluna única do tipo Panel/Node/Case, por exemplo:\n\n"
            "Panel/Node/Case\tMXX+\tMXX-\tMYY+\tMYY-\tUGZ (cm)\n"
            "43/49/101\t8.75\t12.40\t3.80\t2.60\t-0.18\n"
            "43/49/302 (QP)\t3.10\t5.10\t1.40\t0.90\t-0.08\n\n"
            "NOTAS IMPORTANTES\n"
            "- Confirmar a orientação dos eixos locais e a normal dos painéis no software de origem. A ordem das camadas não é inferida nó a nó; adopta-se uma profundidade útil conservadora.\n"
            "- Para verificação explícita de wk, indicar uma ou mais combinações ELS quase-permanentes.\n"
            "- As combinações ELS característica e frequente são classificadas e reportadas; nesta versão não governam o cálculo directo de wk.\n- O cálculo de wk só deve ser interpretado com esforços de ELS apropriados.\n"
            "- QXX/QYY e UGZ não geram estados OK/Não conforme nesta versão.\n"
            "- Na aba Dashboard é apresentada uma síntese do estado global dos painéis.\n"
            "- Na aba Resumo, seleccionar ou fazer duplo clique numa linha permite consultar a leitura técnica completa do painel.\n"
            "- Nas tabelas principais, clicar numa célula relevante abre um balão de detalhe com o conteúdo completo da linha, útil para zonas, croquis, motivos e notas longas.\n"
            "- As mensagens de motivo e acção recomendada são formuladas como notas técnicas de verificação estrutural; não substituem a validação final do projectista.\n"
            "- O relatório PDF é sintético; o Excel exportado mantém os resultados completos para auditoria.\n"
            "- Opcionalmente podem ser importadas tabelas .xlsx/.csv de nós, vigas/pilares, paredes e contornos de aberturas/negativos. Estes dados localizam/classificam zonas locais associadas aos picos e apoiam a decisão do projectista; não alteram o núcleo ELU/ELS.\n"
        )
        txt.insert("1.0", instructions)
        txt.config(state="disabled")

    def _build_paste_tab(self, parent):
        top = ttk.Frame(parent, padding=6)
        top.pack(fill="x")
        ttk.Label(top, text="Cole aqui a tabela de esforços, clique em 'Ler tabela colada' e depois em 'Calcular'.").pack(side="left")
        ttk.Button(top, text="Calcular", command=self.run_design, style="Primary.TButton").pack(side="right")
        ttk.Button(top, text="Ler tabela colada", command=self.load_from_textbox).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Limpar", command=lambda: self.txt_paste.delete("1.0", "end")).pack(side="right", padx=(0, 6))

        frame = ttk.Frame(parent, padding=(6, 0, 6, 6))
        frame.pack(fill="both", expand=True)
        self.txt_paste = tk.Text(frame, wrap="none", undo=True)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.txt_paste.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=self.txt_paste.xview)
        self.txt_paste.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.txt_paste.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def _make_tree(self, parent):
        frame = ttk.Frame(parent)
        frame.pack(fill="both", expand=True)
        tree = ttk.Treeview(frame, show="headings")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return tree

    def show_df(self, tree: ttk.Treeview, df: pd.DataFrame):
        tree.delete(*tree.get_children())
        # A Treeview só apresenta uma pré-visualização. Guardar uma cópia integral de 300k+
        # linhas duplicava centenas de MB sem qualquer benefício para a GUI.
        preview_rows = LARGE_PREVIEW_ROWS if (df is not None and len(df) >= LARGE_DATASET_THRESHOLD) else MAX_PREVIEW_ROWS
        preview = df.head(preview_rows) if df is not None else pd.DataFrame()
        self._tree_data[tree] = preview
        try:
            tree.tag_configure("ok", background="#eef7ee")
            tree.tag_configure("info", background="#eef3fb")
            tree.tag_configure("warn", background="#fff5d6")
            tree.tag_configure("bad", background="#fde7e7")
        except Exception:
            pass
        tree.bind("<<TreeviewSelect>>", self._on_tree_select)
        tree.bind("<Double-1>", self._show_selected_detail)
        tree.bind("<ButtonRelease-1>", self._show_cell_balloon, add="+")
        tree.bind("<Escape>", self._close_cell_balloon, add="+")
        if df is None or df.empty:
            tree["columns"] = []
            return
        cols = list(df.columns)
        tree["columns"] = cols
        for c in cols:
            tree.heading(c, text=c)
            anchor = "w" if any(k in str(c).lower() for k in ["motivo", "reason", "acção", "acao", "action", "nota", "notes", "formula", "croquis"]) else "center"
            tree.column(c, width=self._column_width(c), anchor=anchor, stretch=True)
        for values in preview.itertuples(index=False, name=None):
            vals = []
            for c, v in zip(cols, values):
                if isinstance(v, float):
                    vals.append("" if not math.isfinite(v) else f"{v:.3f}")
                else:
                    vals.append(str(v))
            tag = self._tag_for_values(cols, vals)
            tree.insert("", "end", values=vals, tags=(tag,) if tag else ())

    def load_from_textbox(self):
        text = self.txt_paste.get("1.0", "end").strip()
        if not text:
            messagebox.showwarning("Aviso", "Cole primeiro a tabela na caixa de texto.")
            return
        df = parse_pasted_table(text)
        if df.empty:
            messagebox.showwarning("Aviso", "A tabela colada não foi reconhecida.")
            return
        self.load_df(df)

    def paste_clipboard(self):
        try:
            text = self.clipboard_get()
        except Exception:
            messagebox.showwarning("Aviso", "Não foi possível ler a área de transferência.")
            return
        df = parse_pasted_table(text)
        if df.empty:
            messagebox.showwarning("Aviso", "A tabela colada não foi reconhecida.")
            return
        self.txt_paste.delete("1.0", "end")
        self.txt_paste.insert("1.0", text)
        self.load_df(df)

    def import_file(self):
        path = filedialog.askopenfilename(
            title="Importar tabela",
            filetypes=[("Excel", "*.xlsx *.xls"), ("CSV / TXT", "*.csv *.txt"), ("Todos", "*.*")],
        )
        if not path:
            return
        try:
            selected = None
            self.import_source_note = ""
            if path.lower().endswith((".xlsx", ".xls")):
                xls = pd.ExcelFile(path)
                preferred = ["16_Raw_Table", "Raw_Table", "Values", "Envelope", "Global extremes", "Panels"]
                selected = None
                for name in preferred:
                    if name in xls.sheet_names:
                        selected = name
                        break
                if selected is None:
                    for name in xls.sheet_names:
                        try:
                            sample = pd.read_excel(path, sheet_name=name, dtype=str, nrows=8)
                            cleaned_cols = set(rename_known_columns(sample).columns)
                            if ({"mxx", "myy", "mxy"}.issubset(cleaned_cols) or {"mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"}.issubset(cleaned_cols)):
                                selected = name
                                break
                        except Exception:
                            continue
                if selected is None:
                    selected = xls.sheet_names[0]
                df = pd.read_excel(path, sheet_name=selected, dtype=str)
            else:
                df, csv_note = read_delimited_file_robust(path)
                selected = None
                self.import_source_note = csv_note
            self.load_df(df, source_path=path, source_sheet=selected)
            if selected:
                self.status_var.set(f"Tabela carregada: {len(self.df_clean)} linhas. Folha Excel usada: {selected}. Clique em Calcular para dimensionar.")
            elif self.import_source_note:
                self.status_var.set(f"Tabela carregada: {len(self.df_clean)} linhas ({self.import_source_note}). Clique em Calcular para dimensionar.")
        except Exception as e:
            messagebox.showerror("Erro", f"Não foi possível importar a tabela.\n\nDetalhe técnico: {e}")

    def load_df(self, df: pd.DataFrame, source_path: str = "", source_sheet: Optional[str] = None):
        self.input_source_path = str(source_path or "")
        self.input_source_sheet = source_sheet
        self.df_raw = df.copy()
        self.df_clean = clean_dataframe(df)
        self.import_source_note = self.import_source_note or ""
        self.df_results = pd.DataFrame()
        self.df_summary = pd.DataFrame()
        self.df_governing = pd.DataFrame()
        self.df_zones = pd.DataFrame()
        self.df_traceability = pd.DataFrame()
        self.df_unit_check = pd.DataFrame()
        self.df_detailed = pd.DataFrame()
        self.df_notes = pd.DataFrame()
        self.df_optimization = pd.DataFrame()
        self.df_diagnostic = pd.DataFrame()
        self.df_data_validation = pd.DataFrame()
        self.df_sketches = pd.DataFrame()
        self.df_peaks = pd.DataFrame()
        self.show_df(self.tree_input, self.df_clean)
        self.show_df(self.tree_results, self.df_results)
        self.show_df(self.tree_summary, self.df_summary)
        self.show_df(self.tree_governing, self.df_governing)
        self.show_df(self.tree_zones, self.df_zones)
        if hasattr(self, "tree_traceability"):
            self.show_df(self.tree_traceability, self.df_traceability)
        self.show_df(self.tree_optimization, self.df_optimization)
        self.show_df(self.tree_diagnostic, self.df_diagnostic)
        self.show_df(self.tree_peaks, self.df_peaks)
        self.show_df(self.tree_validation, self.df_data_validation)
        self.show_df(self.tree_sketches, self.df_sketches)
        self.show_df(self.tree_unit, self.df_unit_check)
        self.show_df(self.tree_detailed, self.df_detailed)
        self.show_df(self.tree_notes, self.df_notes)
        # Mostrar também a tabela importada na aba Colar, para auditoria visual imediata.
        try:
            preview_text = dataframe_to_tsv_preview(self.df_raw, max_rows=5000)
            self.txt_paste.delete("1.0", "end")
            self.txt_paste.insert("1.0", preview_text)
        except Exception:
            pass
        self.update_dashboard()
        self.progress_var.set(0.0)
        try:
            self.nb.select(self.tab_input)
        except Exception:
            pass
        src = ""
        if source_sheet:
            src = f" Folha: {source_sheet}."
        self.status_var.set(f"Tabela carregada: {len(self.df_clean)} linhas.{src} Clique em Calcular para dimensionar.")

    def validate_inputs(self) -> Optional[str]:
        if self.df_clean is None or self.df_clean.empty:
            return "Cole ou importe uma tabela de esforços primeiro."
        t = safe_float(self.var_thickness.get(), 0.0)
        c = safe_float(self.var_cover.get(), 0.0)
        if t <= 0:
            return "Espessura inválida."
        if c <= 0 or c >= 0.45 * t:
            return "Recobrimento inválido para a espessura indicada."
        gamma_c = safe_float(self.var_gamma_c.get(), 0.0)
        gamma_s = safe_float(self.var_gamma_s.get(), 0.0)
        alpha_cc = safe_float(self.var_alpha_cc.get(), 0.0)
        aggregate_mm = safe_float(self.var_aggregate_mm.get(), 0.0)
        k1 = safe_float(self.var_stress_k1.get(), 0.0)
        k2 = safe_float(self.var_stress_k2.get(), 0.0)
        k3 = safe_float(self.var_stress_k3.get(), 0.0)
        if not (1.0 <= gamma_c <= 2.0):
            return "γc deve estar entre 1,00 e 2,00."
        if not (1.0 <= gamma_s <= 1.5):
            return "γs deve estar entre 1,00 e 1,50."
        if not (0.80 <= alpha_cc <= 1.00):
            return "αcc deve estar entre 0,80 e 1,00."
        if not (4.0 <= aggregate_mm <= 63.0):
            return "A dimensão máxima do agregado dg deve estar entre 4 e 63 mm."
        if not all(0.10 <= k <= 1.00 for k in (k1, k2, k3)):
            return "Os coeficientes k1, k2 e k3 devem estar entre 0,10 e 1,00."
        if k2 > k1:
            return "Para os limites ELS configurados, k2 não deve ser superior a k1."
        peak_ratio = safe_float(self.var_peak_ratio_threshold.get(), 0.0)
        if self.var_geometry_local_design.get():
            local_factor = safe_float(self.var_local_zone_factor.get(), 0.0)
            if local_factor < 1.0 or local_factor > 6.0:
                return "O factor da largura local deve estar entre 1,0 e 6,0 vezes o passo local da malha."
            if self.df_geometry_nodes is None or self.df_geometry_nodes.empty:
                return "O dimensionamento local geométrico requer a tabela geral de nós. Importe-a ou desactive a opção."
        if peak_ratio <= 1.0:
            return "O limiar de detecção de picos max/P95 deve ser superior a 1,00."
        parse_node_spec(self.var_singular_nodes.get())

        combo_fields = [
            ("ELU", self.var_uls_cases.get()),
            ("ELS característica", self.var_els_char_cases.get()),
            ("ELS frequente", self.var_els_freq_cases.get()),
            ("ELS quase-permanente", self.var_els_qp_cases.get()),
        ]
        for label, text in combo_fields:
            try:
                parse_case_spec(text)
            except CombinationSpecError as exc:
                return f"{label}: {exc}"
        uls_ids = parse_case_spec(self.var_uls_cases.get())
        char_ids = parse_case_spec(self.var_els_char_cases.get())
        freq_ids = parse_case_spec(self.var_els_freq_cases.get())
        qp_ids = parse_case_spec(self.var_els_qp_cases.get())
        if not uls_ids:
            return "Indique as combinações ELU. Pode usar intervalos, por exemplo: 101-117 201-216."
        overlaps = find_overlaps(uls_ids, char_ids, freq_ids, qp_ids)
        if overlaps:
            return f"Combinações atribuídas a mais do que uma classe: {format_case_ids(overlaps)}. Corrija a classificação ELU/ELS."
        if self.var_crack_check.get() and not qp_ids:
            return "A verificação directa de wk requer pelo menos uma combinação ELS quase-permanente."
        return None

    def build_unit_check(self, df_clean: pd.DataFrame, designer: SlabDesigner) -> pd.DataFrame:
        if df_clean is None or df_clean.empty:
            return pd.DataFrame()
        # v2.15.2: ordens de grandeza que podem bloquear/avisar o projecto usam apenas
        # combinações explicitamente classificadas. Casos ``Outro`` continuam preservados
        # e têm um máximo RAW informativo separado, sem contaminar o estado de dimensionamento.
        if "case" in df_clean.columns:
            cls = df_clean["case"].map(designer.classify_case)
            design_mask = cls.astype(str) != "Outro"
        else:
            design_mask = pd.Series(True, index=df_clean.index)
        dcalc = df_clean.loc[design_mask].copy() if bool(design_mask.any()) else df_clean.iloc[0:0].copy()

        def _max_abs(frame, cols, factor):
            vals = [pd.to_numeric(frame[c], errors="coerce").abs().max() * factor for c in cols if c in frame.columns]
            vals = [safe_float(v, 0.0) for v in vals if pd.notna(v)]
            return max(vals) if vals else 0.0

        mcols = ["mxx", "myy", "mxy", "mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"]
        max_m = _max_abs(dcalc, mcols, designer.moment_factor)
        max_m_raw = _max_abs(df_clean, mcols, designer.moment_factor)
        max_q = _max_abs(dcalc, ["qxx", "qyy"], designer.shear_factor)
        max_u = _max_abs(dcalc, ["ugz"], designer.deflection_factor)
        notes = []
        if max_m > 1000.0:
            notes.append("Momentos convertidos muito elevados para lajes correntes; confirmar unidades e sinal dos esforços.")
        if 0.0 < max_m < 0.01:
            notes.append("Momentos muito baixos; confirmar se a unidade não deveria ser kNm/m.")
        if max_q > 1500.0:
            notes.append("Esforços transversos muito elevados para lajes correntes; confirmar unidades.")
        if not notes:
            notes.append("Sem anomalias óbvias por ordem de grandeza. Esta verificação não substitui a confirmação das unidades na origem dos resultados.")
        unit_rows = [
            {"Grandeza": "Momentos de flexão — combinações classificadas", "Unidade selecionada": designer.moment_unit, "Factor aplicado": designer.moment_factor, "Máximo convertido": max_m, "Unidade interna": "kNm/m", "Nota": notes[0]},
        ]
        if max_m_raw > max_m + max(1e-9, 1e-6 * max(max_m_raw, 1.0)):
            unit_rows.append({
                "Grandeza": "Momentos de flexão — RAW importado (inclui Outro)",
                "Unidade selecionada": designer.moment_unit, "Factor aplicado": designer.moment_factor,
                "Máximo convertido": max_m_raw, "Unidade interna": "kNm/m",
                "Nota": "Máximo apenas informativo; inclui combinações não classificadas e não condiciona ELU/ELS nem o aviso de unidades de projecto."
            })
        unit_rows += [
            {"Grandeza": "QXX/QYY", "Unidade selecionada": designer.shear_unit, "Factor aplicado": designer.shear_factor, "Máximo convertido": max_q, "Unidade interna": "kN/m", "Nota": "Esforços transversos apenas informativos nesta versão. " + " | ".join(notes)},
            {"Grandeza": "Deslocamento UGZ", "Unidade selecionada": designer.deflection_unit, "Factor aplicado": designer.deflection_factor, "Máximo convertido": max_u, "Unidade interna": "mm", "Nota": "UGZ negativo = para baixo. Valor apenas informativo/diagnóstico; não é verificação automática de flecha."},
            {"Grandeza": "Fendilhação", "Unidade selecionada": "wk seleccionado" if designer.wk_check_enabled else "controlo simplificado", "Factor aplicado": "-", "Máximo convertido": "-", "Unidade interna": "-", "Nota": f"wk só é avaliado nas combinações ELS quase-permanentes indicadas: {format_case_ids(designer.qp_case_ids) or 'não indicadas'}. A ELS característica é usada também na limitação de tensões quando essa verificação está activa; a ELS frequente permanece classificada e reportada."},
        ]
        return pd.DataFrame(unit_rows)


    def build_data_validation(self, df_clean: pd.DataFrame, designer: SlabDesigner) -> pd.DataFrame:
        rows = []
        if df_clean is None or df_clean.empty:
            return pd.DataFrame([{"Categoria": "Tabela", "Item": "linhas", "Estado": "Não conforme", "Resultado": "0", "Nota": "Sem dados importados."}])

        # Dois formatos são válidos:
        # A) momentos brutos: MXX, MYY, MXY;
        # B) momentos equivalentes: MXX+, MXX-, MYY+, MYY-.
        moment_mode = str(df_clean["__moment_input_mode"].iloc[0]) if "__moment_input_mode" in df_clean.columns and len(df_clean) else "undefined"
        base_required = ["panel", "case"]
        for c in base_required:
            estado = "OK" if c in df_clean.columns else "Não conforme"
            rows.append({"Categoria": "Colunas", "Item": c, "Estado": estado, "Resultado": "presente" if estado == "OK" else "em falta", "Nota": "coluna reconhecida" if estado == "OK" else "corrigir cabeçalho ou formato de importação"})
        if moment_mode == "direct_wa":
            rows.append({"Categoria": "Formato de momentos", "Item": "MXX+/MXX-/MYY+/MYY-", "Estado": "OK", "Resultado": "momentos equivalentes reconhecidos", "Nota": "+ = face superior; - = face inferior; valores usados directamente"})
            for c in ["mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"]:
                rows.append({"Categoria": "Colunas", "Item": c, "Estado": "OK", "Resultado": "presente", "Nota": "coluna de momento equivalente reconhecida"})
        elif moment_mode == "direct_wa_partial":
            rows.append({"Categoria": "Formato de momentos", "Item": "MXX+/MXX-/MYY+/MYY-", "Estado": "Verificar", "Resultado": "colunas equivalentes parciais", "Nota": "valores em falta são assumidos como zero; confirmar exportação"})
            for c in ["mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"]:
                rows.append({"Categoria": "Colunas", "Item": c, "Estado": "OK" if c in df_clean.columns else "Verificar", "Resultado": "presente" if c in df_clean.columns else "em falta", "Nota": "formato equivalente parcial"})
        elif moment_mode == "raw_plate":
            rows.append({"Categoria": "Formato de momentos", "Item": "MXX/MYY/MXY", "Estado": "OK", "Resultado": "momentos brutos reconhecidos", "Nota": "Wood & Armer calculado internamente"})
            for c in ["mxx", "myy", "mxy"]:
                rows.append({"Categoria": "Colunas", "Item": c, "Estado": "OK", "Resultado": "presente", "Nota": "coluna de momento bruto reconhecida"})
        else:
            rows.append({"Categoria": "Formato de momentos", "Item": "momentos", "Estado": "Não conforme", "Resultado": "não reconhecido", "Nota": "fornecer MXX/MYY/MXY ou MXX+/MXX-/MYY+/MYY-"})
        for c in ["qxx", "qyy"]:
            rows.append({"Categoria": "Colunas", "Item": c, "Estado": "Informativo", "Resultado": "presente" if c in df_clean.columns else "em falta", "Nota": "coluna lida apenas para diagnóstico; não entra no cálculo" if c in df_clean.columns else "opcional"})
        rows.append({"Categoria": "Colunas", "Item": "ugz", "Estado": "Informativo", "Resultado": "presente" if "ugz" in df_clean.columns else "em falta", "Nota": "deslocamento vertical lido apenas para diagnóstico; negativo = para baixo" if "ugz" in df_clean.columns else "opcional"})

        n_lines = len(df_clean)
        n_panels = df_clean["panel"].astype(str).nunique() if "panel" in df_clean.columns else 0
        n_cases = df_clean["case_id"].astype(str).nunique() if "case_id" in df_clean.columns else 0
        rows.append({"Categoria": "Tabela", "Item": "linhas", "Estado": "OK" if n_lines > 0 else "Não conforme", "Resultado": n_lines, "Nota": "número de linhas importadas"})
        rows.append({"Categoria": "Tabela", "Item": "painéis", "Estado": "OK" if n_panels > 0 else "Verificar", "Resultado": n_panels, "Nota": "painéis distintos detectados"})
        rows.append({"Categoria": "Tabela", "Item": "combinações", "Estado": "OK" if n_cases > 0 else "Verificar", "Resultado": n_cases, "Nota": "casos/combinações distintos detectados"})
        found_ids = {canonical_case_id(v) for v in df_clean.get("case", pd.Series(dtype=str)).tolist() if canonical_case_id(v)}

        def add_class_validation(category, item, case_ids, note_ok, required=False):
            case_ids = set(case_ids or set())
            if not case_ids:
                rows.append({
                    "Categoria": category, "Item": item,
                    "Estado": "Não conforme" if required else "Informativo",
                    "Resultado": "não indicadas",
                    "Nota": "classificação obrigatória para o cálculo" if required else "classe não definida pelo utilizador"
                })
                return
            missing = sorted(case_ids - found_ids, key=lambda x: int(x) if str(x).isdigit() else str(x))
            rows.append({
                "Categoria": category, "Item": item,
                "Estado": "OK" if not missing else "Verificar",
                "Resultado": format_case_ids(case_ids),
                "Nota": note_ok if not missing else f"casos não encontrados na tabela: {format_case_ids(missing)}"
            })

        add_class_validation("ELU", "combinações", designer.uls_case_ids, "classificação explícita usada no envelope ELU", required=True)
        add_class_validation("ELS", "característica", designer.characteristic_case_ids, "combinações ELS características classificadas; mantidas para rastreabilidade nesta versão")
        add_class_validation("ELS", "frequente", designer.frequent_case_ids, "combinações ELS frequentes classificadas; mantidas para rastreabilidade nesta versão")
        add_class_validation("ELS", "quase-permanente", designer.qp_case_ids, "combinações ELS-QP usadas no envelope de fendilhação quando wk está activo", required=designer.wk_check_enabled)

        if designer.wk_check_enabled and designer.qp_case_ids:
            mask = df_clean["case"].map(designer.is_qp_case) if "case" in df_clean.columns else pd.Series(False, index=df_clean.index)
            n_qp = int(mask.sum())
            qp_found = {canonical_case_id(v) for v in df_clean.loc[mask, "case"].tolist()} if n_qp else set()
            missing_qp = sorted(designer.qp_case_ids - qp_found, key=lambda x: int(x) if str(x).isdigit() else str(x))
            panels_qp = df_clean.loc[mask, "panel"].astype(str).nunique() if n_qp and "panel" in df_clean.columns else 0
            missing_panels = []
            if "panel" in df_clean.columns:
                all_p = set(df_clean["panel"].astype(str))
                qp_p = set(df_clean.loc[mask, "panel"].astype(str)) if n_qp else set()
                missing_panels = sorted(all_p - qp_p)
            estado = "OK" if n_qp > 0 and not missing_qp and not missing_panels else ("Verificar" if n_qp > 0 else "Não conforme")
            notes_qp = []
            if missing_qp:
                notes_qp.append(f"ELS-QP não encontrados: {format_case_ids(missing_qp)}")
            if missing_panels:
                notes_qp.append(f"painéis sem qualquer ELS-QP: {', '.join(missing_panels[:12])}")
            if not notes_qp:
                notes_qp.append("pelo menos uma combinação ELS-QP encontrada em todos os painéis")
            rows.append({
                "Categoria": "ELS", "Item": "cobertura da verificação wk", "Estado": estado,
                "Resultado": f"{n_qp} linhas; {len(qp_found)}/{len(designer.qp_case_ids)} casos QP encontrados; {panels_qp}/{n_panels} painéis",
                "Nota": " | ".join(notes_qp)
            })

        # Coerência básica de ordem de grandeza, após conversão. Apenas combinações
        # explicitamente classificadas podem criar o aviso de projecto; ``Outro`` é RAW informativo.
        if "case" in df_clean.columns:
            __cls = df_clean["case"].map(designer.classify_case)
            __mask = __cls.astype(str) != "Outro"
        else:
            __mask = pd.Series(True, index=df_clean.index)
        __calc = df_clean.loc[__mask] if bool(__mask.any()) else df_clean.iloc[0:0]
        __mcols = ["mxx", "myy", "mxy", "mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"]
        max_m = max([safe_float(pd.to_numeric(__calc[c], errors="coerce").abs().max(), 0.0) * designer.moment_factor for c in __mcols if c in __calc.columns] or [0])
        max_m_raw = max([safe_float(pd.to_numeric(df_clean[c], errors="coerce").abs().max(), 0.0) * designer.moment_factor for c in __mcols if c in df_clean.columns] or [0])
        max_q = max([safe_float(pd.to_numeric(__calc[c], errors="coerce").abs().max(), 0.0) * designer.shear_factor for c in ["qxx", "qyy"] if c in __calc.columns] or [0])
        rows.append({"Categoria": "Unidades", "Item": "momentos — combinações classificadas", "Estado": "Verificar" if max_m > 1000 or (0 < max_m < 0.01) else "OK", "Resultado": f"max |M| = {max_m:.3f} kNm/m", "Nota": "confirmar unidades se o máximo das combinações usadas no cálculo estiver fora da ordem corrente"})
        if max_m_raw > max_m + max(1e-9, 1e-6 * max(max_m_raw, 1.0)):
            rows.append({"Categoria": "Unidades", "Item": "momentos RAW — inclui Outro", "Estado": "Informativo", "Resultado": f"max |M| RAW = {max_m_raw:.3f} kNm/m", "Nota": "casos não classificados são preservados para rastreabilidade, mas não condicionam o aviso de unidades nem o dimensionamento"})
        rows.append({"Categoria": "Unidades", "Item": "QXX/QYY", "Estado": "Informativo", "Resultado": f"max |Q| = {max_q:.3f} kN/m", "Nota": "valor reportado apenas como diagnóstico; não participa no dimensionamento"})
        rows.append({"Categoria": "Parâmetros EC2", "Item": "materiais", "Estado": "OK", "Resultado": f"γc={designer.gamma_c:.2f}; γs={designer.gamma_s:.2f}; αcc={designer.alpha_cc:.2f}", "Nota": f"fcd={designer.cp['fcd']:.2f} MPa; fyd={designer.fyd:.2f} MPa — valores efectivamente usados no cálculo"})
        rows.append({"Categoria": "Parâmetros EC2", "Item": "agregado dg", "Estado": "OK", "Resultado": f"{designer.aggregate_mm:.0f} mm", "Nota": "considerado na distância livre mínima entre varões"})
        rows.append({"Categoria": "Parâmetros EC2", "Item": "limites ELS", "Estado": "OK" if designer.stress_check_enabled else "Informativo", "Resultado": f"k1/k2/k3={designer.stress_k1:.2f}/{designer.stress_k2:.2f}/{designer.stress_k3:.2f}", "Nota": "coeficientes usados na limitação de tensões EC2 7.2"})
        # Coerência simples entre a espessura indicada no nome do ficheiro e a entrada de cálculo.
        # Nunca altera o valor automaticamente: apenas chama a atenção para erros de configuração.
        src = str(getattr(self, "input_source_path", "") or "")
        if src:
            fname = os.path.basename(src)
            mm_vals = [float(v) for v in re.findall(r"(?<!\d)(\d{2,4})\s*mm(?!\w)", fname, flags=re.IGNORECASE)]
            if mm_vals:
                t_cfg = safe_float(self.var_thickness.get(), 0.0)
                nearest = min(mm_vals, key=lambda v: abs(v-t_cfg))
                mismatch = abs(nearest - t_cfg) > 0.5
                rows.append({
                    "Categoria": "Coerência de entrada", "Item": "espessura vs nome do ficheiro",
                    "Estado": "Verificar" if mismatch else "OK",
                    "Resultado": f"ficheiro sugere {nearest:.0f} mm; cálculo usa {t_cfg:.0f} mm",
                    "Nota": "O programa não altera a espessura automaticamente. Confirmar o valor introduzido." if mismatch else "coerente",
                })
        rows.append({"Categoria": "Eixos locais", "Item": "orientação", "Estado": "OK*" if designer.swap_local_axes else "OK", "Resultado": "X/Y trocados" if designer.swap_local_axes else ("Y local = direcção principal" if designer.local_y_is_vertical else "X local = direcção principal"), "Nota": "confirmar orientação dos eixos locais, sentido da normal e direcções de armadura antes de desenhar"})
        rows.append({
            "Categoria": "Picos FEM", "Item": "detecção estatística", "Estado": "Informativo",
            "Resultado": f"limiar max/P95 = {designer.peak_ratio_threshold:.2f}",
            "Nota": "O detector não suaviza nem substitui esforços; P95/P99 são apenas referências estatísticas para diagnóstico."
        })
        if designer.singular_node_ids:
            imported_nodes = {canonical_node_id(v) for v in df_clean.get("node", pd.Series(dtype=object)).dropna()} if "node" in df_clean.columns else set()
            missing_singular = sorted(designer.singular_node_ids - imported_nodes)
            singular_state = "Verificar" if not missing_singular else "Não conforme"
            singular_note = "Nós indicados explicitamente são excluídos apenas do envelope distribuído e permanecem como verificação local obrigatória."
            if missing_singular:
                singular_note += " Nós não encontrados na tabela importada: " + ", ".join(missing_singular) + "."
        else:
            missing_singular = []
            singular_state = "Informativo"
            singular_note = "Nenhum nó é excluído automaticamente do dimensionamento distribuído."
        rows.append({
            "Categoria": "Picos FEM", "Item": "singularidades confirmadas",
            "Estado": singular_state,
            "Resultado": ", ".join(sorted(designer.singular_node_ids)) if designer.singular_node_ids else "nenhuma",
            "Nota": singular_note
        })
        return pd.DataFrame(rows)

    def build_diagnostic(self, results: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
        rows = []
        def add(panel, sev, problem, action, source="Cálculo"):
            rows.append({"Painel": panel, "Severidade": sev, "Problema": problem, "Acção recomendada": action, "Origem": source})

        if validation is not None and not validation.empty:
            for _, r in validation.iterrows():
                estado = str(r.get("Estado", ""))
                if estado in ("Verificar", "Não conforme", "OK*"):
                    sev = "Alta" if estado == "Não conforme" else ("Média" if estado == "Verificar" else "Baixa")
                    add("-", sev, f"{r.get('Categoria','')} - {r.get('Item','')}: {r.get('Resultado','')}", r.get("Nota", ""), source="Validação da tabela")

        if results is None or results.empty:
            return pd.DataFrame(rows)
        for panel, g in results.groupby("Panel", dropna=False, observed=True):
            # Estado GLOBAL usa apenas o envelope distribuído. Picos/singularidades excluídos
            # permanecem no grupo RAW e são diagnosticados separadamente abaixo.
            g_global = g.copy()
            if "Design_relevant" in g_global.columns:
                g_global = g_global[g_global["Design_relevant"].astype(str) != "Não"].copy()
            if "Excluded_from_distributed_envelope" in g_global.columns:
                g_global = g_global[g_global["Excluded_from_distributed_envelope"].astype(str) != "Sim"].copy()
            if g_global.empty:
                g_global = g.iloc[0:0].copy()
            # Estado mais gravoso por painel, mantendo separação ELU/ELS.
            statuses = set(str(x) for x in g_global.get("Status", pd.Series(dtype=str)).dropna())
            if "Não conforme" in statuses:
                bad = g_global[g_global.get("Status", pd.Series(dtype=str)).astype(str) == "Não conforme"].copy()
                bad_els = bad[bad.get("Case_classification", pd.Series(index=bad.index, dtype=str)).astype(str) == "ELS-QP"] if not bad.empty else pd.DataFrame()
                if not bad_els.empty and "ELS_wk_ratio" in bad_els.columns:
                    r = bad_els.loc[bad_els["ELS_wk_ratio"].fillna(-1).idxmax()]
                    add(panel, "Alta", r.get("Verification_reason", "ELS/fendilhação não conforme"), r.get("Recommended_action", "rever ELS/fendilhação"))
                else:
                    r = bad.loc[bad["util_M"].fillna(-1).idxmax()] if not bad.empty and "util_M" in bad.columns else g_global.loc[g_global["util_max"].fillna(-1).idxmax()]
                    add(panel, "Alta", r.get("Verification_reason", "ELU/flexão não conforme"), r.get("Recommended_action", "rever dimensionamento"))
            elif "ELS_wk_status" in g_global.columns and ("Verificar" in set(g_global["ELS_wk_status"].astype(str)) or "Não conforme" in set(g_global["ELS_wk_status"].astype(str))):
                # v2.8.3: seleccionar de forma fail-safe tanto linhas ``Não conforme`` como
                # ``Verificar``. Na v2.8.2 filtrava-se apenas ``Verificar`` e, quando só
                # existiam linhas ``Não conforme``, o acesso ``iloc[0]`` era feito sobre
                # um DataFrame vazio, originando ``single positional indexer is out-of-bounds``.
                r = select_worst_els_wk_issue(g_global)
                if r is not None:
                    wk_state = str(r.get("ELS_wk_status", "Verificar"))
                    sev = "Alta" if wk_state == "Não conforme" else "Média"
                    label = "não satisfeito" if wk_state == "Não conforme" else "requer verificação"
                    add(
                        panel, sev,
                        f"ELS/fendilhação {label} em ELS-QP {r.get('Case','')}: wk/wmax={safe_float(r.get('ELS_wk_ratio',0),0):.3f}",
                        "Confirmar combinação ELS; reduzir diâmetro/espaçamento, aumentar armadura distribuída ou rever wmax."
                    )
            elif "Verificar" in statuses:
                vg = g_global[g_global.get("Status", pd.Series(dtype=str)).astype(str) == "Verificar"].copy()
                r = vg.loc[vg["util_max"].fillna(-1).idxmax()] if not vg.empty else g_global.loc[g_global["util_max"].fillna(-1).idxmax()]
                add(panel, "Média", r.get("Verification_reason", "Verificar"), r.get("Recommended_action", "validar manualmente"))
            elif "OK*" in statuses or ("ELS_wk_status" in g_global.columns and "OK*" in set(g_global["ELS_wk_status"].astype(str))):
                if "ELS_wk_status" in g_global.columns and "OK*" in set(g_global["ELS_wk_status"].astype(str)):
                    qpg = g_global[g_global["ELS_wk_status"].astype(str) == "OK*"].copy()
                    r = qpg.loc[qpg["ELS_wk_ratio"].fillna(-1).idxmax()]
                    add(panel, "Baixa", f"ELS/fendilhação satisfeito mas próximo do limite na combinação {r.get('Case','')}: wk/wmax={safe_float(r.get('ELS_wk_ratio',0),0):.3f}", "Confirmar combinação ELS, wmax e pormenorização final.")
                else:
                    r = g_global.loc[g_global["util_max"].fillna(-1).idxmax()]
                    add(panel, "Baixa", r.get("Verification_reason", "OK com aviso"), r.get("Recommended_action", "confirmar notas"))

            mxy_diag = assess_mxy_dominance(g_global if not g_global.empty else g)
            if mxy_diag.get("MXY_diagnostic_available") == "Sim" and safe_float(mxy_diag.get("MXY_ratio_robust", 0.0), 0.0) > 0.40:
                add(
                    panel,
                    "Média",
                    (
                        "MXY relevante no painel: "
                        f"P95(|MXY|)/P95(max(|MXX|,|MYY|))={safe_float(mxy_diag.get('MXY_ratio_robust',0),0):.2f}; "
                        f"MXYmax/P95(Mnormal)={safe_float(mxy_diag.get('MXY_ratio_max_to_P95_normal',0),0):.2f}."
                    ),
                    "Confirmar eixos locais, orientação da normal e transformação Wood & Armer. O indicador é estatístico e não altera os momentos de cálculo."
                )
            if "FEM_peak_flag" in g.columns and "Sim" in set(g["FEM_peak_flag"].astype(str)):
                rr = safe_float(g["FEM_peak_ratio"].max(), 0.0)
                gov_peak_fail = False
                if "FEM_peak_governing_row" in g.columns:
                    gov_peak_fail = bool(((g["FEM_peak_governing_row"].astype(str) == "Sim") & (g["Status"].astype(str) == "Não conforme") & (g["Case_classification"].astype(str) == "ELU")).any())
                # A não conformidade governada pelo pico já foi registada acima como diagnóstico de severidade Alta.
                # Evita duplicar a mesma ocorrência numa segunda linha.
                if not gov_peak_fail:
                    add(
                        panel,
                        "Média",
                        f"Pico local potencial nos momentos de placa (max/P95={rr:.2f}).",
                        "Localizar o nó/caso relevante e confirmar significado físico, discretização, apoios/cargas concentradas e possíveis singularidades. O SlabsEC2 não suavizou o valor."
                    )
            if "Auto_peak_local_node" in g.columns and "Sim" in set(g["Auto_peak_local_node"].astype(str)):
                ag = g[g["Auto_peak_local_node"].astype(str) == "Sim"].copy()
                nodes = sorted({str(x) for x in ag.get("Node", pd.Series(dtype=object)).dropna().astype(str)})
                util_loc = safe_float(ag.get("Local_peak_util_raw", pd.Series([0.0])).max(), 0.0)
                wk_loc = safe_float(ag.get("Local_peak_wk_ratio_raw", pd.Series([0.0])).max(), 0.0)
                add(
                    panel, "Média",
                    f"Concentração nodal separada do envelope distribuído: {len(nodes)} nó(s). "
                    f"Utilização RAW local máx.={util_loc:.3f}; wk/wmax RAW local máx.={wk_loc:.3f}.",
                    "Verificar e pormenorizar localmente a concentração. Estes valores RAW não condicionam o estado global distribuído, mas não são apagados nem considerados conformes automaticamente."
                )

            if "Singular_node_confirmed" in g.columns and "Sim" in set(g["Singular_node_confirmed"].astype(str)):
                sg = g[g["Singular_node_confirmed"].astype(str) == "Sim"].copy()
                nodes = sorted({str(x) for x in sg.get("Node", pd.Series(dtype=object)).dropna().astype(str)})
                util_loc = safe_float(sg.get("Local_peak_util_raw", pd.Series([0.0])).max(), 0.0)
                wk_loc = safe_float(sg.get("Local_peak_wk_ratio_raw", pd.Series([0.0])).max(), 0.0)
                add(
                    panel, "Alta",
                    f"Singularidade(s) confirmada(s) pelo utilizador excluída(s) do envelope distribuído: nó(s) {', '.join(nodes)}. "
                    f"Utilização local ELU máx.={util_loc:.3f}; wk/wmax local máx.={wk_loc:.3f}.",
                    "Executar verificação/pormenorização local específica. Esta exclusão é uma decisão explícita de engenharia e não transforma o pico em resultado conforme."
                )

            if "is_QP_crack_case" in g.columns and "Sim" not in set(g["is_QP_crack_case"].astype(str)):
                # Só é problema se wk foi activado; neste caso a coluna QP existe, mas o caso não apareceu no painel.
                if "wk_check_enabled" in g.columns and "Sim" in set(g["wk_check_enabled"].astype(str)):
                    add(panel, "Média", "sem linhas ELS-QP para verificação wk", "exportar/colar também as combinações ELS quase-permanentes")
        if not rows:
            rows.append({"Painel": "-", "Severidade": "Informação", "Problema": "sem problemas críticos detectados", "Acção recomendada": "validar hipóteses gerais, eixos locais e modelo estrutural", "Origem": "Diagnóstico"})
        order = {"Alta": 0, "Média": 1, "Baixa": 2, "Informação": 3}
        out = pd.DataFrame(rows)
        out["_ord"] = out["Severidade"].map(order).fillna(9)
        return out.sort_values(["_ord", "Painel"]).drop(columns=["_ord"]).reset_index(drop=True)

    def technical_message_for_result(self, r: pd.Series) -> Tuple[str, str]:
        status = str(r.get("Status", ""))
        crack_status = str(r.get("Crack_control_status", ""))
        els_wk_status = str(r.get("ELS_wk_status", ""))
        util_m = safe_float(r.get("util_M", 0.0), 0.0)
        mxy_ratio = safe_float(r.get("MXY_ratio", 0.0), 0.0)
        input_mode = str(r.get("Moment_input_mode", ""))
        qp = str(r.get("is_QP_crack_case", ""))
        wk_enabled = str(r.get("wk_check_enabled", "")) == "Sim"
        case = str(r.get("Case", ""))
        wk_eval = safe_float(r.get("ELS_wk_max_mm", float("nan")), float("nan"))
        wk_ratio = safe_float(r.get("ELS_wk_ratio", float("nan")), float("nan"))
        wmax = safe_float(r.get("wmax_mm", 0.0), 0.0)

        if status == "Informativo":
            return (
                "Linha sem momento de dimensionamento relevante. O registo é mantido apenas para rastreabilidade dos dados importados.",
                "Não considerar esta linha como condicionante da armadura; verificar apenas se o caso/nó deve permanecer na tabela de origem."
            )
        case_class = str(r.get("Case_classification", ""))
        if status == "Não conforme" and case_class == "ELS-QP":
            return (
                f"ELS de fendilhação não satisfeito em ELS-QP {case}. wk,max={wk_eval:.3f} mm > wmax={wmax:.3f} mm.",
                "Aumentar armadura distribuída/reduzir espaçamento, confirmar a combinação ELS-QP e o wmax aplicável antes da adopção da solução."
            )
        if status == "Não conforme":
            if str(r.get("FEM_peak_governing_row", "Não")) == "Sim":
                rr = safe_float(r.get("FEM_peak_ratio", 0.0), 0.0)
                return (
                    f"ELU de flexão não satisfeito — resultado condicionado por pico local potencial de esforços (max/P95={rr:.2f}).",
                    "Localizar o nó/caso governante e confirmar significado físico, malha, apoio/carga concentrada ou singularidade. O valor não foi suavizado; só depois rever armadura/espessura ou efectuar tratamento local adequado."
                )
            return (
                "ELU de flexão não satisfeito para a faixa de 1,00 m com a solução harmonizada do painel.",
                "Aumentar a armadura, reduzir o espaçamento, aumentar a espessura da laje ou rever os esforços do modelo antes de emissão de projecto."
            )
        if wk_enabled and qp == "Sim" and els_wk_status in ("Verificar", "Não conforme"):
            return (
                f"ELS de fendilhação não satisfeito em ELS-QP {case}. wk,max={wk_eval:.3f} mm > wmax={wmax:.3f} mm.",
                "Confirmar as combinações ELS-QP; se o resultado se mantiver, adoptar menor diâmetro/menor espaçamento, aumentar a armadura distribuída ou rever wmax conforme classe de exposição."
            )
        if wk_enabled and qp == "Sim" and els_wk_status == "OK*":
            return (
                f"ELS de fendilhação satisfeito, mas próximo do limite, em ELS-QP {case}. wk/wmax={wk_ratio:.3f}.",
                "Manter a solução apenas após confirmação da combinação ELS, classe de exposição e pormenorização final; considerar menor espaçamento se se pretender maior margem."
            )
        if wk_enabled and qp != "Sim" and status == "Verificar":
            return (
                "A linha não pertence a nenhuma combinação ELS-QP definida para a verificação directa de wk; não deve ser usada como governante de fendilhação.",
                "Separar a leitura ELU/ELS no resumo; confirmar que as combinações ELS-QP foram exportadas adequadamente."
            )
        if util_m > 0.98 and status in ("OK", "OK*"):
            return (
                "ELU satisfeito com margem reduzida. A utilização à flexão encontra-se próxima da capacidade resistente adoptada.",
                "Manter a solução apenas após confirmação dos arredondamentos de armadura, eixos locais e coerência dos esforços importados."
            )
        if (not input_mode.startswith("direct_wa")) and mxy_ratio > 0.40:
            return (
                "Momento torsor de placa significativo relativamente aos momentos principais. A armadura foi obtida por transformação interna dos momentos de placa.",
                "Confirmar orientação dos eixos locais, sentido da normal dos painéis e adequação do método de transformação adoptado."
            )
        if status == "OK*" or crack_status == "OK*":
            return (
                "Verificação global satisfeita com observação técnica. Existem condicionantes de modelação, pormenorização ou controlo que devem ser confirmadas pelo projectista.",
                "Confirmar hipóteses de entrada, orientação dos eixos locais, convenção de sinais e disposições construtivas antes da adopção final."
            )
        if status == "Verificar":
            return (
                "Resultado a verificar pelo projectista. Foi detectada uma condição que não permite classificação automática robusta como OK.",
                "Consultar a aba Detalhe, confirmar combinações, eixos locais, unidades e pormenorização; ajustar a solução se necessário."
            )
        return (
            "Verificações efectuadas satisfazem os critérios adoptados para dimensionamento à flexão, armadura mínima, espaçamento e controlo configurado.",
            "Sem acção correctiva automática. Validar a pormenorização final, apoios, aberturas, punçoamento/corte local e coerência do modelo estrutural."
        )

    def apply_professional_messages(self, results: pd.DataFrame) -> pd.DataFrame:
        if results is None or results.empty:
            return results
        # O DataFrame recebido já é exclusivo desta execução; actualizar in-place evita uma
        # segunda cópia integral. Dicionários são mais leves que Series criadas por iterrows.
        out = results
        if len(out) >= LARGE_DATASET_THRESHOLD:
            # O núcleo já devolve Verification_reason/Recommended_action. Regerar mensagens
            # para 300k+ linhas criava uma lista de dicionários com centenas de colunas e
            # duplicava centenas de MB. Em modo grande, as mensagens profissionais completas
            # são produzidas nos resumos/governantes; a tabela linha-a-linha preserva a mensagem
            # emitida pelo núcleo sem criar colunas textuais duplicadas.
            return out
        reasons, actions = [], []
        for r in out.to_dict("records"):
            reason, action = self.technical_message_for_result(r)
            reasons.append(reason); actions.append(action)
        out["Verification_reason"] = reasons
        out["Recommended_action"] = actions
        out["Leitura_técnica"] = reasons
        out["Acção_de_projecto"] = actions
        return out

    def build_rebar_sketches(self, zones: pd.DataFrame) -> pd.DataFrame:
        if zones is None or zones.empty:
            return pd.DataFrame()
        rows = []
        for _, r in zones.iterrows():
            panels_txt = r.get("Painéis", "") or r.get("Panel", "")
            xp = r.get("X+_final", r.get("X+", "-")); xn = r.get("X-_final", r.get("X-", "-"))
            yp = r.get("Y+_final", r.get("Y+", "-")); yn = r.get("Y-_final", r.get("Y-", "-"))
            zone_type = r.get("Tipo_zona", "")
            sketch = (
                f"Zona {r.get('Zona','')} | Painel(is): {panels_txt} | {zone_type}\n"
                f"Face superior: X = {xp} | Y = {yp}\n"
                f"Face inferior: X = {xn} | Y = {yn}\n"
                "Nota: no zonamento espacial v2.14, a base distribuída é mantida e os reforços locais são "
                "verificados nos próprios envelopes ELU/ELS; o envelope FEM raw não é suavizado."
            )
            rows.append({
                "Zona": r.get("Zona", ""), "Painéis": panels_txt, "Croquis_textual": sketch,
                "Nota_desenho": f"Faces físicas apresentadas. Para RAW: M>0 tracciona a face {str(self.var_positive_moment_face.get()).lower()}. Confirmar normal/eixos locais do modelo antes de desenhar."
            })
        return pd.DataFrame(rows)

    def _derived_table_source(self, results: pd.DataFrame) -> pd.DataFrame:
        """Reduz apenas tabelas derivadas da GUI em datasets muito grandes.

        O cálculo e ``df_results`` continuam a conter todas as linhas. A selecção inclui os
        governantes ELU, ELS-QP, tensões ELS e deslocamento por painel, eliminando milhões de
        células duplicadas em abas auxiliares.
        """
        if results is None or results.empty or len(results) <= LARGE_DATASET_THRESHOLD:
            return results
        idx = set()
        for _panel, g in results.groupby("Panel", dropna=False, sort=False, observed=True):
            for col in ("util_M", "ELS_wk_ratio", "ELS_sigma_s_max_MPa", "ELS_sigma_c_max_MPa", "UGZ_down_mm"):
                if col in g.columns:
                    vals = pd.to_numeric(g[col], errors="coerce")
                    if vals.notna().any():
                        idx.add(vals.idxmax())
            if "Status" in g.columns:
                bad = g[g["Status"].astype(str).isin(["Não conforme", "Verificar"])]
                if not bad.empty:
                    idx.update(bad.head(50).index.tolist())
        if not idx:
            return results.head(LARGE_DERIVED_MAX_ROWS)
        keep = sorted(idx)[:LARGE_DERIVED_MAX_ROWS]
        out = results.loc[keep].copy()
        out["Large_dataset_scope"] = "Tabela derivada: apenas governantes/avisos; cálculo completo preservado em Resultados."
        return out

    def build_detailed_check(self, results: pd.DataFrame) -> pd.DataFrame:
        if results is None or results.empty:
            return pd.DataFrame()
        results = self._derived_table_source(results)
        cols = [
            "Panel", "Node", "Case", "Case_classification", "ULS_cases", "Combo_type", "Moment_input_mode", "Equivalent_moment_source", "MXX_kNm_m", "MYY_kNm_m", "MXY_kNm_m", "MXX+_equiv_kNm_m", "MXX-_equiv_kNm_m", "MYY+_equiv_kNm_m", "MYY-_equiv_kNm_m",
            "Mx+_WA", "Mx-_WA", "My+_WA", "My-_WA", "WA_method",
            "Asx+_req_mm2_m", "Asx-_req_mm2_m", "Asy+_req_mm2_m", "Asy-_req_mm2_m",
            "As_slab_min_face_mm2_m", "As_crack_min_face_mm2_m", "X+_minimum_valid", "X-_minimum_valid", "Y+_minimum_valid", "Y-_minimum_valid", "X+_rebar", "X-_rebar", "Y+_rebar", "Y-_rebar",
            "X+_base", "X-_base", "Y+_base", "Y-_base", "X+_additional", "X-_additional", "Y+_additional", "Y-_additional",
            "Asx+_base_mm2_m", "Asx+_add_mm2_m", "Asx-_base_mm2_m", "Asx-_add_mm2_m", "Asy+_base_mm2_m", "Asy+_add_mm2_m", "Asy-_base_mm2_m", "Asy-_add_mm2_m",
            "Constructability_status", "Constructability_note",
            "MRd_x+_kNm_m", "MRd_x-_kNm_m", "MRd_y+_kNm_m", "MRd_y-_kNm_m",
            "QXX_kN_m", "QYY_kN_m", "VRdc_x_kN_m", "VRdc_y_kN_m", "VRdmax_x_kN_m", "VRdmax_y_kN_m",
            "UGZ_mm", "UGZ_down_mm", "Deflection_limit_mm", "util_deflection", "Deflection_status", "Deflection_note",
            "wk_x+_mm", "wk_x-_mm", "wk_y+_mm", "wk_y-_mm", "wk_max_mm", "wmax_mm",
            "x_cr_x+_mm", "x_cr_x-_mm", "x_cr_y+_mm", "x_cr_y-_mm",
            "h_ceff_x+_mm", "h_ceff_x-_mm", "h_ceff_y+_mm", "h_ceff_y-_mm",
            "Ac_eff_x+_mm2", "Ac_eff_x-_mm2", "Ac_eff_y+_mm2", "Ac_eff_y-_mm2",
            "rho_p_eff_x+", "rho_p_eff_x-", "rho_p_eff_y+", "rho_p_eff_y-",
            "c_eff_x+_mm", "c_eff_x-_mm", "c_eff_y+_mm", "c_eff_y-_mm",
            "phi_eq_x+_mm", "phi_eq_x-_mm", "phi_eq_y+_mm", "phi_eq_y-_mm",
            "eps_diff_x+", "eps_diff_x-", "eps_diff_y+", "eps_diff_y-",
            "sigma_s_x+_MPa", "sigma_s_x-_MPa", "sigma_s_y+_MPa", "sigma_s_y-_MPa",
            "sigma_c_x+_MPa", "sigma_c_x-_MPa", "sigma_c_y+_MPa", "sigma_c_y-_MPa",
            "ELS_stress_status", "ELS_sigma_s_max_MPa", "ELS_sigma_s_limit_MPa",
            "ELS_sigma_c_max_MPa", "ELS_sigma_c_char_limit_MPa", "ELS_sigma_c_qp_linear_limit_MPa", "ELS_stress_note",
            "Section_domain_valid", "MRd_singly_lim_min_kNm_m", "xi_bal_min", "steel_yields_all_faces",
            "phi_ctrl_x+_mm", "s_eff_x+_mm", "phi_lim_x+_EC2_mm", "s_lim_x+_EC2_mm",
            "phi_ctrl_x-_mm", "s_eff_x-_mm", "phi_lim_x-_EC2_mm", "s_lim_x-_EC2_mm",
            "phi_ctrl_y+_mm", "s_eff_y+_mm", "phi_lim_y+_EC2_mm", "s_lim_y+_EC2_mm",
            "phi_ctrl_y-_mm", "s_eff_y-_mm", "phi_lim_y-_EC2_mm", "s_lim_y-_EC2_mm",
            "Crack_status_x+", "Crack_status_x-", "Crack_status_y+", "Crack_status_y-",
            "util_M", "util_Qx", "util_Qy", "util_max", "Panel_solution_mode", "Panel_solution_verified_all_cases",
            "Integrity_status", "Integrity_note",
            "Singular_node_confirmed", "Excluded_from_distributed_envelope", "Local_peak_util_raw", "Local_peak_wk_ratio_raw", "Local_peak_status",
            "FEM_peak_ratio", "FEM_peak_ratio_p99", "FEM_peak_flag", "FEM_peak_classification", "FEM_peak_node_fraction_90", "FEM_peak_recurrence_cases", "FEM_peak_note",
            "Status", "Verification_reason", "Recommended_action", "Notes"
        ]
        out = results[[c for c in cols if c in results.columns]].copy()
        out["Formula_As"] = "Secção rectangular por metro: T=As*fyd; C=0,8*x*b*fcd; MRd=As*fyd*(d-0,4x); mínimos EC2 9.3.1.1 e 7.3.2 aplicados por face"
        out["Formula_Q"] = "QXX/QYY são apenas informativos nesta versão; corte e punçoamento devem ser verificados em módulo específico."
        out["Formula_wk"] = "EC2 7.3.4: secção fendilhada transformada; hc,eff=min[2,5(h-d),(h-x)/3,h/2]; c é o recobrimento efectivo da família considerada; phi_eq pela expressão 7.12 quando há diâmetros diferentes; wk=sr,max*(eps_sm-eps_cm); kt=0,4 em ELS-QP"
        out["Formula_ELS_tensoes"] = "EC2 7.2: ELS característica controla sigma_s<=0,8fyk e reporta sigma_c<=0,6fck; ELS-QP verifica sigma_c<=0,45fck para hipótese de fluência linear. Valores recomendados, confirmar Anexo Nacional/aplicabilidade."
        out["Formula_dominio_ELU"] = "Secção simplesmente armada: a resistência só é creditada enquanto eps_s>=eps_yd; acima do limite balanceado não é adicionada capacidade por mais aço de tracção."
        out["Formula_UGZ"] = "UGZ é convertido para mm; negativo = para baixo; valor apenas informativo, sem limite L/n."
        return out

    def build_panel_summary(self, results: pd.DataFrame) -> pd.DataFrame:
        if results is None or results.empty:
            return pd.DataFrame()
        rows = []
        for panel, grp in results.groupby("Panel", dropna=False, observed=True):
            g_all = grp.copy()
            g_design = g_all[g_all.get("Design_relevant", "Sim").astype(str) != "Não"].copy() if "Design_relevant" in g_all.columns else g_all.copy()
            g = g_design if not g_design.empty else g_all.copy()

            # ELU/flexão: evita que qualquer combinação ELS seja apresentada como caso governante ELU
            # quando existem outras combinações de dimensionamento no mesmo painel.
            if "Case_classification" in g.columns:
                g_elu = g[g["Case_classification"].astype(str) == "ELU"].copy()
            else:
                g_elu = g[g.get("is_QP_crack_case", "Não").astype(str) != "Sim"].copy() if "is_QP_crack_case" in g.columns else g.copy()
            if g_elu.empty:
                g_elu = g.copy()
            r_elu = g_elu.loc[g_elu["util_M"].fillna(-1.0).idxmax()] if "util_M" in g_elu.columns and not g_elu.empty else g.iloc[0]
            util_elu = safe_float(g_elu["util_M"].max() if "util_M" in g_elu.columns else 0.0, 0.0)
            if "Status" in g_elu.columns and "Não conforme" in set(g_elu["Status"].astype(str)):
                estado_elu = "Não conforme"
                peak_ratio = safe_float(r_elu.get("FEM_peak_ratio", 0.0), 0.0)
                peak_governs = str(r_elu.get("FEM_peak_governing_row", "Não")) == "Sim"
                limit_reached = str(r_elu.get("Rebar_limit_reached", "Não")) == "Sim"
                if peak_governs:
                    motivo_elu = (
                        f"ELU/flexão não satisfeito — condicionado por pico local potencial de esforços: "
                        f"utilização máxima={util_elu:.3f}; max/P95={peak_ratio:.2f}."
                    )
                    acao_elu = (
                        "Localizar o nó/caso governante e confirmar significado físico, malha, apoio/carga concentrada ou singularidade. "
                        "O pico não foi suavizado automaticamente. Só depois decidir sobre reforço/espessura ou tratamento local do resultado."
                    )
                else:
                    motivo_elu = f"ELU/flexão não satisfeito: utilização máxima={util_elu:.3f}."
                    acao_elu = "Aumentar armadura, reduzir espaçamento, aumentar espessura ou rever esforços de cálculo."
                if limit_reached:
                    acao_elu += (
                        f" A armadura uniforme atingiu o limite configurado Ømax; o programa não adoptou diâmetros superiores ao definido pelo utilizador."
                    )
            elif util_elu > 0.98:
                estado_elu = "OK*"
                motivo_elu = f"ELU/flexão satisfeito com margem reduzida: utilização máxima={util_elu:.3f}."
                acao_elu = "Confirmar arredondamento de armadura, eixos locais e pormenorização."
            else:
                estado_elu = "OK"
                motivo_elu = f"ELU/flexão satisfeito: utilização máxima={util_elu:.3f}."
                acao_elu = "Sem acção correctiva para flexão; validar hipóteses gerais de projecto."

            # ELS/fendilhação: apenas as combinações ELS-QP definidas podem governar wk.
            qp_rows = g[g.get("ELS_wk_evaluated", "Não").astype(str) == "Sim"].copy() if "ELS_wk_evaluated" in g.columns else pd.DataFrame()
            wk_enabled = "wk_check_enabled" in g.columns and "Sim" in set(g["wk_check_enabled"].astype(str))
            qp_case = str(g["QP_crack_case"].dropna().iloc[0]) if "QP_crack_case" in g.columns and not g["QP_crack_case"].dropna().empty else ""
            if wk_enabled and not qp_case:
                estado_els = "Verificar"
                motivo_els = "ELS/fendilhação: verificação wk activa, mas sem combinações ELS quase-permanentes indicadas."
                acao_els = "Indicar uma ou mais combinações ELS quase-permanentes ou desactivar a verificação directa de wk."
                r_els = None
                wk_max = float("nan"); wk_ratio = float("nan"); case_els = ""; node_els = ""
            elif wk_enabled and qp_rows.empty:
                estado_els = "Verificar"
                motivo_els = f"ELS/fendilhação: não foram encontradas linhas de nenhuma combinação ELS-QP ({qp_case}) para este painel."
                acao_els = "Exportar/colar pelo menos uma combinação ELS-QP aplicável a cada painel."
                r_els = None
                wk_max = float("nan"); wk_ratio = float("nan"); case_els = qp_case; node_els = ""
            elif wk_enabled:
                r_els = qp_rows.loc[qp_rows["ELS_wk_ratio"].fillna(-1.0).idxmax()]
                wk_max = safe_float(r_els.get("ELS_wk_max_mm", float("nan")), float("nan"))
                wk_ratio = safe_float(r_els.get("ELS_wk_ratio", float("nan")), float("nan"))
                case_els = r_els.get("Case", "")
                node_els = r_els.get("Node", "")
                if str(r_els.get("ELS_wk_status", "")) in ("Verificar", "Não conforme") or (math.isfinite(wk_ratio) and wk_ratio > 1.0):
                    estado_els = "Não conforme"
                    motivo_els = f"ELS/fendilhação não satisfeito em ELS-QP {case_els}: wk,max={wk_max:.3f} mm; wk/wmax={wk_ratio:.3f}."
                    acao_els = "Confirmar as combinações ELS-QP; reduzir diâmetro/espaçamento, aumentar armadura distribuída ou rever wmax/classe de exposição."
                elif math.isfinite(wk_ratio) and wk_ratio >= 0.90:
                    estado_els = "OK*"
                    motivo_els = f"ELS/fendilhação satisfeito, mas próximo do limite, em ELS-QP {case_els}: wk/wmax={wk_ratio:.3f}."
                    acao_els = "Confirmar pormenorização e combinação ELS; considerar menor espaçamento se se pretender maior margem."
                else:
                    estado_els = "OK"
                    motivo_els = f"ELS/fendilhação satisfeito em ELS-QP {case_els}: wk/wmax={wk_ratio:.3f}."
                    acao_els = "Sem acção correctiva para fendilhação; validar classe de exposição e wmax adoptado."
            else:
                estado_els = "Não avaliado"
                motivo_els = "ELS/fendilhação directa por wk não avaliado; aplicado apenas controlo simplificado, quando configurado."
                acao_els = "Para verificação directa de abertura de fendas, activar wk e indicar uma ou mais combinações ELS quase-permanentes."
                r_els = None
                wk_max = float("nan"); wk_ratio = float("nan"); case_els = ""; node_els = ""

            # ELS/limitação de tensões (EC2 7.2).
            stress_enabled = "ELS_stress_check_enabled" in g.columns and "Sim" in set(g["ELS_stress_check_enabled"].astype(str))
            char_rows = g[g.get("Case_classification", "").astype(str) == "ELS-CHAR"].copy() if "Case_classification" in g.columns else pd.DataFrame()
            qp_stress_rows = g[g.get("Case_classification", "").astype(str) == "ELS-QP"].copy() if "Case_classification" in g.columns else pd.DataFrame()
            if stress_enabled and char_rows.empty:
                estado_stress = "Verificar"
                motivo_stress = "ELS/limitação de tensões activa, mas sem combinação característica disponível para o painel."
                acao_stress = "Indicar pelo menos uma combinação ELS característica para verificar sigma_s e sigma_c segundo EC2 7.2."
                r_stress = None
            elif stress_enabled:
                rank_stress = {"Não conforme": 4, "Verificar": 3, "OK*": 2, "OK": 1, "Informativo": 0, "Não avaliado": 0}
                stress_pool = pd.concat([char_rows, qp_stress_rows], ignore_index=False) if not qp_stress_rows.empty else char_rows
                if stress_pool.empty:
                    estado_stress = "Verificar"; motivo_stress = "ELS/tensões sem linhas avaliáveis."; acao_stress = "Confirmar combinações ELS."; r_stress = None
                else:
                    stress_pool = stress_pool.copy()
                    stress_pool["__rank_stress"] = stress_pool.get("ELS_stress_status", pd.Series(index=stress_pool.index, dtype=str)).astype(str).map(rank_stress).fillna(0)
                    r_stress = stress_pool.loc[stress_pool["__rank_stress"].idxmax()]
                    estado_stress = str(r_stress.get("ELS_stress_status", "Não avaliado"))
                    motivo_stress = str(r_stress.get("ELS_stress_note", "")) or "Limitação de tensões ELS avaliada."
                    acao_stress = "Sem acção correctiva." if estado_stress in ("OK", "Informativo") else "Rever armadura/combinações e a aplicabilidade dos limites EC2 7.2; para sigma_c,QP>0,45fck considerar fluência não linear."
            else:
                estado_stress = "Não avaliado"; motivo_stress = "Limitação de tensões ELS desactivada."; acao_stress = "Activar para uma verificação de serviço mais completa."; r_stress = None

            if estado_elu == "Não conforme":
                status = "Não conforme"
                motivo = motivo_elu
                acao = acao_elu
            elif estado_els == "Não conforme" or estado_stress == "Não conforme":
                status = "Não conforme"
                motivo = motivo_els if estado_els == "Não conforme" else motivo_stress
                acao = acao_els if estado_els == "Não conforme" else acao_stress
            elif estado_els == "Verificar" or estado_stress == "Verificar":
                status = "Verificar"
                motivo = " | ".join(x for x in [motivo_els if estado_els == "Verificar" else "", motivo_stress if estado_stress == "Verificar" else ""] if x)
                acao = " | ".join(x for x in [acao_els if estado_els == "Verificar" else "", acao_stress if estado_stress == "Verificar" else ""] if x)
            elif estado_elu == "OK*" or estado_els == "OK*" or estado_stress == "OK*":
                status = "OK*"
                motivo = " | ".join([m for m in [motivo_elu if estado_elu == "OK*" else "", motivo_els if estado_els == "OK*" else "", motivo_stress if estado_stress == "OK*" else ""] if m])
                acao = " | ".join([a for a in [acao_elu if estado_elu == "OK*" else "", acao_els if estado_els == "OK*" else "", acao_stress if estado_stress == "OK*" else ""] if a])
            else:
                status = "OK"
                motivo = " | ".join(x for x in [motivo_elu, motivo_els if estado_els != "Não avaliado" else "", motivo_stress if estado_stress not in ("Não avaliado", "Informativo") else ""] if x)
                acao = "Validar pormenorização final, punçoamento/corte local e coerência do modelo estrutural."

            # Uma exclusão manual de singularidade nunca conduz a OK automático. O dimensionamento
            # distribuído pode satisfazer, mas o pico mantém uma verificação local obrigatória.
            sing_rows = g_all[g_all.get("Singular_node_confirmed", "Não").astype(str) == "Sim"].copy() if "Singular_node_confirmed" in g_all.columns else pd.DataFrame()
            singular_nodes = sorted({str(x) for x in sing_rows.get("Node", pd.Series(dtype=object)).dropna().astype(str)}) if not sing_rows.empty else []
            local_peak_util = safe_float(sing_rows.get("Local_peak_util_raw", pd.Series([0.0])).max(), 0.0) if not sing_rows.empty else 0.0
            if singular_nodes:
                singular_txt = ", ".join(singular_nodes)
                motivo = (
                    f"{motivo} | Singularidade(s) confirmada(s) pelo utilizador excluída(s) do envelope distribuído: nó(s) {singular_txt}; "
                    f"utilização local bruta máxima={local_peak_util:.3f}."
                )
                acao = (
                    f"{acao} Executar verificação/pormenorização local específica nos nós {singular_txt}. "
                    "A exclusão do envelope distribuído não elimina a solicitação local nem constitui conformidade automática."
                )

            # A separação estatística P99 é uma política de pós-processamento para a armadura
            # distribuída; nunca converte o painel em OK automático. Os valores RAW são mantidos
            # e os nós separados exigem verificação/pormenorização local explícita.
            auto_rows = g_all[g_all.get("Auto_peak_local_node", "Não").astype(str) == "Sim"].copy() if "Auto_peak_local_node" in g_all.columns else pd.DataFrame()
            auto_nodes = sorted({str(x) for x in auto_rows.get("Node", pd.Series(dtype=object)).dropna().astype(str)}) if not auto_rows.empty else []
            auto_peak_util = safe_float(auto_rows.get("util_M", pd.Series([0.0])).max(), 0.0) if not auto_rows.empty else 0.0
            auto_policy = str(auto_rows.get("Distributed_peak_policy", pd.Series([""])).iloc[0]) if not auto_rows.empty else ""
            if auto_nodes:
                auto_txt = ", ".join(auto_nodes[:20]) + (f" … (+{len(auto_nodes)-20})" if len(auto_nodes) > 20 else "")
                motivo = (
                    f"{motivo} | Concentração local separada automaticamente do envelope distribuído ({auto_policy}): "
                    f"{len(auto_nodes)} nó(s); utilização RAW máxima com a armadura distribuída={auto_peak_util:.3f}."
                )
                acao = (
                    f"{acao} Verificar/pormenorizar localmente os nós separados ({auto_txt}). "
                    "O valor RAW permanece no relatório; esta política não constitui suavização nem verificação local."
                )

            notes = sorted({str(x) for x in g.get("Notes", pd.Series(dtype=str)).dropna() if str(x).strip()})
            defl_idx = g["UGZ_down_mm"].fillna(-1.0).idxmax() if "UGZ_down_mm" in g.columns else r_elu.name
            r_defl = g.loc[defl_idx]
            rows.append({
                "Panel": panel,
                "n_linhas_analisadas": len(g_all),
                "n_linhas_dimensionamento": len(g),
                "Status_global": status,
                "Motivo_estado": motivo,
                "Acção_recomendada": acao,
                "estado_ELU": estado_elu,
                "motivo_ELU": motivo_elu,
                "caso_governante_ELU": r_elu.get("Case", ""),
                "node_governante_ELU": r_elu.get("Node", ""),
                "util_ELU_max": util_elu,
                "estado_ELS_wk": estado_els,
                "motivo_ELS_wk": motivo_els,
                "caso_governante_ELS_wk": case_els,
                "node_governante_ELS_wk": node_els,
                "wk_max_mm": wk_max,
                "wk_wmax_ratio": wk_ratio,
                "estado_ELS_tensoes": estado_stress,
                "motivo_ELS_tensoes": motivo_stress,
                "caso_governante_ELS_tensoes": r_stress.get("Case", "") if r_stress is not None else "",
                "node_governante_ELS_tensoes": r_stress.get("Node", "") if r_stress is not None else "",
                "sigma_s_ELS_max_MPa": safe_float(r_stress.get("ELS_sigma_s_max_MPa", float("nan")), float("nan")) if r_stress is not None else float("nan"),
                "sigma_c_ELS_max_MPa": safe_float(r_stress.get("ELS_sigma_c_max_MPa", float("nan")), float("nan")) if r_stress is not None else float("nan"),
                "util_max": util_elu,
                "caso_governante": r_elu.get("Case", ""),
                "node_governante": r_elu.get("Node", ""),
                "util_M_max": util_elu,
                "caso_governante_M": r_elu.get("Case", ""),
                "node_governante_M": r_elu.get("Node", ""),
                "util_Qx_max": g["util_Qx"].max() if "util_Qx" in g.columns else 0.0,
                "caso_governante_Qx": "",
                "node_governante_Qx": "",
                "util_Qy_max": g["util_Qy"].max() if "util_Qy" in g.columns else 0.0,
                "util_N_prelim_max": g["util_N_prelim"].max() if "util_N_prelim" in g.columns else 0.0,
                "sigma_N_membrane_max_MPa": g["sigma_N_membrane_MPa"].max() if "sigma_N_membrane_MPa" in g.columns else 0.0,
                "caso_governante_Qy": "",
                "node_governante_Qy": "",
                "UGZ_down_max_mm": g["UGZ_down_mm"].max() if "UGZ_down_mm" in g.columns else 0.0,
                "util_flecha_max": g["util_deflection"].max() if "util_deflection" in g.columns else 0.0,
                "caso_governante_flecha": r_defl.get("Case", ""),
                "node_governante_flecha": r_defl.get("Node", ""),
                "MXX_abs_max_kNm_m": g["MXX_kNm_m"].abs().max() if "MXX_kNm_m" in g.columns else 0.0,
                "MYY_abs_max_kNm_m": g["MYY_kNm_m"].abs().max() if "MYY_kNm_m" in g.columns else 0.0,
                "MXY_abs_max_kNm_m": g["MXY_kNm_m"].abs().max() if "MXY_kNm_m" in g.columns else 0.0,
                "QXX_abs_max_kN_m": g["QXX_kN_m"].abs().max() if "QXX_kN_m" in g.columns else 0.0,
                "QYY_abs_max_kN_m": g["QYY_kN_m"].abs().max() if "QYY_kN_m" in g.columns else 0.0,
                "Asx_req_max_mm2_m": max(g["Asx+_req_mm2_m"].max(), g["Asx-_req_mm2_m"].max()) if "Asx+_req_mm2_m" in g.columns else 0.0,
                "Asy_req_max_mm2_m": max(g["Asy+_req_mm2_m"].max(), g["Asy-_req_mm2_m"].max()) if "Asy+_req_mm2_m" in g.columns else 0.0,
                "X+_max_rebar": r_elu.get("X+_rebar", ""),
                "X-_max_rebar": r_elu.get("X-_rebar", ""),
                "Y+_max_rebar": r_elu.get("Y+_rebar", ""),
                "Y-_max_rebar": r_elu.get("Y-_rebar", ""),
                "Solução_painel": r_elu.get("Panel_solution_mode", ""),
                "Verificada_todos_casos": "Sim" if "Sim" in set(g.get("Panel_solution_verified_all_cases", pd.Series(dtype=str)).astype(str)) else "Não",
                "Integridade_interna": "Falha interna" if "Falha interna" in set(g.get("Integrity_status", pd.Series(dtype=str)).astype(str)) else "OK",
                "Nota_integridade": " | ".join(dict.fromkeys(g.get("Integrity_note", pd.Series(dtype=str)).astype(str))) if "Integrity_note" in g.columns else "",
                "Pico_FEM": "Sim" if "Sim" in set(g.get("FEM_peak_flag", pd.Series(dtype=str)).astype(str)) else "Não",
                "Pico_FEM_ratio": safe_float(g.get("FEM_peak_ratio", pd.Series([0.0])).max(), 0.0),
                "Pico_FEM_governante": str(r_elu.get("FEM_peak_governing_row", "Não")),
                "Limite_armadura_atingido": str(r_elu.get("Rebar_limit_reached", "Não")),
                "Nota_limite_armadura": str(r_elu.get("Rebar_limit_note", "")),
                "Nós_singulares_confirmados": ", ".join(singular_nodes),
                "N_singulares_confirmados": len(singular_nodes),
                "Util_local_singular_max": local_peak_util,
                "Nós_pico_local_automático": ", ".join(auto_nodes),
                "N_pico_local_automático": len(auto_nodes),
                "Util_RAW_pico_local_automático": auto_peak_util,
                "Estado_local": "Verificar localmente" if (singular_nodes or auto_nodes) else "Não aplicável",
                "N_nós_locais": len(set(singular_nodes) | set(auto_nodes)),
                "Util_local_RAW_max": max(local_peak_util, auto_peak_util),
                "Política_envelope_distribuído": auto_policy,
                "Punçoamento": "Verificar separadamente",
                "Notas": " | ".join(notes[:4]),
            })
        return pd.DataFrame(rows).sort_values(["Status_global", "Panel"], ascending=[False, True]).reset_index(drop=True)

    def build_governing_design(self, results: pd.DataFrame) -> pd.DataFrame:
        if results is None or results.empty:
            return pd.DataFrame()
        rows = []
        for panel, g in results.groupby("Panel", dropna=False, observed=True):
            g_all = g.copy()
            gx_design = g_all[g_all.get("Design_relevant", "Sim").astype(str) != "Não"].copy() if "Design_relevant" in g_all.columns else g_all.copy()
            gx = gx_design if not gx_design.empty else g_all.copy()
            if "Case_classification" in gx.columns:
                gx_elu = gx[gx["Case_classification"].astype(str) == "ELU"].copy()
            else:
                gx_elu = gx[gx.get("is_QP_crack_case", "Não").astype(str) != "Sim"].copy() if "is_QP_crack_case" in gx.columns else gx.copy()
            if gx_elu.empty:
                gx_elu = gx.copy()
            def row_at_max(df, col):
                return df.loc[df[col].fillna(-1.0).idxmax()] if col in df.columns and not df.empty else gx.iloc[0]

            # Governantes por face/direcção. A armadura fornecida é única por painel,
            # pelo que As_prov é constante e não pode ser usada para identificar o caso governante.
            # ELU é determinado pelo maior momento equivalente da própria face/direcção;
            # ELS pelo maior wk nessa mesma face/direcção.
            rxp_elu = row_at_max(gx_elu, "MEd_x_sup_kNm_m")
            rxn_elu = row_at_max(gx_elu, "MEd_x_inf_kNm_m")
            ryp_elu = row_at_max(gx_elu, "MEd_y_sup_kNm_m")
            ryn_elu = row_at_max(gx_elu, "MEd_y_inf_kNm_m")
            rxp, rxn, ryp, ryn = rxp_elu, rxn_elu, ryp_elu, ryn_elu

            r_elu = row_at_max(gx_elu, "util_M")
            qp_rows = gx[gx.get("ELS_wk_evaluated", "Não").astype(str) == "Sim"].copy() if "ELS_wk_evaluated" in gx.columns else pd.DataFrame()
            r_els = row_at_max(qp_rows, "ELS_wk_ratio") if not qp_rows.empty else None
            rxp_els = row_at_max(qp_rows, "wk_x+_mm") if not qp_rows.empty else None
            rxn_els = row_at_max(qp_rows, "wk_x-_mm") if not qp_rows.empty else None
            ryp_els = row_at_max(qp_rows, "wk_y+_mm") if not qp_rows.empty else None
            ryn_els = row_at_max(qp_rows, "wk_y-_mm") if not qp_rows.empty else None

            def combined_case(r_elu_dir, r_els_dir):
                elu_txt = str(r_elu_dir.get("Case", "")) if r_elu_dir is not None else ""
                els_txt = str(r_els_dir.get("Case", "")) if r_els_dir is not None else ""
                if els_txt:
                    return f"ELU {elu_txt} | ELS {els_txt}"
                return elu_txt
            util_elu = safe_float(gx_elu["util_M"].max() if "util_M" in gx_elu.columns else 0.0, 0.0)
            wk_ratio = safe_float(r_els.get("ELS_wk_ratio", float("nan")), float("nan")) if r_els is not None else float("nan")
            wk_max = safe_float(r_els.get("ELS_wk_max_mm", float("nan")), float("nan")) if r_els is not None else float("nan")
            stress_enabled = "ELS_stress_check_enabled" in gx.columns and "Sim" in set(gx["ELS_stress_check_enabled"].astype(str))
            char_rows = gx[gx.get("Case_classification", "").astype(str) == "ELS-CHAR"].copy() if "Case_classification" in gx.columns else pd.DataFrame()
            qp_stress_rows = gx[gx.get("Case_classification", "").astype(str) == "ELS-QP"].copy() if "Case_classification" in gx.columns else pd.DataFrame()
            r_stress = None
            stress_state = "Não avaliado"
            if stress_enabled and char_rows.empty:
                stress_state = "Verificar"
            elif stress_enabled:
                pool = pd.concat([char_rows, qp_stress_rows], ignore_index=False) if not qp_stress_rows.empty else char_rows
                if not pool.empty:
                    rank = {"Não conforme":4,"Verificar":3,"OK*":2,"OK":1,"Informativo":0,"Não avaliado":0}
                    pool = pool.copy(); pool["__sr"] = pool.get("ELS_stress_status", pd.Series(index=pool.index,dtype=str)).astype(str).map(rank).fillna(0)
                    r_stress = pool.loc[pool["__sr"].idxmax()]
                    stress_state = str(r_stress.get("ELS_stress_status", "Não avaliado"))
            if "Status" in gx_elu.columns and "Não conforme" in set(gx_elu["Status"].astype(str)):
                status = "Não conforme"
                peak_ratio = safe_float(r_elu.get("FEM_peak_ratio", 0.0), 0.0)
                peak_governs = str(r_elu.get("FEM_peak_governing_row", "Não")) == "Sim"
                limit_reached = str(r_elu.get("Rebar_limit_reached", "Não")) == "Sim"
                if peak_governs:
                    motivo = (
                        f"ELU/flexão não satisfeito — condicionado por pico local potencial de esforços: "
                        f"utilização máxima={util_elu:.3f}; max/P95={peak_ratio:.2f}."
                    )
                    acao = (
                        "Localizar o nó/caso governante e confirmar significado físico, malha, apoio/carga concentrada ou singularidade. "
                        "O pico não foi suavizado automaticamente. Só depois decidir sobre reforço/espessura ou tratamento local do resultado."
                    )
                else:
                    motivo = f"ELU/flexão não satisfeito: utilização máxima={util_elu:.3f}."
                    acao = "Aumentar armadura, reduzir espaçamento, aumentar espessura ou rever esforços de cálculo."
                if limit_reached:
                    acao += " A armadura uniforme atingiu o limite Ø/s configurado; Ømax não foi ultrapassado."
            elif r_els is not None and (str(r_els.get("ELS_wk_status", "")) in ("Verificar", "Não conforme") or (math.isfinite(wk_ratio) and wk_ratio > 1.0)):
                status = "Não conforme"
                motivo = f"ELS/fendilhação não satisfeito em ELS-QP {r_els.get('Case','')}: wk,max={wk_max:.3f} mm; wk/wmax={wk_ratio:.3f}."
                acao = "Confirmar combinação ELS; reduzir diâmetro/espaçamento, aumentar armadura distribuída ou rever wmax."
            elif stress_state in ("Não conforme", "Verificar"):
                status = stress_state
                if r_stress is None:
                    motivo = "ELS/limitação de tensões activa, mas não foi fornecida combinação característica."
                    acao = "Indicar pelo menos uma combinação ELS característica para completar EC2 7.2."
                else:
                    motivo = str(r_stress.get("ELS_stress_note", "Limitação de tensões ELS condicionante."))
                    acao = "Rever armadura/combinações e aplicabilidade dos limites EC2 7.2; para sigma_c,QP>0,45fck considerar fluência não linear."
            elif stress_state == "OK*" or util_elu > 0.98 or (r_els is not None and math.isfinite(wk_ratio) and wk_ratio >= 0.90):
                status = "OK*"
                motivo = "ELU e ELS satisfeitos, mas com margem reduzida em pelo menos uma verificação."
                acao = "Confirmar pormenorização, eixos locais, combinações e margens antes de adoptar a solução final."
            else:
                status = "OK"
                motivo = "ELU/flexão satisfeito; ELS/fendilhação satisfeito ou não activado."
                acao = "Validar pormenorização final, punçoamento/corte local e coerência do modelo."
            sing_rows = g_all[g_all.get("Singular_node_confirmed", "Não").astype(str) == "Sim"].copy() if "Singular_node_confirmed" in g_all.columns else pd.DataFrame()
            singular_nodes = sorted({str(x) for x in sing_rows.get("Node", pd.Series(dtype=object)).dropna().astype(str)}) if not sing_rows.empty else []
            local_peak_util = safe_float(sing_rows.get("Local_peak_util_raw", pd.Series([0.0])).max(), 0.0) if not sing_rows.empty else 0.0
            if singular_nodes:
                singular_txt = ", ".join(singular_nodes)
                motivo += f" | Pico(s) singular(es) confirmado(s) excluído(s) do envelope distribuído: nó(s) {singular_txt}."
                acao += " Verificação/pormenorização local obrigatória; a exclusão manual não equivale a conformidade."
            auto_rows = g_all[g_all.get("Auto_peak_local_node", "Não").astype(str) == "Sim"].copy() if "Auto_peak_local_node" in g_all.columns else pd.DataFrame()
            auto_nodes = sorted({str(x) for x in auto_rows.get("Node", pd.Series(dtype=object)).dropna().astype(str)}) if not auto_rows.empty else []
            auto_peak_util = safe_float(auto_rows.get("util_M", pd.Series([0.0])).max(), 0.0) if not auto_rows.empty else 0.0
            auto_policy = str(auto_rows.get("Distributed_peak_policy", pd.Series([""])).iloc[0]) if not auto_rows.empty else ""
            if auto_nodes:
                motivo += (f" | {len(auto_nodes)} nó(s) de concentração local separados automaticamente do envelope distribuído "
                           f"({auto_policy}); utilização RAW máxima={auto_peak_util:.3f}.")
                acao += " Verificar/pormenorizar localmente os nós separados; os esforços RAW permanecem integralmente auditáveis."
            r_defl = row_at_max(gx, "UGZ_down_mm") if "UGZ_down_mm" in gx.columns else r_elu
            rows.append({
                "Panel": panel,
                "Status": status,
                "Motivo_estado": motivo,
                "Acção_recomendada": acao,
                "util_max": util_elu,
                "governing_case": r_elu.get("Case", ""),
                "governing_node": r_elu.get("Node", ""),
                "caso_governante_ELU": r_elu.get("Case", ""),
                "node_governante_ELU": r_elu.get("Node", ""),
                "util_ELU_max": util_elu,
                "caso_governante_ELS_wk": r_els.get("Case", "") if r_els is not None else "",
                "node_governante_ELS_wk": r_els.get("Node", "") if r_els is not None else "",
                "wk_max_mm": wk_max,
                "wk_wmax_ratio": wk_ratio,
                "estado_ELS_tensoes": stress_state,
                "caso_governante_ELS_tensoes": r_stress.get("Case", "") if r_stress is not None else "",
                "node_governante_ELS_tensoes": r_stress.get("Node", "") if r_stress is not None else "",
                "sigma_s_ELS_max_MPa": safe_float(r_stress.get("ELS_sigma_s_max_MPa", float("nan")), float("nan")) if r_stress is not None else float("nan"),
                "sigma_c_ELS_max_MPa": safe_float(r_stress.get("ELS_sigma_c_max_MPa", float("nan")), float("nan")) if r_stress is not None else float("nan"),
                "UGZ_down_max_mm": gx["UGZ_down_mm"].max() if "UGZ_down_mm" in gx.columns else 0.0,
                "util_flecha_max": gx["util_deflection"].max() if "util_deflection" in gx.columns else 0.0,
                "flecha_case": r_defl.get("Case", ""),
                "X+_adopted": rxp.get("X+_rebar", ""),
                "X-_adopted": rxn.get("X-_rebar", ""),
                "Y+_adopted": ryp.get("Y+_rebar", ""),
                "Y-_adopted": ryn.get("Y-_rebar", ""),
                "X+_case": combined_case(rxp_elu, rxp_els),
                "X-_case": combined_case(rxn_elu, rxn_els),
                "Y+_case": combined_case(ryp_elu, ryp_els),
                "Y-_case": combined_case(ryn_elu, ryn_els),
                "X+_case_ELU": rxp_elu.get("Case", ""),
                "X+_node_ELU": rxp_elu.get("Node", ""),
                "X-_case_ELU": rxn_elu.get("Case", ""),
                "X-_node_ELU": rxn_elu.get("Node", ""),
                "Y+_case_ELU": ryp_elu.get("Case", ""),
                "Y+_node_ELU": ryp_elu.get("Node", ""),
                "Y-_case_ELU": ryn_elu.get("Case", ""),
                "Y-_node_ELU": ryn_elu.get("Node", ""),
                "X+_case_ELS": rxp_els.get("Case", "") if rxp_els is not None else "",
                "X+_node_ELS": rxp_els.get("Node", "") if rxp_els is not None else "",
                "X-_case_ELS": rxn_els.get("Case", "") if rxn_els is not None else "",
                "X-_node_ELS": rxn_els.get("Node", "") if rxn_els is not None else "",
                "Y+_case_ELS": ryp_els.get("Case", "") if ryp_els is not None else "",
                "Y+_node_ELS": ryp_els.get("Node", "") if ryp_els is not None else "",
                "Y-_case_ELS": ryn_els.get("Case", "") if ryn_els is not None else "",
                "Y-_node_ELS": ryn_els.get("Node", "") if ryn_els is not None else "",
                "Pico_FEM_governante": str(r_elu.get("FEM_peak_governing_row", "Não")),
                "Pico_FEM_ratio": safe_float(r_elu.get("FEM_peak_ratio", 0.0), 0.0),
                "Limite_armadura_atingido": str(r_elu.get("Rebar_limit_reached", "Não")),
                "Nota_limite_armadura": str(r_elu.get("Rebar_limit_note", "")),
                "Nós_singulares_confirmados": ", ".join(singular_nodes),
                "Util_local_singular_max": local_peak_util,
                "Nós_pico_local_automático": ", ".join(auto_nodes),
                "N_pico_local_automático": len(auto_nodes),
                "Util_RAW_pico_local_automático": auto_peak_util,
                "Estado_local": "Verificar localmente" if (singular_nodes or auto_nodes) else "Não aplicável",
                "N_nós_locais": len(set(singular_nodes) | set(auto_nodes)),
                "Util_local_RAW_max": max(local_peak_util, auto_peak_util),
                "Política_envelope_distribuído": auto_policy,
                "Punçoamento": "Verificar separadamente",
            })
        return pd.DataFrame(rows).sort_values(["Status", "util_max"], ascending=[False, False]).reset_index(drop=True)

    def build_rebar_zones(self, governing: pd.DataFrame) -> pd.DataFrame:
        if governing is None or governing.empty:
            return pd.DataFrame()
        keys = ["X+_adopted", "X-_adopted", "Y+_adopted", "Y-_adopted", "Punçoamento"]
        rows = []
        for i, (key_vals, grp) in enumerate(governing.groupby(keys, dropna=False), start=1):
            panels = [str(p) for p in grp["Panel"].tolist()]
            worst_util = grp["util_max"].max() if "util_max" in grp.columns else 0.0
            status_values = set(str(x) for x in grp.get("Status", pd.Series(dtype=str)).dropna())
            if "Não conforme" in status_values:
                status = "Não conforme"
            elif "Verificar" in status_values:
                status = "Verificar"
            elif "OK*" in status_values:
                status = "OK*"
            else:
                status = "OK"
            rows.append({
                "Zona": f"Z{i}",
                "Painéis": ", ".join(panels),
                "n_paineis": len(panels),
                "Status": status,
                "util_max": worst_util,
                "X+": key_vals[0],
                "X-": key_vals[1],
                "Y+": key_vals[2],
                "Y-": key_vals[3],
                "Punçoamento": key_vals[4],
                "Nota": "Agrupamento por solução adoptada; validar continuidade e compatibilização com desenho de armaduras."
            })
        return pd.DataFrame(rows).sort_values(["Status", "Zona"], ascending=[False, True]).reset_index(drop=True)

    def build_rebar_optimization(self, results: pd.DataFrame) -> pd.DataFrame:
        if results is None or results.empty:
            return pd.DataFrame()
        results = self._derived_table_source(results)
        cols = [
            "Panel", "Node", "Case", "Status", "Optimization_mode", "Optimization_iterations",
            "X+_minimum_valid", "X+_base", "X+_additional", "X+_rebar", "Asx+_req_mm2_m", "Asx+_base_mm2_m", "Asx+_add_mm2_m", "Asx+_prov_mm2_m", "X+_As_ref_base_ratio", "X+_constructability", "X+_optimization",
            "X-_minimum_valid", "X-_base", "X-_additional", "X-_rebar", "Asx-_req_mm2_m", "Asx-_base_mm2_m", "Asx-_add_mm2_m", "Asx-_prov_mm2_m", "X-_As_ref_base_ratio", "X-_constructability", "X-_optimization",
            "Y+_minimum_valid", "Y+_base", "Y+_additional", "Y+_rebar", "Asy+_req_mm2_m", "Asy+_base_mm2_m", "Asy+_add_mm2_m", "Asy+_prov_mm2_m", "Y+_As_ref_base_ratio", "Y+_constructability", "Y+_optimization",
            "Y-_minimum_valid", "Y-_base", "Y-_additional", "Y-_rebar", "Asy-_req_mm2_m", "Asy-_base_mm2_m", "Asy-_add_mm2_m", "Asy-_prov_mm2_m", "Y-_As_ref_base_ratio", "Y-_constructability", "Y-_optimization",
            "Constructability_status", "Constructability_note",
            "X+_harmonization_suggestion", "X-_harmonization_suggestion", "Y+_harmonization_suggestion", "Y-_harmonization_suggestion",
            "Cross_panel_harmonization_note",
            "util_M", "util_Qx", "util_Qy", "util_max", "Verification_reason", "Recommended_action"
        ]
        out = results[[c for c in cols if c in results.columns]].copy()
        if "util_max" in out.columns:
            out = out.sort_values(["Status", "util_max"], ascending=[False, False])
        return out.reset_index(drop=True)

    def build_normative_notes(self, designer: SlabDesigner) -> pd.DataFrame:
        as_main_min, as_secondary_min, as_max = designer.min_slab_reinf_limits()
        sx_main = designer.max_spacing_for_direction(True)
        sx_sec = designer.max_spacing_for_direction(False)
        notes = [
            ("Âmbito", "Lajes maciças modeladas como placas", "O cálculo usa momentos equivalentes MXX+/MXX-/MYY+/MYY- quando disponíveis; em alternativa, calcula Wood & Armer a partir de MXX/MYY/MXY. QXX/QYY e UGZ são apenas informativos."),
            ("Flexão", designer.wood_armer_method, "MXY é tratado pelo método seleccionado. Convenção: a convenção de sinais RAW é explicitamente configurada; momentos equivalentes usam + = superior e - = inferior."),
            ("Eixos locais", "Y principal" if designer.local_y_is_vertical else "X principal", "A direcção principal é usada para escolher o espaçamento máximo. Confirmar eixos locais e normal dos painéis antes de adoptar as armaduras."),
            ("Troca X/Y", "Activada" if designer.swap_local_axes else "Desactivada", "Quando activada, MXX/MYY, QXX/QYY e NXX/NYY são trocados antes do cálculo."),
            ("Coeficientes de materiais", f"γc={designer.gamma_c:.2f}; γs={designer.gamma_s:.2f}; αcc={designer.alpha_cc:.2f}", f"EC2 3.1.6: fcd=αcc·fck/γc; fyd=fyk/γs. Valores efectivamente usados: fcd={designer.cp['fcd']:.2f} MPa; fyd={designer.fyd:.2f} MPa."),
            ("Agregado", f"dg={designer.aggregate_mm:.0f} mm", "A dimensão máxima do agregado entra na verificação construtiva da distância livre entre varões: max(Ø; dg+5; 20 mm)."),
            ("Coeficientes ELS 7.2", f"k1/k2/k3={designer.stress_k1:.2f}/{designer.stress_k2:.2f}/{designer.stress_k3:.2f}", f"Limites calculados: σc,char={designer.stress_limits['sigma_c_char_lim_MPa']:.1f} MPa; σc,QP={designer.stress_limits['sigma_c_qp_linear_creep_lim_MPa']:.1f} MPa; σs,char={designer.stress_limits['sigma_s_char_lim_MPa']:.1f} MPa."),
            ("As,min flexão", f"As,min = {as_main_min:.1f} mm²/m/face", "Aplicado o mínimo de flexão por faixa de 1 m, compatível com EC2 9.3.1.1."),
            ("As,sec,min", f"As,sec,min = {as_secondary_min:.1f} mm²/m/face", "Valor informativo correspondente a 20% da armadura principal mínima; no cálculo por placa aplica-se As,min de flexão em X e Y."),
            ("As,max", f"As,max = {as_max:.1f} mm²/m", "Limite construtivo/preliminar adoptado de 0,04 Ac por metro e por direcção."),
            ("Espaçamento principal", f"smax = {sx_main:.0f} mm", "Adoptado min(3h; 400 mm), eventualmente limitado a 250 mm se a opção estiver activa."),
            ("Espaçamento secundário", f"smax = {sx_sec:.0f} mm", "Adoptado min(3,5h; 450 mm), eventualmente limitado a 250 mm se a opção estiver activa."),
            ("Distância livre", "Verificada na escolha automática", "A solução automática rejeita combinações em que a distância livre seja inferior a max(Ø; dg+5; 20 mm)."),
            ("QXX/QYY", "Informativo", "Os esforços transversos são reportados, mas não são usados no dimensionamento automático desta versão."),
            ("Fendilhação", f"wmax = {designer.wmax_mm:.2f} mm", f"Com wk seleccionado: cálculo directo EC2 7.3.4 para o envelope das combinações ELS-QP ({format_case_ids(designer.qp_case_ids) or 'não indicadas'}). A secção permanece não fendilhada quando M<=Mcr; caso contrário usa-se a secção fendilhada e Ac,eff explícita."),
            ("Limitação de tensões ELS", "Activa" if designer.stress_check_enabled else "Desactivada", f"EC2 7.2: ELS característica verifica sigma_s<=0,8fyk e reporta sigma_c<=0,6fck; ELS-QP verifica sigma_c<=0,45fck para a hipótese de fluência linear. Limites recomendados; confirmar Anexo Nacional e aplicabilidade à classe de exposição."),
            ("Armadura mínima por fendilhação", f"As,min,crack = {designer.crack_min_as_per_face():.1f} mm²/m/face", "EC2 7.3.2: kc=0,40 em flexão; Act=b*h/2; k interpolado entre h=300 e 800 mm."),
            ("Unidades", f"M: {designer.moment_unit}; Q: {designer.shear_unit}; UGZ: {designer.deflection_unit}", "Os valores são convertidos internamente para kNm/m, kN/m e mm. Confirmar sempre as unidades da tabela de origem antes de adoptar os resultados."),
            ("UGZ", "Informativo", "UGZ negativo é considerado deslocamento para baixo. O valor é importado do modelo FEM e não constitui verificação automática de flecha pelo EC2."),
            ("Dimensionamento de armaduras", "Automático por envelope ELU/ELS", "A solução resistente é sempre dimensionada automaticamente."),
            ("Harmonização/optimização", designer.rebar_strategy if designer.optimize_rebar else "Desactivada — solução directa", f"Base principal Ø{designer.base_vertical_phi:.0f}//{designer.base_vertical_spacing:.0f}; base secundária Ø{designer.base_horizontal_phi:.0f}//{designer.base_horizontal_spacing:.0f}. Em Base + reforço, a base é preservada e admite-se uma única família adicional com a mesma modulação; As,ref pode ser superior a As,base se a solução continuar geométrica e estruturalmente válida."),
            ("Profundidade útil", "Ordem física X/Y + centróide real", "d resulta do recobrimento, da ordem exterior/interior configurada para X/Y e do centróide ponderado das famílias efectivamente adoptadas."),
            ("Solução de armadura", "Única por painel/face/direcção", "A solução é seleccionada pelos envelopes ELU, ELS-QP/fendilhação e ELS característica/tensão do aço quando activos, e depois reavaliada em todas as linhas do painel."),
            ("Domínio ELU", "Compatibilidade de extensões", "MRd é calculado por equilíbrio C=T com sigma_s=min(fyd; Es·eps_s). O ponto de cedência do aço permanece auditável como indicador de ductilidade, mas a ausência de cedência não é tratada como falha automática da secção."),
            ("Auditoria fail-safe", "Activa após o cálculo", "Antes do resultado final, são verificadas invariantes internas e o MRd é recalculado por uma rotina independente: nenhum estado OK pode coexistir com MEd/MRd>1, wk/wmax>1, domínio ELU inválido, tensão ELS condicionante, As>As,max ou diâmetros fora do intervalo configurado."),
            ("Classificação de casos", f"ELU: {format_case_ids(designer.uls_case_ids) or 'não indicado'}; ELS-CHAR: {format_case_ids(designer.characteristic_case_ids) or '—'}; ELS-FREQ: {format_case_ids(designer.frequent_case_ids) or '—'}; ELS-QP: {format_case_ids(designer.qp_case_ids) or '—'}", "Cada combinação pertence a uma única classe. ELU governa resistência; ELS-QP governa wk nesta versão; ELS característica governa a limitação de tensões EC2 7.2 quando activa; ELS frequente fica disponível para rastreabilidade."),
            ("Picos FEM", f"{designer.distributed_peak_policy}; detector max/P95 > {designer.peak_ratio_threshold:.2f}", "No modo P99 nodal + RAW local, concentrações muito localizadas são separadas apenas do envelope de armadura distribuída; os valores RAW permanecem integralmente registados e obrigam a verificação local. O modo RAW integral mantém todos os máximos no envelope."),
            ("Geometria opcional", "Diagnóstico + dimensionamento local opcional", "As tabelas geométricas classificam o contexto dos picos. Se o modo local estiver activo, o programa separa armadura distribuída e local, mantendo sempre os esforços FEM brutos e o estado RAW auditáveis; a zona automática requer confirmação do engenheiro."),
            ("Limitações", "Sem punçoamento, corte unidireccional e flechas por cálculo directo", "Para lajes fungiformes, zonas de pilares, paredes de apoio, aberturas ou cargas concentradas, fazer verificação específica de punçoamento/corte e pormenorização local."),
        ]
        return pd.DataFrame(notes, columns=["Tema", "Critério adoptado", "Nota"])

    def run_core_self_test(self):
        try:
            report = run_core_regression_tests()
            messagebox.showinfo("Autoteste SlabsEC2", report)
            self.status_var.set("Autoteste do núcleo concluído sem falhas.")
        except Exception as exc:
            messagebox.showerror("Autoteste SlabsEC2", f"Falha no autoteste:\n{exc}")
            self.status_var.set("Autoteste do núcleo com falha.")

    def run_engineering_validation(self):
        try:
            report = run_engineering_validation_suite()
            messagebox.showinfo("Validação técnica SlabsEC2", report)
            self.status_var.set("Validação técnica do núcleo concluída sem falhas.")
        except Exception as exc:
            messagebox.showerror("Validação técnica SlabsEC2", f"Falha na validação técnica:\n{exc}")
            self.status_var.set("Validação técnica do núcleo com falha.")

    def run_manual_reference_validation_ui(self):
        try:
            report = run_manual_reference_validation()
            messagebox.showinfo("Validação independente SlabsEC2", report)
            self.status_var.set("Validação independente concluída sem desvios fora da tolerância.")
        except Exception as exc:
            messagebox.showerror("Validação independente SlabsEC2", f"Falha na validação independente:\n{exc}")
            self.status_var.set("Validação independente com falha.")

    def run_design(self):
        err = self.validate_inputs()
        if err:
            messagebox.showwarning("Aviso", err)
            return
        # As classes de combinação são sempre definidas explicitamente pelo utilizador.
        designer = SlabDesigner(
            thickness_mm=safe_float(self.var_thickness.get(), 200.0),
            cover_mm=safe_float(self.var_cover.get(), 35.0),
            concrete_class=self.var_concrete.get(),
            fyk=safe_float(self.var_steel.get(), 500.0),
            gamma_c=safe_float(self.var_gamma_c.get(), 1.50),
            gamma_s=safe_float(self.var_gamma_s.get(), 1.15),
            alpha_cc=safe_float(self.var_alpha_cc.get(), 1.00),
            aggregate_mm=safe_float(self.var_aggregate_mm.get(), 20.0),
            stress_k1=safe_float(self.var_stress_k1.get(), 0.60),
            stress_k2=safe_float(self.var_stress_k2.get(), 0.45),
            stress_k3=safe_float(self.var_stress_k3.get(), 0.80),
            local_y_is_vertical=self.var_y_vertical.get(),
            crack_spacing_limit_mm=250.0 if self.var_crack_spacing.get() else None,
            wood_armer_method=self.var_wa_method.get(),
            swap_local_axes=self.var_swap_axes.get(),
            crack_check_enabled=True,
            wk_check_enabled=self.var_crack_check.get(),
            stress_check_enabled=self.var_stress_check.get(),
            qp_cases=self.var_els_qp_cases.get(),
            frequent_cases=self.var_els_freq_cases.get(),
            characteristic_cases=self.var_els_char_cases.get(),
            moment_unit=self.var_moment_unit.get(),
            shear_unit=self.var_shear_unit.get(),
            membrane_unit=self.var_membrane_unit.get(),
            combo_type=self.var_combo_type.get(),
            wmax_mm=safe_float(self.var_wmax.get(), 0.30),
            phi_min_mm=safe_float(self.var_phi_min.get(), 10.0),
            phi_max_mm=safe_float(self.var_phi_max.get(), 32.0),
            optimize_rebar=self.var_optimize_rebar.get(),
            rebar_strategy=self.var_rebar_strategy.get(),
            base_vertical_phi=safe_float(self.var_base_v_phi.get(), 12.0),
            base_vertical_spacing=safe_float(self.var_base_v_spacing.get(), 200.0),
            base_horizontal_phi=safe_float(self.var_base_h_phi.get(), 12.0),
            base_horizontal_spacing=safe_float(self.var_base_h_spacing.get(), 200.0),
            span_x_m=0.0,
            span_y_m=0.0,
            deflection_unit=self.var_deflection_unit.get(),
            deflection_limit="Informativo",
            negative_z_is_down=self.var_negative_z_down.get(),
            bottom_outer_axis=self.var_bottom_outer_axis.get(),
            top_outer_axis=self.var_top_outer_axis.get(),
            positive_moment_face=self.var_positive_moment_face.get(),
            uls_cases=self.var_uls_cases.get(),
            peak_ratio_threshold=safe_float(self.var_peak_ratio_threshold.get(), 1.50),
            singular_nodes=self.var_singular_nodes.get(),
            distributed_peak_policy=self.var_distributed_peak_policy.get(),
        )
        if designer.wk_check_enabled and not designer.qp_case_ids:
            messagebox.showwarning("Aviso", "Foi seleccionada a verificação wk, mas não foram indicadas combinações ELS quase-permanentes.")
            return
        # Hardening: o dimensionamento e a reavaliação final usam sempre todas as linhas.
        # A opção de redução fica reservada à leitura/visualização, nunca à verificação final.
        df_in = self.df_clean
        try:
            self.progress_var.set(0.0)
            self.status_var.set("A calcular...")
            self.update_idletasks()
            total = max(len(df_in), 1)
            perf_note = " — modo grandes tabelas activo" if total >= LARGE_DATASET_THRESHOLD else ""
            self.status_var.set(f"A calcular e harmonizar soluções por painel... {total} linhas{perf_note}")
            self.update_idletasks()
            self._last_designer = designer
            self.df_results = self.apply_professional_messages(designer.design_dataframe(df_in))
            self.progress_var.set(100.0)
            self.status_var.set("A preparar resumos...")
            self.update_idletasks()
            self.df_summary = self.build_panel_summary(self.df_results)
            self.df_governing = self.build_governing_design(self.df_results)
            self.df_traceability = build_governing_traceability(self.df_results)
            if self.df_geometry_nodes is not None and not self.df_geometry_nodes.empty:
                self.df_zones = build_spatial_rebar_zones(self.df_results, self.df_geometry_nodes, designer)
                if self.df_zones is None or self.df_zones.empty:
                    self.df_zones = self.build_rebar_zones(self.df_governing)
            else:
                self.df_zones = self.build_rebar_zones(self.df_governing)
            self.df_optimization = self.build_rebar_optimization(self.df_results)
            self.df_unit_check = self.build_unit_check(df_in, designer)
            self.df_data_validation = self.build_data_validation(df_in, designer)
            self.df_diagnostic = self.build_diagnostic(self.df_results, self.df_data_validation)
            self.df_peaks = build_peak_assessment(self.df_results, ratio_threshold=designer.peak_ratio_threshold)
            self.df_peaks = enrich_peak_assessment_spatial(self.df_results, self.df_peaks, self.df_geometry_nodes)
            self.df_peaks = enrich_peak_assessment_with_geometry(
                self.df_peaks, self.df_geometry_nodes, self.df_geometry_members, self.df_geometry_walls, self.df_geometry_openings
            )
            self.df_summary = merge_geometry_peak_context_into_summary(self.df_summary, self.df_peaks)
            geo_diag = build_geometry_peak_diagnostic(self.df_peaks)
            if geo_diag is not None and not geo_diag.empty:
                self.df_diagnostic = pd.concat([self.df_diagnostic, geo_diag], ignore_index=True)
            self.df_local_design = pd.DataFrame()
            if self.var_geometry_local_design.get():
                factor = max(1.0, safe_float(self.var_local_zone_factor.get(), 2.5))
                self.df_local_design = build_geometry_local_design(
                    self.df_results, self.df_peaks, self.df_geometry_nodes, self.df_geometry_members,
                    self.df_geometry_walls, self.df_geometry_openings, designer,
                    enabled=True, zone_factor=factor,
                )
                if self.df_local_design is not None and not self.df_local_design.empty:
                    self.df_summary = merge_local_design_into_summary(self.df_summary, self.df_local_design)
                    ldiag = build_local_design_diagnostic(self.df_local_design)
                    if ldiag is not None and not ldiag.empty:
                        self.df_diagnostic = pd.concat([self.df_diagnostic, ldiag], ignore_index=True)
            self.df_sketches = self.build_rebar_sketches(self.df_zones)
            self.df_detailed = self.build_detailed_check(self.df_results)
            self.df_notes = self.build_normative_notes(designer)
            self.show_df(self.tree_results, self.df_results)
            self.set_summary_filter(self.summary_filter.get())
            self.show_df(self.tree_governing, self.df_governing)
            self.show_df(self.tree_zones, self.df_zones)
            if hasattr(self, "tree_traceability"):
                self.show_df(self.tree_traceability, self.df_traceability)
            self.show_df(self.tree_optimization, self.df_optimization)
            self.show_df(self.tree_diagnostic, self.df_diagnostic)
            self.show_df(self.tree_peaks, self.df_peaks)
            if hasattr(self, "tree_local_design"):
                self.show_df(self.tree_local_design, self.df_local_design)
            self.show_df(self.tree_validation, self.df_data_validation)
            self.show_df(self.tree_sketches, self.df_sketches)
            self.show_df(self.tree_unit, self.df_unit_check)
            self.show_df(self.tree_detailed, self.df_detailed)
            self.show_df(self.tree_notes, self.df_notes)
            self.update_dashboard()
            qp_msg = ""
            if designer.wk_check_enabled:
                n_qp = int((self.df_results.get("is_QP_crack_case", pd.Series(dtype=str)) == "Sim").sum())
                n_qp_cases = int(self.df_results.loc[self.df_results.get("is_QP_crack_case", pd.Series(index=self.df_results.index, dtype=str)) == "Sim", "Case"].astype(str).nunique()) if "Case" in self.df_results.columns else 0
                qp_msg = f"; wk ELS-QP: {n_qp} linhas / {n_qp_cases} casos"
                if n_qp == 0:
                    messagebox.showwarning("Aviso", f"Não foram encontradas linhas para as combinações ELS quase-permanentes indicadas: {format_case_ids(designer.qp_case_ids)}")
            self.progress_var.set(100.0)
            local_msg = ""
            if self.var_geometry_local_design.get():
                nloc = int((self.df_local_design.get("Aplicado", pd.Series(dtype=str)).astype(str) == "Sim").sum()) if self.df_local_design is not None and not self.df_local_design.empty else 0
                local_msg = f"; zonas locais geométricas: {nloc}"
            self.status_var.set(f"Cálculo concluído: {len(self.df_results)} linhas analisadas; {len(self.df_summary)} painéis resumidos{qp_msg}{local_msg}.")
        except Exception as e:
            self.progress_var.set(0.0)
            messagebox.showerror("Erro", str(e))
            self.status_var.set("Falha no cálculo.")
