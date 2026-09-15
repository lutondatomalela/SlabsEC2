# -*- coding: utf-8 -*-
"""Contexto geométrico opcional do SlabsEC2.

Este pacote não é necessário para o núcleo ELU/ELS. Quando disponível, pode apenas
contextualizar picos ou, se o utilizador activar explicitamente o modo local, separar
armadura distribuída e armadura local sem modificar os esforços FEM brutos.
"""
from .importers import read_geometry_file, clean_geometry_dataframe
from .context import (
    enrich_peak_assessment_with_geometry,
    geometry_summary,
    build_geometry_peak_diagnostic,
    merge_geometry_peak_context_into_summary,
)
from .local_design import (
    build_geometry_local_design, merge_local_design_into_summary,
    build_local_design_diagnostic, identify_local_zone_nodes,
)

__all__ = [
    "read_geometry_file", "clean_geometry_dataframe",
    "enrich_peak_assessment_with_geometry", "geometry_summary",
    "build_geometry_peak_diagnostic", "merge_geometry_peak_context_into_summary",
    "build_geometry_local_design", "merge_local_design_into_summary",
    "build_local_design_diagnostic", "identify_local_zone_nodes",
]
