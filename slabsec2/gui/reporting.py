# -*- coding: utf-8 -*-
import math
from datetime import datetime
import pandas as pd
from tkinter import filedialog, messagebox

from ..version import APP_NAME, APP_VERSION, APP_AUTHOR, APP_SUBJECT, APP_KEYWORDS, APP_CATEGORY, APP_XLSX_DESCRIPTION, GITHUB_URL, LARGE_DATASET_THRESHOLD, LARGE_DERIVED_MAX_ROWS

XLSX_DATA_ROWS_PER_SHEET = 1_048_575  # o cabeçalho ocupa a primeira linha

class ReportExportMixin:
    def export_excel(self):
        if self.df_results is None or self.df_results.empty:
            messagebox.showwarning("Aviso", "Não há resultados para exportar.")
            return
        path = filedialog.asksaveasfilename(
            title="Exportar resultados",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not path:
            return

        # Garante extensão correcta. Evita ficheiros com extensão inválida,
        # por exemplo .xls ou nomes sem extensão que depois o Excel recusa abrir.
        import os
        root, ext = os.path.splitext(path)
        if ext.lower() != ".xlsx":
            path = root + ".xlsx" if ext else path + ".xlsx"

        # Grandes tabelas: workbook compacto e escrita em streaming. O cálculo não é reduzido;
        # evita-se apenas duplicar 300k+ linhas em várias folhas temáticas e em Full Results.
        if len(self.df_results) >= LARGE_DATASET_THRESHOLD:
            return self._export_excel_large(path)

        def safe_sheet_name(name: str) -> str:
            bad = r'[]:*?/\\'
            out = "".join("_" if ch in bad else ch for ch in str(name))[:31]
            return out or "Sheet"

        def has_df(df):
            return df is not None and isinstance(df, pd.DataFrame) and not df.empty

        def pick_cols(df, cols):
            if not has_df(df):
                return pd.DataFrame()
            present = [c for c in cols if c in df.columns]
            if not present:
                return pd.DataFrame()
            return df[present].copy()

        try:
            self.progress_var.set(0.0)
            self.status_var.set("A preparar exportação Excel...")
            self.update_idletasks()

            # ---- folhas estruturadas, menos densas ----
            export_dt = datetime.now()
            metadata = pd.DataFrame([
                ["Programa", APP_NAME],
                ["Versão", APP_VERSION],
                ["Repositório", GITHUB_URL],
                ["Data de exportação", export_dt.strftime("%Y-%m-%d %H:%M")],
                ["Tipo de ficheiro", "Resultados de cálculo"],
                ["Norma de referência", "Eurocódigo 2 / NP EN 1992-1-1"],
                ["Âmbito", "Lajes modeladas como painéis/placas, com esforços por metro"],
                ["Limitações", "Não inclui punçoamento, corte unidireccional, flechas por cálculo directo ou vibração; o dimensionamento local geométrico é opcional e requer validação do engenheiro"],
                ["Unidades internas", "Momentos em kNm/m; QXX/QYY em kN/m apenas informativos; UGZ em mm apenas informativo"],
                ["Descrição", APP_XLSX_DESCRIPTION],
            ], columns=["Campo", "Valor"])

            input_params = pd.DataFrame([
                ["Espessura [mm]", self.var_thickness.get()],
                ["Recobrimento [mm]", self.var_cover.get()],
                ["Profundidade útil", "Ordem física X/Y configurada — centróide real da armadura"],
                ["Betão", self.var_concrete.get()],
                ["Aço fyk [MPa]", self.var_steel.get()],
                ["γc", self.var_gamma_c.get()],
                ["γs", self.var_gamma_s.get()],
                ["αcc", self.var_alpha_cc.get()],
                ["Agregado dg [mm]", self.var_aggregate_mm.get()],
                ["ELS k1 / k2 / k3", f"{self.var_stress_k1.get()} / {self.var_stress_k2.get()} / {self.var_stress_k3.get()}"],
                ["Direcção local Y = direcção principal", "Sim" if self.var_y_vertical.get() else "Não"],
                ["Trocar eixos X ↔ Y", "Sim" if self.var_swap_axes.get() else "Não"],
                ["Método MXY", self.var_wa_method.get()],
                ["Verificar wk", "Sim" if self.var_crack_check.get() else "Não"],
                ["Verificar tensões ELS", "Sim" if self.var_stress_check.get() else "Não"],
                ["Combinações ELU", self.var_uls_cases.get()],
                ["ELS característica", self.var_els_char_cases.get()],
                ["ELS frequente", self.var_els_freq_cases.get()],
                ["ELS quase-permanente", self.var_els_qp_cases.get()],
                ["wmax [mm]", self.var_wmax.get()],
                ["Unidade dos momentos", self.var_moment_unit.get()],
                ["Unidade QXX/QYY", self.var_shear_unit.get()],
                ["Unidade NXX/NYY/NXY", self.var_membrane_unit.get()],
                ["Malha exterior superior", self.var_top_outer_axis.get()],
                ["Malha exterior inferior", self.var_bottom_outer_axis.get()],
                ["RAW: M>0 tracciona face", self.var_positive_moment_face.get()],
                ["Unidade UGZ", self.var_deflection_unit.get()],
                ["UGZ negativo = para baixo", "Sim" if self.var_negative_z_down.get() else "Não"],
                ["Ø min / Ø max [mm]", f"{self.var_phi_min.get()} / {self.var_phi_max.get()}"],
                ["Harmonizar/optimizar solução", "Sim" if self.var_optimize_rebar.get() else "Não"],
                ["Estratégia de harmonização", self.var_rebar_strategy.get() if self.var_optimize_rebar.get() else "Desactivada"],
                ["Base direcção principal", f"Ø{self.var_base_v_phi.get()}//{self.var_base_v_spacing.get()}"],
                ["Base direcção secundária", f"Ø{self.var_base_h_phi.get()}//{self.var_base_h_spacing.get()}"],
                ["Limiar de pico max/P95", self.var_peak_ratio_threshold.get()],
                ["Nós singulares confirmados", self.var_singular_nodes.get() or "nenhum"],
                ["Geometria opcional — nós", len(getattr(self, "df_geometry_nodes", pd.DataFrame()))],
                ["Geometria opcional — vigas/pilares", len(getattr(self, "df_geometry_members", pd.DataFrame()))],
                ["Geometria opcional — paredes", len(getattr(self, "df_geometry_walls", pd.DataFrame()))],
                ["Geometria opcional — aberturas/negativos", len(getattr(self, "df_geometry_openings", pd.DataFrame()))],
                ["Dimensionamento local geométrico", "Activo" if getattr(self, "var_geometry_local_design", None) is not None and self.var_geometry_local_design.get() else "Desactivado"],
                ["Factor largura local × malha", self.var_local_zone_factor.get() if getattr(self, "var_local_zone_factor", None) is not None else "-"],
            ], columns=["Parâmetro", "Valor"] )

            readme = pd.DataFrame([
                ["SlabsEC2", "Exportação organizada de resultados de lajes de betão armado"],
                ["Formato", "Workbook .xlsx válido, com resultados separados por tema"],
                ["Linhas analisadas", len(self.df_results) if has_df(self.df_results) else 0],
                ["Painéis resumidos", len(self.df_summary) if has_df(self.df_summary) else 0],
                ["Folhas principais", "Resumo por painel, armaduras adoptadas, zonas espaciais, rastreabilidade de governantes, diagnóstico, validação, resultados por tema"],
                ["Nota", "A folha '15_Full_Results' mantém a tabela completa para auditoria; as folhas 09 a 13 separam os resultados por assunto."],
            ], columns=["Item", "Descrição"] )

            row_core = pick_cols(self.df_results, [
                "Panel", "Node", "Case", "Case_classification", "is_QP_crack_case", "ELS_wk_evaluated", "Status", "Verification_reason", "Recommended_action",
                "util_max", "util_M", "Section_domain_valid", "MRd_singly_lim_min_kNm_m", "ELS_wk_max_mm", "ELS_wk_ratio", "ELS_wk_status", "wk_max_mm",
                "ELS_stress_status", "ELS_sigma_s_max_MPa", "ELS_sigma_s_limit_MPa", "ELS_sigma_c_max_MPa", "ELS_sigma_c_char_limit_MPa", "ELS_sigma_c_qp_linear_limit_MPa"
            ])
            row_flexure = pick_cols(self.df_results, [
                "Panel", "Node", "Case", "Moment_input_mode", "Equivalent_moment_source", "MXX_kNm_m", "MYY_kNm_m", "MXY_kNm_m", "MXY_abs_kNm_m", "MXX+_equiv_kNm_m", "MXX-_equiv_kNm_m", "MYY+_equiv_kNm_m", "MYY-_equiv_kNm_m", "WA_method", "WA_transformation_applied", "MXY_ratio",
                "WA_X+_direct_kNm_m", "WA_X+_MXY_add_kNm_m", "WA_X-_direct_kNm_m", "WA_X-_MXY_add_kNm_m",
                "WA_Y+_direct_kNm_m", "WA_Y+_MXY_add_kNm_m", "WA_Y-_direct_kNm_m", "WA_Y-_MXY_add_kNm_m",
                "Mx+_WA", "Mx-_WA", "My+_WA", "My-_WA",
                "Asx+_req_mm2_m", "Asx-_req_mm2_m", "Asy+_req_mm2_m", "Asy-_req_mm2_m",
                "MRd_x+_kNm_m", "MRd_x-_kNm_m", "MRd_y+_kNm_m", "MRd_y-_kNm_m", "Section_domain_valid", "MRd_singly_lim_min_kNm_m", "xi_bal_min", "steel_yields_all_faces", "util_M"
            ])
            row_shear = pick_cols(self.df_results, [
                "Panel", "Node", "Case", "QXX_kN_m", "QYY_kN_m", "VRdc_x_kN_m", "VRdc_y_kN_m",
                "VRdmax_x_kN_m", "VRdmax_y_kN_m", "util_Qx", "util_Qy",
                "util_Qx_VRdmax", "util_Qy_VRdmax", "Transverse_links_note"
            ])
            row_cracking = pick_cols(self.df_results, [
                "Panel", "Node", "Case", "is_QP_crack_case", "ELS_wk_evaluated", "ELS_wk_status", "wmax_mm",
                "ELS_wk_max_mm", "ELS_wk_ratio", "wk_x+_mm", "wk_x-_mm", "wk_y+_mm", "wk_y-_mm", "wk_max_mm", "wk_calc_unfiltered_max_mm",
                "sigma_s_x+_MPa", "sigma_s_x-_MPa", "sigma_s_y+_MPa", "sigma_s_y-_MPa",
                "sigma_c_x+_MPa", "sigma_c_x-_MPa", "sigma_c_y+_MPa", "sigma_c_y-_MPa",
                "phi_ctrl_x+_mm", "phi_ctrl_x-_mm", "phi_ctrl_y+_mm", "phi_ctrl_y-_mm",
                "s_eff_x+_mm", "s_eff_x-_mm", "s_eff_y+_mm", "s_eff_y-_mm",
                "phi_lim_x+_EC2_mm", "phi_lim_x-_EC2_mm", "phi_lim_y+_EC2_mm", "phi_lim_y-_EC2_mm",
                "s_lim_x+_EC2_mm", "s_lim_x-_EC2_mm", "s_lim_y+_EC2_mm", "s_lim_y-_EC2_mm",
                "Crack_status_x+", "Crack_status_x-", "Crack_status_y+", "Crack_status_y-",
                "Crack_reason_x+", "Crack_reason_x-", "Crack_reason_y+", "Crack_reason_y-",
                "Crack_control_status", "Crack_control_note"
            ])
            row_service = pick_cols(self.df_results, [
                "Panel", "Node", "Case", "Case_classification", "ELS_stress_status", "ELS_stress_note",
                "ELS_sigma_s_max_MPa", "ELS_sigma_s_limit_MPa", "ELS_sigma_c_max_MPa",
                "ELS_sigma_c_char_limit_MPa", "ELS_sigma_c_qp_linear_limit_MPa",
                "sigma_s_x+_MPa", "sigma_s_x-_MPa", "sigma_s_y+_MPa", "sigma_s_y-_MPa",
                "sigma_c_x+_MPa", "sigma_c_x-_MPa", "sigma_c_y+_MPa", "sigma_c_y-_MPa"
            ])

            row_rebar = pick_cols(self.df_results, [
                "Panel", "Node", "Case",
                "X+_minimum_valid", "X-_minimum_valid", "Y+_minimum_valid", "Y-_minimum_valid",
                "X+_rebar", "X-_rebar", "Y+_rebar", "Y-_rebar",
                "X+_base", "X-_base", "Y+_base", "Y-_base",
                "X+_additional", "X-_additional", "Y+_additional", "Y-_additional",
                "Asx+_base_mm2_m", "Asx+_add_mm2_m", "Asx-_base_mm2_m", "Asx-_add_mm2_m",
                "Asy+_base_mm2_m", "Asy+_add_mm2_m", "Asy-_base_mm2_m", "Asy-_add_mm2_m",
                "Asx+_prov_mm2_m", "Asx-_prov_mm2_m", "Asy+_prov_mm2_m", "Asy-_prov_mm2_m",
                "X+_As_ref_base_ratio", "X-_As_ref_base_ratio", "Y+_As_ref_base_ratio", "Y-_As_ref_base_ratio",
                "Constructability_status", "Constructability_note",
                "X+_harmonization_suggestion", "X-_harmonization_suggestion", "Y+_harmonization_suggestion", "Y-_harmonization_suggestion",
                "Cross_panel_harmonization_note",
                "sX_max_mm", "sY_max_mm", "Optimization_mode", "Optimization_iterations"
            ])

            sheets = [
                ("00_METADATA", metadata),
                ("00_README", readme),
                ("01_Input_Data", input_params),
                ("02_Panel_Summary", self.df_summary),
                ("03_Adopted_Rebar", self.df_governing),
                ("04_Rebar_Zones", self.df_zones),
                ("04B_Traceability", getattr(self, "df_traceability", pd.DataFrame())),
                ("05_Optimization", self.df_optimization),
                ("06_Diagnostic", self.df_diagnostic),
                ("07_Data_Validation", self.df_data_validation),
                ("08_Unit_Check", self.df_unit_check),
                ("09_Row_Core", row_core),
                ("10_Row_Flexure", row_flexure),
                ("11_Row_Shear", row_shear),
                ("12_Row_Cracking", row_cracking),
                ("12B_ELS_Stress", row_service),
                ("13_Row_Rebar", row_rebar),
                ("14_Detailed_Check", self.df_detailed),
                ("15_Full_Results", self.df_results),
                ("16_Raw_Table", self.df_clean),
                ("17_EC2_Notes", self.df_notes),
                ("18_Peak_Assessment", getattr(self, "df_peaks", pd.DataFrame())),
                ("19_Geo_Nodes", getattr(self, "df_geometry_nodes", pd.DataFrame())),
                ("20_Geo_Members", getattr(self, "df_geometry_members", pd.DataFrame())),
                ("21_Geo_Walls", getattr(self, "df_geometry_walls", pd.DataFrame())),
                ("22_Geo_Openings", getattr(self, "df_geometry_openings", pd.DataFrame())),
                ("23_Local_Design", getattr(self, "df_local_design", pd.DataFrame())),
            ]

            self.progress_var.set(15.0)
            self.status_var.set("A escrever folhas Excel...")
            self.update_idletasks()

            index_rows = pd.DataFrame([
                [name, self._excel_sheet_description(name)] for name, _ in sheets
            ], columns=readme.columns)
            readme = pd.concat([readme, index_rows], ignore_index=True)
            sheets = [(name, readme if name == "00_README" else df) for name, df in sheets]

            from ..xlsx_export import write_workbook

            def progress(done, total, name):
                self.progress_var.set(15.0 + 80.0 * done / max(total, 1))
                self.status_var.set(f"A exportar Excel: {name} ({done:,}/{total:,} linhas)")
                self.update_idletasks()

            write_workbook(path, sheets, progress=progress, properties={
                "title": f"{APP_NAME} - Resultados de Cálculo",
                "subject": APP_SUBJECT, "author": "",
                "comments": APP_XLSX_DESCRIPTION, "keywords": APP_KEYWORDS,
                "category": APP_CATEGORY,
            })

            self.progress_var.set(100.0)
            self.status_var.set(f"Excel organizado exportado: {path}")
            messagebox.showinfo("Exportação concluída", f"Excel exportado com sucesso:\n{path}")

        except PermissionError:
            self.progress_var.set(0.0)
            self.status_var.set("Erro ao exportar Excel: ficheiro aberto ou sem permissão.")
            messagebox.showerror(
                "Erro",
                "Não foi possível gravar o ficheiro. Feche o Excel se o ficheiro estiver aberto e tente novamente."
            )
        except Exception as e:
            self.progress_var.set(0.0)
            self.status_var.set("Erro ao exportar Excel.")
            messagebox.showerror("Erro", str(e))

    def _export_excel_large(self, path: str):
        """Exportação XLSX de baixa memória para 100k+ linhas.

        O workbook contém todas as linhas numa tabela compacta de auditoria. Tabelas muito
        detalhadas são reduzidas aos governantes/avisos porque repetir centenas de colunas em
        várias folhas é redundante e pode consumir vários GB de RAM.
        """
        import os
        import xlsxwriter
        import numpy as np

        def has_df(df):
            return df is not None and isinstance(df, pd.DataFrame) and not df.empty

        def pick_cols(df, cols):
            if not has_df(df):
                return pd.DataFrame()
            present = [c for c in cols if c in df.columns]
            return df[present] if present else pd.DataFrame()

        export_dt = datetime.now()
        nrows = len(self.df_results)
        compact_cols = [
            "Panel", "Node", "Case", "Case_classification", "Moment_input_mode", "Equivalent_moment_source",
            "MXX_kNm_m", "MYY_kNm_m", "MXY_kNm_m",
            "MXX+_equiv_kNm_m", "MXX-_equiv_kNm_m", "MYY+_equiv_kNm_m", "MYY-_equiv_kNm_m",
            "MEd_x_sup_kNm_m", "MEd_x_inf_kNm_m", "MEd_y_sup_kNm_m", "MEd_y_inf_kNm_m",
            "Asx+_req_mm2_m", "Asx-_req_mm2_m", "Asy+_req_mm2_m", "Asy-_req_mm2_m",
            "Asx+_prov_mm2_m", "Asx-_prov_mm2_m", "Asy+_prov_mm2_m", "Asy-_prov_mm2_m",
            "X+_rebar", "X-_rebar", "Y+_rebar", "Y-_rebar",
            "d_x_sup_mm", "d_x_inf_mm", "d_y_sup_mm", "d_y_inf_mm",
            "MRd_x+_kNm_m", "MRd_x-_kNm_m", "MRd_y+_kNm_m", "MRd_y-_kNm_m",
            "util_M", "Section_domain_valid", "ELS_wk_max_mm", "ELS_wk_ratio", "ELS_wk_status",
            "ELS_sigma_s_max_MPa", "ELS_sigma_c_max_MPa", "ELS_stress_status",
            "UGZ_mm", "UGZ_down_mm", "Status", "Integrity_status",
            "FEM_peak_flag", "FEM_peak_ratio", "FEM_peak_governing_row",
            "Singular_node_confirmed", "Excluded_from_distributed_envelope", "Design_relevant",
        ]
        compact = pick_cols(self.df_results, compact_cols)
        critical = self._derived_table_source(self.df_results) if hasattr(self, "_derived_table_source") else self.df_results.head(LARGE_DERIVED_MAX_ROWS)
        detail_cols = [
            "Panel", "Node", "Case", "Case_classification", "Status", "Verification_reason", "Recommended_action",
            "MEd_x_sup_kNm_m", "MEd_x_inf_kNm_m", "MEd_y_sup_kNm_m", "MEd_y_inf_kNm_m",
            "Asx+_req_mm2_m", "Asx-_req_mm2_m", "Asy+_req_mm2_m", "Asy-_req_mm2_m",
            "X+_rebar", "X-_rebar", "Y+_rebar", "Y-_rebar",
            "MRd_x+_kNm_m", "MRd_x-_kNm_m", "MRd_y+_kNm_m", "MRd_y-_kNm_m", "util_M",
            "ELS_wk_max_mm", "ELS_wk_ratio", "ELS_wk_status", "ELS_sigma_s_max_MPa", "ELS_sigma_c_max_MPa",
            "ELS_stress_status", "Integrity_status", "FEM_peak_flag", "FEM_peak_ratio", "FEM_peak_governing_row",
        ]
        detail = pick_cols(critical, detail_cols)

        metadata = pd.DataFrame([
            ["Programa", APP_NAME], ["Versão", APP_VERSION], ["Repositório", GITHUB_URL],
            ["Data de exportação", export_dt.strftime("%Y-%m-%d %H:%M")],
            ["Modo de exportação", "Grandes tabelas — streaming/compacto"],
            ["Linhas calculadas", nrows],
            ["Norma de referência", "Eurocódigo 2 / NP EN 1992-1-1"],
            ["Nota", "Todas as linhas foram calculadas. A folha 15_Results_Compact contém a auditoria linha-a-linha; folhas detalhadas contêm governantes/avisos."],
            ["Limitações", "Punçoamento, corte unidireccional e flecha normativa fora do âmbito deste núcleo."],
        ], columns=["Campo", "Valor"])
        readme = pd.DataFrame([
            ["SlabsEC2", "Exportação optimizada para grandes tabelas FEM"],
            ["Linhas analisadas", nrows],
            ["Resultados completos", "15_Results_Compact — todas as linhas, grandezas estruturais essenciais"],
            ["Detalhe crítico", "14_Detailed_Critical — governantes, avisos e não conformidades"],
            ["Dados brutos", "Não duplicados neste workbook; usar o ficheiro de origem ou Exportar .csv quando for necessária uma tabela massiva completa."],
            ["Rigor", "A redução aplica-se apenas à apresentação/exportação; nenhum caso foi removido do cálculo."],
        ], columns=["Item", "Descrição"])
        input_params = pd.DataFrame([
            ["Espessura [mm]", self.var_thickness.get()], ["Recobrimento [mm]", self.var_cover.get()],
            ["Betão", self.var_concrete.get()], ["Aço fyk [MPa]", self.var_steel.get()],
            ["γc / γs / αcc", f"{self.var_gamma_c.get()} / {self.var_gamma_s.get()} / {self.var_alpha_cc.get()}"],
            ["Agregado dg [mm]", self.var_aggregate_mm.get()],
            ["ELS k1 / k2 / k3", f"{self.var_stress_k1.get()} / {self.var_stress_k2.get()} / {self.var_stress_k3.get()}"],
            ["Combinações ELU", self.var_uls_cases.get()], ["ELS característica", self.var_els_char_cases.get()],
            ["ELS frequente", self.var_els_freq_cases.get()], ["ELS quase-permanente", self.var_els_qp_cases.get()],
            ["wmax [mm]", self.var_wmax.get()], ["Ø min / Ø max [mm]", f"{self.var_phi_min.get()} / {self.var_phi_max.get()}"],
            ["Estratégia", self.var_rebar_strategy.get() if self.var_optimize_rebar.get() else "Solução directa"],
            ["Unidade dos momentos", self.var_moment_unit.get()], ["Unidade QXX/QYY", self.var_shear_unit.get()],
            ["Unidade NXX/NYY/NXY", self.var_membrane_unit.get()], ["RAW: M>0 tracciona face", self.var_positive_moment_face.get()],
            ["Malha exterior superior / inferior", f"{self.var_top_outer_axis.get()} / {self.var_bottom_outer_axis.get()}"],
            ["Unidade UGZ", self.var_deflection_unit.get()],
        ], columns=["Parâmetro", "Valor"])

        sheets = [
            ("00_METADATA", metadata), ("00_README", readme), ("01_Input_Data", input_params),
            ("02_Panel_Summary", self.df_summary), ("03_Adopted_Rebar", self.df_governing),
            ("04_Rebar_Zones", self.df_zones), ("05_Optimization", self.df_optimization),
            ("06_Diagnostic", self.df_diagnostic), ("07_Data_Validation", self.df_data_validation),
            ("08_Unit_Check", self.df_unit_check), ("14_Detailed_Critical", detail),
            ("17_EC2_Notes", self.df_notes), ("18_Peak_Assessment", getattr(self, "df_peaks", pd.DataFrame())),
            ("19_Geo_Nodes", getattr(self, "df_geometry_nodes", pd.DataFrame())),
            ("20_Geo_Members", getattr(self, "df_geometry_members", pd.DataFrame())),
            ("21_Geo_Walls", getattr(self, "df_geometry_walls", pd.DataFrame())),
            ("22_Geo_Openings", getattr(self, "df_geometry_openings", pd.DataFrame())),
            ("23_Local_Design", getattr(self, "df_local_design", pd.DataFrame())),
            ("15_Results_Compact", compact),
        ]
        # O modo de grandes tabelas também respeita o limite físico XLSX. Sem esta divisão,
        # um modelo com ~1,3 M linhas falharia apesar de o cálculo ter terminado correctamente.
        expanded_sheets = []
        for name, df in sheets:
            if isinstance(df, pd.DataFrame) and len(df) > XLSX_DATA_ROWS_PER_SHEET:
                for part, start in enumerate(range(0, len(df), XLSX_DATA_ROWS_PER_SHEET), start=1):
                    expanded_sheets.append((f"{name[:27]}_{part}", df.iloc[start:start + XLSX_DATA_ROWS_PER_SHEET]))
            else:
                expanded_sheets.append((name, df))
        sheets = expanded_sheets

        def cell_value(v):
            if pd.isna(v):
                return None
            if isinstance(v, (np.integer,)): return int(v)
            if isinstance(v, (np.floating,)): return float(v)
            if isinstance(v, (pd.Timestamp, datetime)): return str(v)
            return str(v) if not isinstance(v, (int, float, bool)) else v

        def write_df(workbook, name, df, sheet_no, n_sheets):
            name = str(name)[:31]
            ws = workbook.add_worksheet(name)
            header_fmt = workbook.add_format({"bold": True, "font_color": "white", "bg_color": "#1F4E78", "align": "center", "valign": "vcenter", "text_wrap": True, "border": 1})
            text_fmt = workbook.add_format({"valign": "top"})
            num_fmt = workbook.add_format({"num_format": "0.000", "valign": "top"})
            ws.freeze_panes(1, 0)
            ws.hide_gridlines(2)
            if df is None or not isinstance(df, pd.DataFrame) or df.empty:
                ws.write(0, 0, "Nota", header_fmt); ws.write(1, 0, "Sem dados disponíveis.", text_fmt); return
            cols = list(df.columns)
            for c, h in enumerate(cols):
                ws.write(0, c, str(h), header_fmt)
            # largura calculada só por cabeçalho; não varrer 300k linhas para formatação.
            for c, h in enumerate(cols):
                hl = str(h).lower()
                width = 12
                if any(k in hl for k in ["reason", "action", "nota", "motivo", "descr"]): width = 38
                elif any(k in hl for k in ["panel", "node", "case", "status"]): width = 15
                else: width = min(max(len(str(h)) + 2, 12), 20)
                ws.set_column(c, c, width)
            for rno, row in enumerate(df.itertuples(index=False, name=None), start=1):
                for c, v in enumerate(row):
                    vv = cell_value(v)
                    if vv is None: continue
                    if isinstance(vv, (int, float)) and not isinstance(vv, bool): ws.write_number(rno, c, vv, num_fmt)
                    else: ws.write(rno, c, vv, text_fmt)
                if rno % 20000 == 0:
                    self.status_var.set(f"Excel grandes tabelas: {name} — {rno:,}/{len(df):,} linhas".replace(",", " "))
                    self.progress_var.set(10.0 + 85.0 * ((sheet_no - 1) + rno/max(len(df),1)) / max(n_sheets,1))
                    self.update_idletasks()
            ws.autofilter(0, 0, len(df), max(len(cols)-1, 0))

        try:
            self.progress_var.set(5.0)
            self.status_var.set(f"A exportar {nrows:,} linhas em modo de baixa memória...".replace(",", " "))
            self.update_idletasks()
            workbook = xlsxwriter.Workbook(path, {"constant_memory": True, "strings_to_urls": False, "nan_inf_to_errors": True})
            workbook.set_properties({"title": f"{APP_NAME} - Resultados de Cálculo", "subject": APP_SUBJECT, "author": "", "comments": APP_XLSX_DESCRIPTION, "keywords": APP_KEYWORDS, "category": APP_CATEGORY})
            for i, (name, df) in enumerate(sheets, start=1):
                self.status_var.set(f"A escrever folha {i}/{len(sheets)}: {name}")
                self.update_idletasks()
                write_df(workbook, name, df, i, len(sheets))
            workbook.close()
            self.progress_var.set(100.0)
            self.status_var.set(f"Excel optimizado exportado: {path}")
            messagebox.showinfo("Exportação concluída", f"Excel exportado em modo de grandes tabelas:\n{path}")
        except PermissionError:
            self.progress_var.set(0.0); self.status_var.set("Erro ao exportar Excel: ficheiro aberto ou sem permissão.")
            messagebox.showerror("Erro", "Não foi possível gravar o ficheiro. Feche o Excel se o ficheiro estiver aberto e tente novamente.")
        except Exception as exc:
            try:
                if 'workbook' in locals(): workbook.close()
            except Exception:
                pass
            self.progress_var.set(0.0); self.status_var.set("Erro ao exportar Excel.")
            messagebox.showerror("Erro", str(exc))

    def _excel_sheet_description(self, sheet_name: str) -> str:
        descriptions = {
            "00_METADATA": "Metadados do ficheiro e identificação da exportação",
            "00_README": "Resumo da exportação e índice do workbook",
            "01_Input_Data": "Parâmetros usados no cálculo",
            "02_Panel_Summary": "Resumo governante por painel",
            "03_Adopted_Rebar": "Armadura adoptada por painel",
            "04_Rebar_Zones": "Zonamento espacial automático base + reforços quando existem coordenadas; fallback por solução quando não existem",
            "04B_Traceability": "Governantes ELU/ELS por face e direcção, ligados aos momentos raw e à transformação Wood-Armer",
            "05_Optimization": "Histórico/resultado da optimização de armaduras",
            "06_Diagnostic": "Avisos e acções recomendadas",
            "07_Data_Validation": "Validação da tabela importada",
            "08_Unit_Check": "Unidades adoptadas e factores de conversão",
            "09_Row_Core": "Resultados essenciais por linha/caso",
            "10_Row_Flexure": "Resultados de flexão e armadura requerida",
            "11_Row_Shear": "QXX/QYY importados — informação FEM; verificação de corte fora do âmbito",
            "12_Row_Cracking": "Verificação de fendilhação / wk",
            "13_Row_Rebar": "Armadura base, adicional e final por linha",
            "14_Detailed_Check": "Cálculo detalhado de linhas seleccionadas/críticas",
            "15_Full_Results": "Tabela completa de resultados para auditoria",
            "16_Raw_Table": "Tabela importada já normalizada",
            "17_EC2_Notes": "Notas normativas e limitações",
            "18_Peak_Assessment": "Diagnóstico estatístico e classificação geométrica opcional de picos locais e singularidades confirmadas",
            "23_Local_Design": "Proposta opcional de armadura distribuída + local, com envelope FEM bruto preservado",
        }
        return descriptions.get(sheet_name, "")

    def export_pdf_report(self):
        """Exporta uma memória de cálculo profissional e um PDF de auditoria associado.

        O PDF principal é deliberadamente orientado à revisão de projeto: hipóteses,
        critérios, resumo e fichas por painel. O PDF de auditoria conserva a
        rastreabilidade técnica sem transformar a memória principal num dump de dados.
        """
        if self.df_results is None or self.df_results.empty:
            messagebox.showwarning("Aviso", "Não há resultados para exportar.")
            return
        path = filedialog.asksaveasfilename(
            title="Exportar memória de cálculo PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
        )
        if not path:
            return

        import os
        try:
            from reportlab.lib import colors
            from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
            from reportlab.lib.units import mm
            from reportlab.platypus import (
                BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Table,
                TableStyle, PageBreak, KeepTogether,
            )
            from reportlab.platypus.tableofcontents import TableOfContents
        except ImportError:
            messagebox.showerror("Erro", "A biblioteca reportlab não está instalada. Instale com: pip install reportlab")
            return

        try:
            self.progress_var.set(0.0)
            self.status_var.set("A gerar memória de cálculo profissional...")
            self.update_idletasks()

            root, ext = os.path.splitext(path)
            if ext.lower() != ".pdf":
                path = root + ".pdf" if ext else path + ".pdf"
                root, _ = os.path.splitext(path)
            audit_path = root + "_AUDITORIA.pdf"
            export_dt = datetime.now()
            source_name = os.path.basename(getattr(self, "input_source_path", "") or "") or "Tabela colada / origem não identificada"

            # -----------------------------------------------------------------
            # Helpers de dados
            # -----------------------------------------------------------------
            def _has(df):
                return isinstance(df, pd.DataFrame) and not df.empty

            def _val(row, key, default="-"):
                try:
                    v = row.get(key, default)
                except Exception:
                    return default
                if pd.isna(v):
                    return default
                return v

            def _num(v, nd=3, default="-"):
                try:
                    x = float(v)
                    if not math.isfinite(x):
                        return default
                    return f"{x:.{nd}f}"
                except Exception:
                    return default

            def _text(v, default="-"):
                if v is None:
                    return default
                try:
                    if pd.isna(v):
                        return default
                except Exception:
                    pass
                s = str(v).strip()
                return s if s else default

            def _esc(s):
                return _text(s, "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            def _panel_key(v):
                s = _text(v)
                try:
                    return (0, float(s))
                except Exception:
                    return (1, s)

            def _status_rank(s):
                s = _text(s).lower()
                if "não conforme" in s or "nao conforme" in s: return 0
                if "verificar" in s: return 1
                if "ok*" in s: return 2
                if "ok" in s: return 3
                return 4

            summary = self.df_summary.copy() if _has(self.df_summary) else pd.DataFrame()
            governing = self.df_governing.copy() if _has(self.df_governing) else pd.DataFrame()
            trace = getattr(self, "df_traceability", pd.DataFrame())
            peaks = getattr(self, "df_peaks", pd.DataFrame())
            diagnostics = self.df_diagnostic.copy() if _has(self.df_diagnostic) else pd.DataFrame()

            if _has(summary) and "Panel" in summary.columns:
                summary = summary.assign(_status_rank=summary.get("Status_global", pd.Series(index=summary.index, dtype=str)).map(_status_rank))
                summary = summary.sort_values(["_status_rank", "Panel"], key=lambda s: s.map(_panel_key) if s.name == "Panel" else s).drop(columns=["_status_rank"])

            # -----------------------------------------------------------------
            # Estilos e documento com bookmarks / índice
            # -----------------------------------------------------------------
            navy = colors.HexColor("#243746")
            blue = colors.HexColor("#3D5A73")
            pale_blue = colors.HexColor("#EAF0F4")
            light = colors.HexColor("#F6F7F8")
            border = colors.HexColor("#D8DEE3")
            dark = colors.HexColor("#20262B")
            muted = colors.HexColor("#66727A")
            ok_fill = colors.HexColor("#E9F3EC")
            warn_fill = colors.HexColor("#FFF4D9")
            bad_fill = colors.HexColor("#F9E4E4")

            base_styles = getSampleStyleSheet()
            styles = {
                "CoverTitle": ParagraphStyle("CoverTitle", parent=base_styles["Title"], fontName="Courier-Bold", fontSize=20, leading=25, alignment=TA_LEFT, textColor=navy, spaceAfter=10),
                "CoverSub": ParagraphStyle("CoverSub", parent=base_styles["Normal"], fontName="Courier", fontSize=11, leading=16, textColor=muted, spaceAfter=5),
                "H1": ParagraphStyle("H1", parent=base_styles["Heading1"], fontName="Courier-Bold", fontSize=13, leading=17, textColor=navy, spaceBefore=8, spaceAfter=8),
                "H2": ParagraphStyle("H2", parent=base_styles["Heading2"], fontName="Courier-Bold", fontSize=11, leading=15, textColor=blue, spaceBefore=7, spaceAfter=6),
                "PanelTitle": ParagraphStyle("PanelTitle", parent=base_styles["Heading2"], fontName="Courier-Bold", fontSize=12, leading=15, textColor=navy, spaceAfter=6),
                "Body": ParagraphStyle("Body", parent=base_styles["Normal"], fontName="Courier", fontSize=9.2, leading=13.5, textColor=dark, spaceAfter=6),
                "Small": ParagraphStyle("Small", parent=base_styles["Normal"], fontName="Courier", fontSize=7.8, leading=10.5, textColor=dark),
                "Tiny": ParagraphStyle("Tiny", parent=base_styles["Normal"], fontName="Courier", fontSize=6.8, leading=8.8, textColor=dark),
                "Cell": ParagraphStyle("Cell", parent=base_styles["Normal"], fontName="Courier", fontSize=7.4, leading=9.5, textColor=dark),
                "CellC": ParagraphStyle("CellC", parent=base_styles["Normal"], fontName="Courier", fontSize=7.4, leading=9.5, alignment=TA_CENTER, textColor=dark),
                "CellR": ParagraphStyle("CellR", parent=base_styles["Normal"], fontName="Courier", fontSize=7.4, leading=9.5, alignment=TA_RIGHT, textColor=dark),
                "Note": ParagraphStyle("Note", parent=base_styles["Normal"], fontName="Courier", fontSize=8, leading=11.5, textColor=muted, leftIndent=5*mm, borderColor=border, borderWidth=0.5, borderPadding=5, spaceBefore=4, spaceAfter=6),
            }

            class ProfessionalDocTemplate(BaseDocTemplate):
                def afterFlowable(self, flowable):
                    if isinstance(flowable, Paragraph):
                        style_name = getattr(flowable.style, "name", "")
                        level = None
                        if style_name == "H1": level = 0
                        elif style_name in {"H2", "PanelTitle"}: level = 1
                        if level is not None:
                            text = flowable.getPlainText()
                            key = f"h_{level}_{self.page}_{abs(hash((text, self.page))) % 10000000}"
                            self.canv.bookmarkPage(key)
                            try:
                                self.canv.addOutlineEntry(text, key, level=level, closed=False)
                            except Exception:
                                pass
                            self.notify("TOCEntry", (level, text, self.page, key))

            def header_footer(canvas, doc_obj, audit=False):
                canvas.saveState()
                canvas.setTitle(f"{APP_NAME} - {'Auditoria' if audit else 'Memória de Cálculo'}")
                canvas.setAuthor(APP_AUTHOR)
                canvas.setSubject(APP_SUBJECT)
                canvas.setCreator(f"{APP_NAME} {APP_VERSION}")
                canvas.setKeywords(APP_KEYWORDS)
                if doc_obj.page > 1:
                    w, h = canvas._pagesize
                    canvas.setStrokeColor(border)
                    canvas.setFillColor(muted)
                    canvas.setFont("Courier", 7.2)
                    canvas.drawString(doc_obj.leftMargin, h - 9*mm, f"{APP_NAME} {APP_VERSION} | {'Auditoria técnica' if audit else 'Memória de cálculo'}")
                    canvas.drawRightString(w - doc_obj.rightMargin, h - 9*mm, f"Página {doc_obj.page}")
                    canvas.line(doc_obj.leftMargin, h - 11*mm, w - doc_obj.rightMargin, h - 11*mm)
                    footer = f"Origem: {source_name[:65]} | {export_dt.strftime('%Y-%m-%d %H:%M')}"
                    canvas.drawString(doc_obj.leftMargin, 7*mm, footer)
                    canvas.drawRightString(w - doc_obj.rightMargin, 7*mm, APP_VERSION)
                canvas.restoreState()

            def p(text, style="Body"):
                return Paragraph(_esc(text), styles[style])

            def h(text, level=1):
                return Paragraph(_esc(text), styles["H1" if level == 1 else "H2"])

            def status_fill(status):
                s = _text(status).lower()
                if "não conforme" in s or "nao conforme" in s: return bad_fill
                if "verificar" in s or "ok*" in s: return warn_fill
                if "ok" in s: return ok_fill
                return light

            def review_condition(row):
                if row is None:
                    return "-"
                status = _text(_val(row, "Status_global", ""))
                if "não conforme" in status.lower() or "nao conforme" in status.lower():
                    return _text(_val(row, "Motivo_estado", "Verificação não satisfeita"))
                local = _text(_val(row, "Estado_local", ""))
                stress = _text(_val(row, "estado_ELS_tensoes", ""))
                try:
                    wr = float(_val(row, "wk_wmax_ratio", 0.0))
                except Exception:
                    wr = 0.0
                if stress not in {"-", "", "OK"}:
                    return "ELU/wk distribuídos conformes; rever limitação de tensões ELS"
                if wr >= 0.90:
                    return "ELU conforme; fendilhação próxima do limite"
                if "verificar" in local.lower():
                    return "ELU/ELS distribuídos conformes; verificação local necessária"
                return "ELU/ELS distribuídos conformes"

            def make_table(headers, rows, widths=None, header=True, small=False, align_right=None):
                data = []
                if header:
                    data.append([Paragraph(_esc(x), styles["CellC"]) for x in headers])
                for row in rows:
                    cells=[]
                    for j, x in enumerate(row):
                        sty = "Tiny" if small else ("CellR" if align_right and j in align_right else "Cell")
                        cells.append(Paragraph(_esc(x), styles[sty]))
                    data.append(cells)
                t = Table(data, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
                cmds = [
                    ("VALIGN", (0,0), (-1,-1), "TOP"),
                    ("GRID", (0,0), (-1,-1), 0.35, border),
                    ("LEFTPADDING", (0,0), (-1,-1), 4),
                    ("RIGHTPADDING", (0,0), (-1,-1), 4),
                    ("TOPPADDING", (0,0), (-1,-1), 3.5),
                    ("BOTTOMPADDING", (0,0), (-1,-1), 3.5),
                ]
                if header:
                    cmds += [("BACKGROUND", (0,0), (-1,0), navy), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Courier-Bold")]
                t.setStyle(TableStyle(cmds))
                return t

            def kv_table(items, widths=(54*mm, 118*mm)):
                rows=[[k, v] for k,v in items]
                t=make_table(["Parâmetro", "Valor"], rows, widths=list(widths))
                return t

            def status_box(status, reason=""):
                tbl=Table([[Paragraph(f"<b>{_esc(status)}</b>", styles["Cell"]), Paragraph(_esc(reason), styles["Cell"])]], colWidths=[32*mm, 140*mm])
                tbl.setStyle(TableStyle([
                    ("BACKGROUND",(0,0),(0,0),status_fill(status)), ("BOX",(0,0),(-1,-1),0.6,border),
                    ("VALIGN",(0,0),(-1,-1),"MIDDLE"), ("LEFTPADDING",(0,0),(-1,-1),5), ("RIGHTPADDING",(0,0),(-1,-1),5),
                    ("TOPPADDING",(0,0),(-1,-1),5), ("BOTTOMPADDING",(0,0),(-1,-1),5),
                ]))
                return tbl

            def panel_summary_row(panel):
                if not _has(summary): return None
                m=summary[summary["Panel"].astype(str)==str(panel)] if "Panel" in summary.columns else pd.DataFrame()
                return m.iloc[0] if not m.empty else None

            def panel_governing_row(panel):
                if not _has(governing): return None
                m=governing[governing["Panel"].astype(str)==str(panel)] if "Panel" in governing.columns else pd.DataFrame()
                return m.iloc[0] if not m.empty else None

            def panel_trace_rows(panel):
                if not _has(trace) or "Panel" not in trace.columns: return pd.DataFrame()
                return trace[trace["Panel"].astype(str)==str(panel)].copy()

            # -----------------------------------------------------------------
            # MEMÓRIA PRINCIPAL - A4 vertical
            # -----------------------------------------------------------------
            doc = ProfessionalDocTemplate(path, pagesize=A4, rightMargin=18*mm, leftMargin=20*mm, topMargin=18*mm, bottomMargin=15*mm)
            frame = Frame(doc.leftMargin, doc.bottomMargin, A4[0]-doc.leftMargin-doc.rightMargin, A4[1]-doc.topMargin-doc.bottomMargin, id="main")
            doc.addPageTemplates([PageTemplate(id="main", pagesize=A4, frames=[frame], onPage=lambda c,d: header_footer(c,d,False))])
            story=[]

            # Capa
            story += [Spacer(1, 32*mm), p("MEMÓRIA DE CÁLCULO", "CoverTitle"), p("Dimensionamento e verificação de lajes de betão armado", "CoverSub"), Spacer(1, 9*mm)]
            cover_rows=[
                ["Programa", f"{APP_NAME} {APP_VERSION}"],
                ["Norma de referência", "NP EN 1992-1-1 / Eurocódigo 2"],
                ["Origem dos esforços", source_name],
                ["Data de emissão", export_dt.strftime("%Y-%m-%d %H:%M")],
                ["Painéis analisados", str(len(summary)) if _has(summary) else "-"],
                ["Linhas analisadas", f"{len(self.df_results):,}".replace(",", " ")],
            ]
            ct=make_table([], cover_rows, widths=[48*mm, 120*mm], header=False)
            ct.setStyle(TableStyle([("BACKGROUND",(0,0),(0,-1),pale_blue),("FONTNAME",(0,0),(0,-1),"Courier-Bold")]))
            story += [ct, Spacer(1, 18*mm), p("Documento de cálculo gerado automaticamente. A decisão final de projeto, o tratamento das zonas locais e a compatibilização com os desenhos permanecem sob responsabilidade do projetista.", "Note"), PageBreak()]

            # Controlo documental / índice
            story += [h("Controlo documental",1), kv_table([
                ("Versão do programa", APP_VERSION), ("Repositório", GITHUB_URL), ("Ficheiro de origem", source_name),
                ("Folha de origem", _text(getattr(self,"input_source_sheet",None), "-")), ("Data/hora", export_dt.strftime("%Y-%m-%d %H:%M")),
                ("Documento complementar", os.path.basename(audit_path)),
            ]), Spacer(1,6*mm), h("Índice",1)]
            toc=TableOfContents(); toc.levelStyles=[ParagraphStyle("TOC1", fontName="Courier", fontSize=9, leading=13, leftIndent=0, firstLineIndent=0, textColor=dark), ParagraphStyle("TOC2", fontName="Courier", fontSize=8, leading=11, leftIndent=10*mm, firstLineIndent=0, textColor=muted)]
            story += [toc, PageBreak()]

            # 1 Objeto e âmbito
            story += [h("1. Objeto e âmbito",1), p("A presente memória apresenta o dimensionamento e a verificação das armaduras de flexão das lajes a partir dos esforços importados do modelo estrutural. O cálculo é efetuado por faixas de 1,00 m, com rastreabilidade da combinação e do nó governantes."),
                      h("1.1 Verificações incluídas",2), p("Flexão ELU; armadura mínima; fendilhação ELS quando ativada; limitação de tensões ELS; harmonização Base + reforços; identificação e separação auditável de concentrações nodais locais."),
                      h("1.2 Limitações desta versão",2), p("Corte unidirecional, punçoamento, deformação normativa, vibrações e interação N-M de membrana não são verificados automaticamente. QXX/QYY, UGZ e esforços de membrana são apenas informativos quando fornecidos."), PageBreak()]

            # 2 Bases
            story += [h("2. Bases de cálculo",1), h("2.1 Geometria e materiais",2), kv_table([
                ("Espessura da laje", f"{self.var_thickness.get()} mm"), ("Recobrimento nominal", f"{self.var_cover.get()} mm"),
                ("Betão", self.var_concrete.get()), ("Aço", f"fyk = {self.var_steel.get()} MPa"),
                ("Coeficientes materiais", f"γc={self.var_gamma_c.get()}; γs={self.var_gamma_s.get()}; αcc={self.var_alpha_cc.get()}"),
                ("Agregado", f"dg = {self.var_aggregate_mm.get()} mm"), ("Faixa de cálculo", "1,00 m"),
            ]), Spacer(1,5*mm), h("2.2 Combinações de ações",2), kv_table([
                ("ELU", self.var_uls_cases.get() or "-"), ("ELS característica", self.var_els_char_cases.get() or "-"),
                ("ELS frequente", self.var_els_freq_cases.get() or "-"), ("ELS quase-permanente", self.var_els_qp_cases.get() or "-"),
            ]), Spacer(1,5*mm), h("2.3 Convenções de cálculo",2), kv_table([
                ("Momentos", self.var_moment_unit.get()), ("Método", self.var_wa_method.get()),
                ("RAW: M>0 tracciona", self.var_positive_moment_face.get()), ("Malha exterior superior", self.var_top_outer_axis.get()),
                ("Malha exterior inferior", self.var_bottom_outer_axis.get()), ("Troca X/Y", "Sim" if self.var_swap_axes.get() else "Não"),
                ("Base direção principal", f"Ø{self.var_base_v_phi.get()}//{self.var_base_v_spacing.get()}"),
                ("Base direção secundária", f"Ø{self.var_base_h_phi.get()}//{self.var_base_h_spacing.get()}"),
            ]), PageBreak()]

            # 3 Critérios
            story += [h("3. Critérios de verificação",1), h("3.1 Flexão - ELU",2), p("A condição fundamental de verificação é MEd ≤ MRd. A resistência é avaliada por equilíbrio da secção e compatibilidade de extensões, considerando a posição física das camadas de armadura e a altura útil resultante."),
                      h("3.2 Fendilhação - ELS",2), p(f"Quando ativada, a largura de fendas é avaliada para as combinações quase-permanentes indicadas, com limite adotado wmax = {self.var_wmax.get()} mm. A condição de aceitação é wk ≤ wmax."),
                      h("3.3 Limitação de tensões",2), p("São reportadas as tensões no aço e no betão para as combinações ELS aplicáveis. Avisos relativos à compressão do betão são apresentados separadamente de uma não conformidade resistente."),
                      h("3.4 Tratamento de picos FEM",2), p(f"Política: {self.var_distributed_peak_policy.get()}. O valor RAW não é apagado. Concentrações estatisticamente localizadas podem ser separadas do envelope de armadura distribuída e passam a exigir verificação/pormenorização local, permanecendo integralmente auditáveis."), PageBreak()]

            # 4 resumo executivo
            story += [h("4. Resumo executivo",1)]
            if _has(summary):
                counts=summary.get("Status_global", pd.Series(dtype=str)).astype(str).value_counts().to_dict()
                story += [p("Estados globais: " + "; ".join(f"{k}: {v}" for k,v in counts.items()) + ".")]
                rows=[]
                for _,r in summary.iterrows():
                    rows.append([
                        _text(_val(r,"Panel")), _text(_val(r,"Status_global")), _num(_val(r,"util_ELU_max"),3),
                        _num(_val(r,"wk_max_mm"),3), _text(_val(r,"Estado_local")), review_condition(r),
                    ])
                t=make_table(["Painel","Estado","η ELU","wk [mm]","Estado local","Condicionante"], rows, widths=[17*mm,26*mm,18*mm,20*mm,32*mm,59*mm])
                # cor de estado por linha
                cmds=[]
                for i,(_,r) in enumerate(summary.iterrows(), start=1): cmds.append(("BACKGROUND",(1,i),(1,i),status_fill(_val(r,"Status_global"))))
                t.setStyle(TableStyle(cmds)); story += [t]
            else:
                story += [p("Sem resumo por painel disponível.")]
            story += [PageBreak()]

            # 5 fichas por painel
            story += [h("5. Resultados por painel",1), p("Cada ficha reúne o resultado de projeto e os governantes necessários para revisão. Os valores RAW e a auditoria detalhada encontram-se no PDF complementar."), Spacer(1,3*mm)]
            panels=[]
            if _has(summary) and "Panel" in summary.columns: panels=[_text(x) for x in summary["Panel"].tolist()]
            elif _has(governing) and "Panel" in governing.columns: panels=[_text(x) for x in governing["Panel"].tolist()]
            panels=sorted(dict.fromkeys(panels), key=_panel_key)
            for idx,panel in enumerate(panels):
                sr=panel_summary_row(panel); gr=panel_governing_row(panel); tr=panel_trace_rows(panel)
                story.append(Paragraph(f"Painel {_esc(panel)}", styles["PanelTitle"]))
                status=_text(_val(sr,"Status_global", _val(gr,"Status","-"))) if sr is not None or gr is not None else "-"
                reason=review_condition(sr) if sr is not None else _text(_val(gr,"Motivo_estado","-"))
                story += [status_box(status, reason), Spacer(1,3*mm)]
                if sr is not None:
                    story += [make_table(["ELU","wk","ELS tensões","Estado local","N nós locais","Util. RAW local"], [[
                        f"η={_num(_val(sr,'util_ELU_max'),3)} | {_text(_val(sr,'caso_governante_ELU'))}",
                        f"{_num(_val(sr,'wk_max_mm'),3)} mm | {_text(_val(sr,'caso_governante_ELS_wk'))}",
                        _text(_val(sr,'estado_ELS_tensoes')),
                        _text(_val(sr,'Estado_local')),
                        _text(_val(sr,'N_nós_locais')),
                        _num(_val(sr,'Util_local_RAW_max'),3),
                    ]], widths=[31*mm,31*mm,25*mm,35*mm,21*mm,29*mm]) , Spacer(1,3*mm)]
                if gr is not None:
                    story += [make_table(["Face/direção","Armadura adotada","Caso ELU","Nó ELU","Caso ELS/wk","Nó ELS/wk"], [
                        [face, _text(_val(gr,f"{face}_adopted")), _text(_val(gr,f"{face}_case_ELU")), _text(_val(gr,f"{face}_node_ELU")), _text(_val(gr,f"{face}_case_ELS")), _text(_val(gr,f"{face}_node_ELS"))]
                        for face in ["X+","X-","Y+","Y-"]
                    ], widths=[22*mm,48*mm,28*mm,22*mm,28*mm,22*mm]), Spacer(1,3*mm)]
                if _has(tr):
                    rows=[]
                    for face in ["X+","X-","Y+","Y-"]:
                        sub=tr[tr.get("Face_direção", pd.Series(index=tr.index,dtype=str)).astype(str)==face]
                        elu=sub[sub.get("Estado_limite",pd.Series(index=sub.index,dtype=str)).astype(str).str.contains("ELU",na=False)]
                        els=sub[sub.get("Estado_limite",pd.Series(index=sub.index,dtype=str)).astype(str).str.contains("ELS",na=False)]
                        er=elu.iloc[0] if not elu.empty else None; wr=els.iloc[0] if not els.empty else None
                        rows.append([face, _num(_val(er,"MEd_governante_kNm_m") if er is not None else None,2), _num(_val(er,"As_req_mm2_m") if er is not None else None,0), _num(_val(er,"As_prov_mm2_m") if er is not None else None,0), _num(_val(er,"MRd_kNm_m") if er is not None else None,2), _num(_val(er,"util_M_face") if er is not None else None,3), _num(_val(wr,"wk_face_mm") if wr is not None else None,3), _num(_val(wr,"sigma_s_face_MPa") if wr is not None else None,1)])
                    story += [make_table(["Face","MEd","As,req","As,prov","MRd","η","wk","σs"], rows, widths=[14*mm,23*mm,22*mm,22*mm,23*mm,18*mm,20*mm,24*mm], align_right={1,2,3,4,5,6,7}), Spacer(1,3*mm)]
                action=_text(_val(sr,"Acção_recomendada","-")) if sr is not None else "-"
                if action != "-": story.append(p("Nota de revisão: " + action, "Note"))
                if idx < len(panels)-1: story.append(PageBreak())

            # 6 armaduras e zonas
            story += [PageBreak(), h("6. Quadro geral de armaduras",1)]
            if _has(governing):
                rows=[]
                for _,r in governing.sort_values("Panel", key=lambda s:s.map(_panel_key)).iterrows():
                    rows.append([_text(_val(r,"Panel")),_text(_val(r,"X+_adopted")),_text(_val(r,"X-_adopted")),_text(_val(r,"Y+_adopted")),_text(_val(r,"Y-_adopted")),_text(_val(r,"Status"))])
                story += [make_table(["Painel","X+","X-","Y+","Y-","Estado"], rows, widths=[18*mm,36*mm,36*mm,36*mm,36*mm,24*mm])]
            if _has(self.df_zones):
                story += [Spacer(1,6*mm), h("6.1 Zonas harmonizadas",2)]
                zrows=[]
                for _,r in self.df_zones.iterrows(): zrows.append([_text(_val(r,"Zona")),_text(_val(r,"Painéis")),_text(_val(r,"X+")),_text(_val(r,"X-")),_text(_val(r,"Y+")),_text(_val(r,"Y-"))])
                story += [make_table(["Zona","Painéis","X+","X-","Y+","Y-"], zrows, widths=[18*mm,42*mm,30*mm,30*mm,30*mm,30*mm])]

            # 7 revisão e conclusão
            story += [PageBreak(), h("7. Pontos para revisão do projetista",1)]
            if _has(diagnostics):
                d=diagnostics.copy()
                if "Severidade" in d.columns:
                    d["_rank"]=d["Severidade"].astype(str).map({"Alta":0,"Média":1,"Media":1,"Baixa":2}).fillna(3)
                    d=d.sort_values("_rank").drop(columns=["_rank"])
                drows=[]
                for _,r in d.head(30).iterrows(): drows.append([_text(_val(r,"Painel")),_text(_val(r,"Severidade")),_text(_val(r,"Problema")),_text(_val(r,"Acção recomendada"))])
                story += [make_table(["Painel","Severidade","Questão","Ação"], drows, widths=[20*mm,24*mm,92*mm,44*mm])]
                if len(d)>30: story += [p(f"O diagnóstico completo contém {len(d)} registos e encontra-se no PDF de auditoria.","Note")]
            else: story += [p("Não existem registos de diagnóstico.")]
            story += [Spacer(1,5*mm), h("8. Conclusão e limitações",1), p("Os estados apresentados referem-se exclusivamente às verificações implementadas nesta versão. A adoção das armaduras requer compatibilização com a geometria, apoios, aberturas, amarrações, sobreposições, punçoamento, corte e deformação quando aplicáveis."), p(f"A rastreabilidade completa dos governantes, picos FEM e verificações de consistência é fornecida em '{os.path.basename(audit_path)}'. O workbook Excel mantém os resultados completos linha-a-linha."), Spacer(1,6*mm), p(f"Repositório: {GITHUB_URL}","Small")]

            self.progress_var.set(45.0); self.status_var.set("A compor memória principal..."); self.update_idletasks()
            doc.multiBuild(story)

            # -----------------------------------------------------------------
            # AUDITORIA - A4 paisagem
            # -----------------------------------------------------------------
            adoc=ProfessionalDocTemplate(audit_path,pagesize=landscape(A4),rightMargin=14*mm,leftMargin=14*mm,topMargin=17*mm,bottomMargin=14*mm)
            aps=landscape(A4); aframe=Frame(adoc.leftMargin,adoc.bottomMargin,aps[0]-adoc.leftMargin-adoc.rightMargin,aps[1]-adoc.topMargin-adoc.bottomMargin,id="audit")
            adoc.addPageTemplates([PageTemplate(id="audit",pagesize=aps,frames=[aframe],onPage=lambda c,d:header_footer(c,d,True))])
            astory=[Spacer(1,12*mm), p("AUDITORIA TÉCNICA", "CoverTitle"), p("Rastreabilidade dos resultados da memória de cálculo", "CoverSub"), Spacer(1,5*mm), kv_table([("Programa",f"{APP_NAME} {APP_VERSION}"),("Memória principal",os.path.basename(path)),("Origem",source_name),("Linhas analisadas",f"{len(self.df_results):,}".replace(","," "))], widths=(58*mm,190*mm)), PageBreak()]

            def audit_table(title, df, cols, widths, max_rows=None):
                astory.append(h(title,1))
                if not _has(df): astory.append(p("Sem dados disponíveis.")); return
                present=[c for c in cols if c in df.columns]
                if not present: astory.append(p("Sem colunas aplicáveis.")); return
                work=df[present].copy()
                if max_rows is not None and len(work)>max_rows: work=work.head(max_rows)
                hdr=[c.replace("_"," ") for c in present]
                rows=[[_text(v) if not isinstance(v,float) else _num(v,3) for v in row] for row in work.itertuples(index=False,name=None)]
                astory.append(make_table(hdr,rows,widths=widths,small=True)); astory.append(Spacer(1,4*mm))

            audit_table("A1. Resumo completo por painel", summary, ["Panel","Status_global","util_ELU_max","caso_governante_ELU","node_governante_ELU","wk_max_mm","wk_wmax_ratio","caso_governante_ELS_wk","node_governante_ELS_wk","estado_ELS_tensoes","Estado_local","N_nós_locais","Util_local_RAW_max"], [14*mm,20*mm,18*mm,22*mm,18*mm,18*mm,18*mm,22*mm,18*mm,24*mm,28*mm,16*mm,20*mm])
            astory.append(PageBreak())
            audit_table("A2. Governantes - resistência e armadura", trace, ["Panel","Face_direção","Estado_limite","Case_governante","Node_governante","MEd_governante_kNm_m","As_req_mm2_m","As_prov_mm2_m","Armadura_adoptada","MRd_kNm_m","util_M_face"], [14*mm,18*mm,30*mm,21*mm,19*mm,24*mm,22*mm,22*mm,42*mm,22*mm,18*mm])
            audit_table("A2B. Governantes - ELS e picos", trace, ["Panel","Face_direção","Estado_limite","Case_governante","Node_governante","wk_face_mm","sigma_s_face_MPa","FEM_peak_flag","FEM_peak_ratio"], [16*mm,20*mm,34*mm,24*mm,22*mm,22*mm,26*mm,24*mm,24*mm])
            astory.append(PageBreak())
            audit_table("A3. Picos FEM - estatística", peaks, ["Panel","Pico_FEM","Mmax_kNm_m","P95_kNm_m","P99_kNm_m","Pico_ratio_max_P95","Pico_ratio_max_P99","Nó_pico","Caso_pico","N_candidatos_P99","Frac_nós_>=90%Mmax"], [15*mm,18*mm,22*mm,22*mm,22*mm,23*mm,23*mm,20*mm,22*mm,22*mm,30*mm])
            audit_table("A3B. Picos FEM - classificação e decisão", peaks, ["Panel","Classificação_pico","Estado_local_singular","Util_local_singular_max","wk_wmax_local_singular_max","Recomendação_pico"], [16*mm,70*mm,38*mm,30*mm,34*mm,78*mm])
            astory.append(PageBreak())
            audit_table("A4. Diagnóstico", diagnostics, ["Painel","Severidade","Problema","Acção recomendada","Origem"], [18*mm,22*mm,125*mm,65*mm,35*mm])
            audit_table("A5. Validação da tabela importada", self.df_data_validation, ["Categoria","Item","Estado","Resultado","Nota"], [34*mm,48*mm,25*mm,52*mm,105*mm])
            audit_table("A6. Unidades e consistência", self.df_unit_check, ["Grandeza","Unidade selecionada","Factor aplicado","Máximo convertido","Unidade interna","Nota"], [38*mm,40*mm,32*mm,40*mm,34*mm,80*mm])
            audit_table("A7. Notas normativas e hipóteses", self.df_notes, ["Tema","Critério adoptado","Nota"], [40*mm,60*mm,164*mm])
            opt_src = self.df_optimization.sort_values("util_max",ascending=False) if _has(self.df_optimization) and "util_max" in self.df_optimization.columns else self.df_optimization
            audit_table("A8. Harmonização / otimização - linhas críticas", opt_src, ["Panel","Node","Case","Status","X+_rebar","X-_rebar","Y+_rebar","Y-_rebar","Constructability_status","util_max"], [14*mm,18*mm,20*mm,22*mm,30*mm,30*mm,30*mm,30*mm,32*mm,18*mm], max_rows=120)
            astory += [PageBreak(), h("A9. Nota sobre completude",1), p("O PDF de auditoria contém os resultados necessários à revisão dos governantes e das decisões automáticas. A tabela completa com todas as linhas FEM permanece no workbook Excel, evitando reproduzir centenas de milhares ou milhões de registos num documento paginado.")]

            self.progress_var.set(75.0); self.status_var.set("A compor PDF de auditoria..."); self.update_idletasks()
            adoc.multiBuild(astory)

            self.progress_var.set(100.0)
            self.status_var.set(f"Memória e auditoria exportadas: {path}")
            try:
                messagebox.showinfo("Exportação concluída", f"Memória de cálculo:\n{path}\n\nAuditoria técnica:\n{audit_path}")
            except Exception:
                pass
        except Exception as e:
            self.progress_var.set(0.0)
            messagebox.showerror("Erro", f"Não foi possível gerar a memória de cálculo.\n\nDetalhe técnico: {e}")
