"""Row-major XLSX writing with bounded writer memory and atomic replacement."""
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

import pandas as pd
import xlsxwriter

DATA_ROWS_PER_SHEET = 1_048_575


def write_workbook(path, sheets, progress=None, properties=None):
    """Preserve every supplied row/column; never use pandas column-major streaming."""
    path = Path(path)
    total = sum(max(len(df), 1) if isinstance(df, pd.DataFrame) else 1 for _, df in sheets)
    done = 0
    with NamedTemporaryFile(dir=path.parent, suffix='.xlsx', delete=False) as tmp:
        temporary = tmp.name
    try:
        with xlsxwriter.Workbook(temporary, {
            'constant_memory': True, 'strings_to_urls': False,
            'strings_to_formulas': False, 'nan_inf_to_errors': True,
        }) as book:
            book.set_properties(properties or {})
            header = book.add_format({'bold': True, 'font_color': 'white',
                                      'bg_color': '#1F4E78', 'text_wrap': True})
            numeric = book.add_format({'num_format': '0.000', 'valign': 'top'})
            text = book.add_format({'valign': 'top'})
            for name, df in sheets:
                if not isinstance(df, pd.DataFrame) or df.empty:
                    df = pd.DataFrame({'Nota': ['Sem dados disponíveis.']})
                for part, start in enumerate(range(0, len(df), DATA_ROWS_PER_SHEET), 1):
                    title = str(name) if len(df) <= DATA_ROWS_PER_SHEET else f'{name[:27]}_{part}'
                    title = ''.join('_' if ch in '[]:*?/\\' else ch for ch in title)[:31]
                    ws = book.add_worksheet(title)
                    ws.freeze_panes(1, 0)
                    ws.hide_gridlines(2)
                    ws.set_row(0, 30)
                    ws.write_row(0, 0, [str(c) for c in df.columns], header)
                    for col, label in enumerate(df.columns):
                        ws.set_column(col, col, min(max(len(str(label)) + 2, 12), 40))
                    chunk = df.iloc[start:start + DATA_ROWS_PER_SHEET]
                    if progress:
                        progress(done, total, title)
                    for rownum, row in enumerate(chunk.itertuples(index=False, name=None), 1):
                        for col, value in enumerate(row):
                            if value is None or pd.isna(value):
                                continue
                            if isinstance(value, str):
                                ws.write_string(rownum, col, value, text)
                            else:
                                ws.write(rownum, col, value, numeric)
                        done += 1
                        if progress and rownum % 2000 == 0:
                            progress(done, total, title)
                    ws.autofilter(0, 0, len(chunk), len(df.columns) - 1)
            if progress:
                progress(total, total, 'A finalizar e comprimir o ficheiro')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
