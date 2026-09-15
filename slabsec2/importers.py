# -*- coding: utf-8 -*-
import csv
import io
import re
from typing import List, Optional, Tuple
import pandas as pd
from .utils import normalize_text, safe_float

COLUMN_ALIASES = {
    "panel_node_case": [
        "panel/node/case", "panel / node / case", "panel/node", "panel node case",
        "object/node/case", "object / node / case", "element/node/case",
        "finite element/node/case", "fe/node/case", "painel/nó/caso", "painel/no/caso"
    ],
    "panel": ["panel", "painel", "object", "element", "finite element", "fe", "objeto", "elemento"],
    "node": ["node", "nó", "no"],
    "case": ["case", "caso", "combination", "combinação", "combinacao"],
    "mxx": ["mxx (knm/m)", "mxx [knm/m]", "mxx", "mx (knm/m)", "mx [knm/m]", "mx"],
    "myy": ["myy (knm/m)", "myy [knm/m]", "myy", "my (knm/m)", "my [knm/m]", "my"],
    "mxy": ["mxy (knm/m)", "mxy [knm/m]", "mxy", "mxyy"],
    # Momentos equivalentes já tratados pelo software de análise/cálculo para dimensionamento de armadura.
    # O sinal + ou - no cabeçalho identifica a face: + = superior; - = inferior.
    "mxx_wa_pos": [
        "mxx+", "mx+", "mxx+ (w&a)", "mx+ (w&a)",
        "mxx+ (w&a) (knm/m)", "mxx+ [w&a] [knm/m]",
        "mxx+ (wood & armer)", "mxx+ (wood and armer)",
        "mxx sup", "mxx superior", "mx sup", "mx superior",
        "mxx top", "mx top", "mxx+ (knm/m)", "mx+ (knm/m)"
    ],
    "mxx_wa_neg": [
        "mxx-", "mx-", "mxx- (w&a)", "mx- (w&a)",
        "mxx- (w&a) (knm/m)", "mxx- [w&a] [knm/m]",
        "mxx- (wood & armer)", "mxx- (wood and armer)",
        "mxx inf", "mxx inferior", "mx inf", "mx inferior",
        "mxx bottom", "mx bottom", "mxx- (knm/m)", "mx- (knm/m)"
    ],
    "myy_wa_pos": [
        "myy+", "my+", "myy+ (w&a)", "my+ (w&a)",
        "myy+ (w&a) (knm/m)", "myy+ [w&a] [knm/m]",
        "myy+ (wood & armer)", "myy+ (wood and armer)",
        "myy sup", "myy superior", "my sup", "my superior",
        "myy top", "my top", "myy+ (knm/m)", "my+ (knm/m)"
    ],
    "myy_wa_neg": [
        "myy-", "my-", "myy- (w&a)", "my- (w&a)",
        "myy- (w&a) (knm/m)", "myy- [w&a] [knm/m]",
        "myy- (wood & armer)", "myy- (wood and armer)",
        "myy inf", "myy inferior", "my inf", "my inferior",
        "myy bottom", "my bottom", "myy- (knm/m)", "my- (knm/m)"
    ],
    "qxx": ["qxx (kn/m)", "qxx [kn/m]", "qxx", "qx (kn/m)", "qx [kn/m]", "qx", "vxx", "vx"],
    "qyy": ["qyy (kn/m)", "qyy [kn/m]", "qyy", "qy (kn/m)", "qy [kn/m]", "qy", "vyy", "vy"],
    "ugz": ["ugz (cm)", "ugz [cm]", "ugz (mm)", "ugz [mm]", "ugz", "uz (cm)", "uz [cm]", "uz", "u z", "deslocamento z", "deslocamento global z", "w", "flecha"],
    "nxx": ["nxx (kn/m)", "nxx [kn/m]", "nxx", "nx (kn/m)", "nx [kn/m]", "nx"],
    "nyy": ["nyy (kn/m)", "nyy [kn/m]", "nyy", "ny (kn/m)", "ny [kn/m]", "ny"],
    "nxy": ["nxy (kn/m)", "nxy [kn/m]", "nxy"],
}

def header_field_order(header_line: str) -> List[Optional[str]]:
    """Detecta a ordem dos campos numéricos depois de Panel/Node/Case em tabelas copiadas com espaços.

    Modos suportados:
    1) Momentos brutos de placa: MXX, MYY, MXY.
    2) Momentos equivalentes importados para armadura: MXX+, MXX-, MYY+, MYY-.

    No modo de momentos equivalentes, + identifica a armadura superior e - identifica a armadura inferior.
    O campo Panel repetido, quando existir, é consumido mas não substitui o painel identificado em Panel/Node/Case.
    """
    h = normalize_text(header_line)
    h2 = h.replace("[", " ").replace("]", " ").replace("(", " ").replace(")", " ")

    patterns = [
        ("mxx_wa_pos", r"\bmxx\s*\+|\bmx\s*\+"),
        ("mxx_wa_neg", r"\bmxx\s*-|\bmx\s*-"),
        ("myy_wa_pos", r"\bmyy\s*\+|\bmy\s*\+"),
        ("myy_wa_neg", r"\bmyy\s*-|\bmy\s*-"),
        ("mxx", r"\bmxx\b(?!\s*[+-])|\bmx\b(?!\s*[+-])"),
        ("myy", r"\bmyy\b(?!\s*[+-])|\bmy\b(?!\s*[+-])"),
        ("mxy", r"\bmxy\b|\bmxyy\b"),
        ("qxx", r"\bqxx\b|\bqx\b|\bvxx\b|\bvx\b"),
        ("qyy", r"\bqyy\b|\bqy\b|\bvyy\b|\bvy\b"),
        ("ugz", r"\bugz\b|\buz\b|\bflecha\b|\bdeslocamento\s+z\b|\bdeslocamento\s+global\s+z\b"),
        ("nxx", r"\bnxx\b|\bnx\b"),
        ("nyy", r"\bnyy\b|\bny\b"),
        ("nxy", r"\bnxy\b"),
        (None, r"\bpanel\b|\bpainel\b|\bobject\b|\belement\b|\bfe\b"),
    ]
    matches = []
    for fld, pat in patterns:
        for m in re.finditer(pat, h2):
            matches.append((m.start(), m.end(), fld))
    if not matches:
        return []
    # Remove sobreposições, privilegiando padrões específicos (+/-) sobre padrões genéricos.
    matches.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    selected = []
    for s, e, fld in matches:
        if any(not (e <= ss or s >= ee) for ss, ee, _ in selected):
            continue
        selected.append((s, e, fld))
    selected.sort(key=lambda x: x[0])

    first_m = None
    for s, _e, fld in selected:
        if fld in {"mxx", "myy", "mxy", "mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"}:
            first_m = s
            break
    if first_m is None:
        return []
    return [fld for s, _e, fld in selected if s >= first_m]

def parse_pasted_table(text: str) -> pd.DataFrame:
    text = text.strip()
    if not text:
        return pd.DataFrame()

    # Excel/tabela de cálculo copiado normalmente vem separado por tabs, ponto e vírgula ou barras verticais.
    for sep in ("\t", ";", "|"):
        try:
            df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", dtype=str)
            if len(df.columns) > 1:
                return df
        except Exception:
            pass

    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 2:
        return pd.DataFrame()

    # Leitura robusta para tabelas copiadas do software de análise estrutural com espaços simples, por exemplo:
    # 43/ 49/ 302 (CQC) -2,17 -0,13 0,83 5,59 3,69 -0,193
    fem_rows = []
    row_re = re.compile(
        r"^\s*(?P<panel>\S+)\s*/\s*(?P<node>\S+)\s*/\s*(?P<case>\d+)\s*"
        r"(?P<casetype>\([^)]*\))?\s+(?P<rest>.*)$"
    )
    num_re = re.compile(r"[-+]?\d+(?:[\.,]\d+)?")
    field_order = header_field_order(lines[0])
    fallback_order = ["mxx", "myy", "mxy", "qxx", "qyy"]
    if not field_order:
        field_order = fallback_order
    for ln in lines[1:]:
        m = row_re.match(ln)
        if not m:
            fem_rows = []
            break
        nums = num_re.findall(m.group("rest"))
        if len(nums) < 5:
            fem_rows = []
            break
        case_txt = m.group("case")
        if m.group("casetype"):
            case_txt = f"{case_txt} {m.group('casetype').strip()}"
        rec = {
            "panel_node_case": f"{m.group('panel')}/{m.group('node')}/{case_txt}",
            "panel": m.group("panel"),
            "node": m.group("node"),
            "case": case_txt,
        }
        # Consome valores pela ordem detectada no cabeçalho. None corresponde ao Panel repetido no software de análise estrutural.
        consumed = 0
        for fld in field_order:
            if consumed >= len(nums):
                break
            if fld is not None:
                rec[fld] = nums[consumed]
            consumed += 1
        # Fallback apenas para tabelas RAW. Em tabelas de momentos equivalentes,
        # criar artificialmente MXX/MYY/MXY tornaria o formato ambíguo.
        wa_header = any(f in {"mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"} for f in field_order if f)
        if not wa_header:
            for fld, val in zip(fallback_order, nums):
                rec.setdefault(fld, val)
        fem_rows.append(rec)
    if fem_rows:
        return pd.DataFrame(fem_rows)

    # Fallback para espaços múltiplos.
    rows = [re.split(r"\s{2,}", ln.strip()) for ln in lines]
    header = rows[0]
    body = rows[1:]
    width = len(header)
    body = [r[:width] + [""] * max(0, width - len(r)) for r in body]
    return pd.DataFrame(body, columns=header)

def dataframe_to_tsv_preview(df: pd.DataFrame, max_rows: int = 5000) -> str:
    """Converte uma tabela importada para texto tabulado, só para pré-visualização na GUI."""
    if df is None or df.empty:
        return ""
    preview = df.head(max_rows).copy()
    text = preview.to_csv(index=False, sep="\t", lineterminator="\n")
    if len(df) > max_rows:
        text += f"\n... pré-visualização limitada a {max_rows} linhas de {len(df)} linhas importadas. A tabela completa está na aba 'Tabela'.\n"
    return text

def _decode_bytes_robust(raw: bytes) -> Tuple[str, str]:
    """Lê CSV/texto exportado por software de cálculo em diferentes codificações usuais."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                return raw.decode(enc), enc
            except UnicodeError:
                pass
    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            return raw.decode("utf-8-sig"), "utf-8-sig"
        except UnicodeError:
            pass
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin1", "utf-16", "utf-16-le", "utf-16-be"):
        try:
            return raw.decode(enc), enc
        except UnicodeError:
            continue
    return raw.decode("latin1", errors="replace"), "latin1-replace"

def _detect_csv_separator(text: str) -> Optional[str]:
    """Detecta separador provável, sem depender do locale do Windows."""
    sample_lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    if not sample_lines:
        return None
    sample = "\n".join(sample_lines)
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=["\t", ";", ",", "|"])
        return dialect.delimiter
    except Exception:
        pass
    scores = {}
    for sep in ["\t", ";", ",", "|"]:
        counts = [ln.count(sep) for ln in sample_lines]
        positive = [c for c in counts if c > 0]
        if positive:
            scores[sep] = (len(positive), sum(positive), -max(positive) + min(positive))
    if not scores:
        return None
    return max(scores.items(), key=lambda kv: kv[1])[0]

def read_delimited_file_robust(path: str) -> Tuple[pd.DataFrame, str]:
    """Importa CSV/TXT robustamente com caminho optimizado para ficheiros grandes.

    A detecção de codificação/separador usa apenas uma amostra inicial do ficheiro. Depois,
    ``pandas`` lê directamente do disco, evitando manter simultaneamente ``bytes`` + texto
    decodificado + ``StringIO`` em memória. Em tabelas com centenas de milhares de linhas
    esta redução é significativa.
    """
    sample_size = 512 * 1024
    with open(path, "rb") as f:
        raw_sample = f.read(sample_size)
    sample_text, encoding = _decode_bytes_robust(raw_sample)
    if "\x00" in sample_text and not encoding.startswith("utf-16"):
        for enc in ("utf-16", "utf-16-le", "utf-16-be"):
            try:
                sample_text = raw_sample.decode(enc)
                encoding = enc
                break
            except UnicodeError:
                pass
    sep = _detect_csv_separator(sample_text)
    # O motor C é substancialmente mais rápido e usa menos memória quando o separador é conhecido.
    kwargs = {"dtype": str, "encoding": encoding}
    if sep is not None:
        kwargs.update({"sep": sep, "engine": "c", "low_memory": False})
    else:
        kwargs.update({"sep": None, "engine": "python"})
    try:
        df = pd.read_csv(path, **kwargs)
    except Exception:
        # Fallback integral mantém compatibilidade com exports pouco convencionais.
        with open(path, "rb") as f:
            raw = f.read()
        text, encoding = _decode_bytes_robust(raw)
        sep = _detect_csv_separator(text)
        df = pd.read_csv(io.StringIO(text), sep=sep, engine="python", dtype=str)
    source_note = f"codificação: {encoding}; separador: {repr(sep) if sep is not None else 'auto'}"
    return df, source_note

def rename_known_columns(df: pd.DataFrame) -> pd.DataFrame:
    norm_to_original = {normalize_text(c): c for c in df.columns}
    rename_map = {}
    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in norm_to_original:
                rename_map[norm_to_original[alias]] = target
                break
    # fallback: remove units/brackets and retry, useful for software de análise estrutural tables with headers like MXX [kNm/m].
    for original in df.columns:
        if original in rename_map:
            continue
        simplified = normalize_text(re.sub(r"[\[\(].*?[\]\)]", "", str(original)))
        for target, aliases in COLUMN_ALIASES.items():
            if target in rename_map.values():
                continue
            if simplified in [normalize_text(re.sub(r"[\[\(].*?[\]\)]", "", a)) for a in aliases]:
                rename_map[original] = target
                break
    return df.rename(columns=rename_map).copy()

def split_panel_node_case(s: str) -> Tuple[str, str, str]:
    parts = [p.strip() for p in str(s).split("/")]
    panel = parts[0] if len(parts) > 0 else ""
    node = parts[1] if len(parts) > 1 else ""
    case = parts[2] if len(parts) > 2 else ""
    return panel, node, case

def canonical_case_id(value: object) -> str:
    """Extrai o número do caso/combinação, ignorando textos como (C), (CQC)."""
    txt = normalize_text(str(value))
    txt = txt.replace("case", "").replace("caso", "").replace("comb.", "").replace("comb", "")
    m = re.search(r"\d+", txt)
    return m.group(0) if m else txt.strip()

def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza a tabela importada.

    Para grandes volumes usa operações vectorizadas; evita ``map(lambda ...)`` em cada célula,
    que era um dos principais custos de importação em tabelas >100k linhas.
    """
    df = rename_known_columns(df)
    df["__row_order"] = range(len(df))

    wa_cols = ["mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"]
    raw_cols = ["mxx", "myy", "mxy"]
    wa_present = [c for c in wa_cols if c in df.columns]
    raw_present_cols = [c for c in raw_cols if c in df.columns]
    wa_full = len(wa_present) == len(wa_cols)
    raw_full = len(raw_present_cols) == len(raw_cols)

    # v2.15 — entrada fail-safe: não completar silenciosamente momentos em falta e
    # não escolher arbitrariamente entre RAW e equivalentes quando ambos existem.
    if wa_present and not wa_full:
        missing = [c for c in wa_cols if c not in df.columns]
        raise ValueError("Tabela de momentos equivalentes incompleta. Faltam: " + ", ".join(missing) + ".")
    if raw_present_cols and not raw_full:
        missing = [c for c in raw_cols if c not in df.columns]
        raise ValueError("Tabela RAW de placa incompleta. Faltam: " + ", ".join(missing) + ".")
    if wa_full and raw_full:
        raise ValueError(
            "Formato de momentos ambíguo: foram detectados simultaneamente MXX/MYY/MXY RAW e "
            "MXX+/MXX-/MYY+/MYY-. Forneça apenas um dos formatos para evitar dupla transformação."
        )
    if wa_full:
        moment_input_mode = "direct_wa"
    elif raw_full:
        moment_input_mode = "raw_plate"
    else:
        raise ValueError(
            "Não foi reconhecido um formato completo de momentos. Forneça MXX/MYY/MXY ou "
            "MXX+/MXX-/MYY+/MYY-."
        )
    df["__moment_input_mode"] = moment_input_mode

    if "panel_node_case" in df.columns:
        parts = df["panel_node_case"].astype(str).str.split("/", n=2, expand=True)
        df["panel_from_id"] = parts[0].str.strip() if parts.shape[1] > 0 else ""
        if "node" not in df.columns:
            df["node"] = parts[1].str.strip() if parts.shape[1] > 1 else ""
        if "case" not in df.columns:
            df["case"] = parts[2].str.strip() if parts.shape[1] > 2 else ""
    else:
        df["panel_from_id"] = ""
        if "node" not in df.columns:
            df["node"] = ""
        if "case" not in df.columns:
            df["case"] = ""

    if "panel" not in df.columns:
        df["panel"] = df["panel_from_id"]
    df["panel"] = df["panel"].astype(str).replace("nan", "")
    blank_panel = df["panel"].str.strip().eq("")
    if blank_panel.any():
        df.loc[blank_panel, "panel"] = df.loc[blank_panel, "panel_from_id"]

    if "case" in df.columns:
        case_txt = df["case"].astype(str)
        extracted = case_txt.str.extract(r"(\d+)", expand=False)
        df["case_id"] = extracted
        missing = extracted.isna()
        if missing.any():
            df.loc[missing, "case_id"] = case_txt.loc[missing].map(canonical_case_id)

    # Preserve a distinção entre "campo não fornecido" e "campo fornecido com valor zero".
    # O motor pode continuar a trabalhar com zeros internos para os campos opcionais, mas
    # relatórios/auditoria nunca devem interpretar esses zeros como resultados importados.
    optional_numeric_cols = ["qxx", "qyy", "ugz", "nxx", "nyy", "nxy"]
    provided_optional = {c: (c in df.columns) for c in optional_numeric_cols}
    for c, provided in provided_optional.items():
        df[f"__provided_{c}"] = bool(provided)

    numeric_cols = ["mxx", "myy", "mxy", "mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg",
                    "qxx", "qyy", "ugz", "nxx", "nyy", "nxy"]
    for c in numeric_cols:
        if c not in df.columns:
            df[c] = 0.0
            continue
        ser = df[c]
        if not pd.api.types.is_numeric_dtype(ser):
            ser = ser.astype(str).str.strip().str.replace(",", ".", regex=False)
        df[c] = pd.to_numeric(ser, errors="coerce").fillna(0.0)

    return df

def reduce_to_governing_cases(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    work = df.copy()
    moment_cols = [c for c in ["mxx", "myy", "mxy", "mxx_wa_pos", "mxx_wa_neg", "myy_wa_pos", "myy_wa_neg"] if c in work.columns]
    if moment_cols:
        work["_mmax"] = work[moment_cols].abs().max(axis=1)
    else:
        work["_mmax"] = 0.0
    work["_qmax"] = work[[c for c in ["qxx", "qyy"] if c in work.columns]].abs().max(axis=1) if any(c in work.columns for c in ["qxx", "qyy"]) else 0.0
    work["_umax"] = work["ugz"].abs() if "ugz" in work.columns else 0.0
    work["_score"] = work["_mmax"] + 0.15 * work["_qmax"] + 0.01 * work["_umax"]
    idx = set()
    for _, grp in work.groupby(["panel"], dropna=False):
        if grp.empty:
            continue
        idx.add(grp["_score"].idxmax())
        for c in moment_cols:
            if grp[c].abs().max() > 0:
                idx.add(grp[c].abs().idxmax())
        for c in ["qxx", "qyy"]:
            if c in grp.columns and grp[c].abs().max() > 0:
                idx.add(grp[c].abs().idxmax())
        if "ugz" in grp.columns and grp["ugz"].abs().max() > 0:
            idx.add(grp["ugz"].abs().idxmax())
            idx.add(grp["ugz"].idxmin())
    out = work.loc[sorted(idx)].copy().sort_values(["panel", "case", "node", "__row_order"])
    return out.drop(columns=["_mmax", "_qmax", "_umax", "_score"], errors="ignore").reset_index(drop=True)
