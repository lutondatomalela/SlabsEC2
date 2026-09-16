"""Recursos e diagnóstico do arranque, sem dependência da pasta de trabalho."""
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import tempfile


def asset_path(name):
    return Path(__file__).resolve().parent / "assets" / name


def configure_runtime():
    # pythonw/PyInstaller --windowed não disponibilizam os fluxos da consola.
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    logger = logging.getLogger("SlabsEC2")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "state")
    for folder in (base / "SlabsEC2" / "logs", Path(tempfile.gettempdir()) / "SlabsEC2-logs"):
        try:
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / "SlabsEC2.log"
            if not logger.handlers:
                handler = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=2, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
                logger.addHandler(handler)
            return logger, path
        except OSError:
            continue
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())
    return logger, "indisponível (sem permissão de escrita)"


def apply_window_icon(window):
    import tkinter as tk
    png = asset_path("slabsec2.png")
    if png.is_file():
        window._app_icon = tk.PhotoImage(file=str(png))
        window.iconphoto(True, window._app_icon)
    ico = asset_path("slabsec2.ico")
    if sys.platform == "win32" and ico.is_file():
        window.iconbitmap(str(ico))


def show_unhandled_error(logger, log_path, details, parent=None):
    logger.error("Erro não tratado na interface", exc_info=details)
    message = ("Não foi possível concluir a operação.\n\n"
               "O detalhe técnico foi registado em:\n" + str(log_path))
    try:
        from tkinter import messagebox
        messagebox.showerror("SlabsEC2 — erro", message, parent=parent)
    except Exception:
        if sys.platform == "win32":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "SlabsEC2", 0x10)
