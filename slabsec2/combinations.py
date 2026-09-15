# -*- coding: utf-8 -*-
"""Utilitários para especificação e classificação de combinações/casos.

Aceita listas e intervalos compactos, por exemplo:
    101-117 201-216
    101para117; 201para216
    101 a 117, 201 até 216
    101 103 105
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Set

from .importers import canonical_case_id


class CombinationSpecError(ValueError):
    pass


_RANGE_CONNECTOR_RE = re.compile(
    r"(?i)(\d+)\s*(?:para|até|ate|a|[-–—:])\s*(\d+)"
)


def parse_case_spec(text: object, *, max_range_size: int = 2000) -> List[str]:
    """Expande uma especificação compacta para IDs canónicos, preservando a ordem.

    Exemplos:
      ``101-103 201`` -> ["101", "102", "103", "201"]
      ``101para103`` -> ["101", "102", "103"]

    Intervalos descendentes são rejeitados para evitar erros silenciosos.
    """
    raw = str(text or "").strip()
    if not raw:
        return []

    normalized = raw.replace("\n", " ").replace("\t", " ")
    # Normaliza conectores de intervalo para hífen.
    normalized = _RANGE_CONNECTOR_RE.sub(lambda m: f"{m.group(1)}-{m.group(2)}", normalized)
    # Separadores de itens.
    tokens = [t for t in re.split(r"[;,\s]+", normalized) if t]

    out: List[str] = []
    seen: Set[str] = set()
    for tok in tokens:
        if re.fullmatch(r"\d+-\d+", tok):
            a_s, b_s = tok.split("-", 1)
            a, b = int(a_s), int(b_s)
            if b < a:
                raise CombinationSpecError(
                    f"Intervalo descendente não permitido: {tok}. Use {b}-{a} apenas se essa for a sequência pretendida."
                )
            if (b - a + 1) > max_range_size:
                raise CombinationSpecError(
                    f"Intervalo demasiado extenso: {tok} ({b-a+1} casos)."
                )
            values = [str(i) for i in range(a, b + 1)]
        else:
            cid = canonical_case_id(tok)
            # Não aceitar tokens sem qualquer número (evita ignorar texto inválido silenciosamente).
            if not cid or not re.search(r"\d", tok):
                raise CombinationSpecError(f"Especificação de combinação inválida: {tok!r}.")
            values = [cid]

        for cid in values:
            if cid not in seen:
                seen.add(cid)
                out.append(cid)
    return out


def case_spec_set(text: object) -> Set[str]:
    return set(parse_case_spec(text))


def _sort_key(cid: str):
    return (0, int(cid)) if str(cid).isdigit() else (1, str(cid))


def format_case_ids(ids: Iterable[object], *, compress: bool = True) -> str:
    """Formata IDs; sequências numéricas consecutivas são comprimidas em intervalos."""
    vals = []
    seen = set()
    for v in ids:
        cid = canonical_case_id(v)
        if cid and cid not in seen:
            seen.add(cid)
            vals.append(cid)
    vals = sorted(vals, key=_sort_key)
    if not vals:
        return ""
    if not compress or not all(v.isdigit() for v in vals):
        return ", ".join(vals)

    nums = [int(v) for v in vals]
    groups = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        groups.append((start, prev))
        start = prev = n
    groups.append((start, prev))

    parts = []
    for a, b in groups:
        if a == b:
            parts.append(str(a))
        elif b == a + 1:
            parts.extend([str(a), str(b)])
        else:
            parts.append(f"{a}-{b}")
    return " ".join(parts)


def find_overlaps(*groups: Sequence[object]) -> Set[str]:
    sets = [set(canonical_case_id(x) for x in g if canonical_case_id(x)) for g in groups]
    overlaps: Set[str] = set()
    for i in range(len(sets)):
        for j in range(i + 1, len(sets)):
            overlaps |= sets[i] & sets[j]
    return overlaps
