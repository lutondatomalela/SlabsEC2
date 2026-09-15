# -*- coding: utf-8 -*-
from dataclasses import dataclass

@dataclass
class RebarSolution:
    phi: float
    spacing: float
    as_prov: float
    text_override: str = ""
    base_text: str = ""
    add_text: str = ""
    as_base: float = 0.0
    as_add: float = 0.0
    optimization_note: str = ""
    n_iterations: int = 0
    capacity_limited: bool = False
    limit_note: str = ""
    minimum_valid_text: str = ""
    constructability_status: str = "OK"
    constructability_note: str = ""
    reinforcement_ratio_add_base: float = 0.0

    @property
    def text(self) -> str:
        if self.text_override:
            return self.text_override
        return f"Ø{int(self.phi)}//{int(self.spacing)}"

