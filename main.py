# -*- coding: utf-8 -*-
"""Arranque da interface e verificações em Python ou no executável."""
import argparse
import multiprocessing
import sys
from pathlib import Path

from slabsec2.runtime import configure_runtime, show_unhandled_error
from slabsec2.version import APP_VERSION


def main(argv=None):
    logger, log_path = configure_runtime()
    parser = argparse.ArgumentParser(description="SlabsEC2 — lajes maciças de betão armado")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--self-test", action="store_true")
    action.add_argument("--validation-suite", action="store_true")
    action.add_argument("--manual-validation", action="store_true")
    action.add_argument("--audit", "--audit-v2153", "--audit-v2151", "--audit-v215", action="store_true")
    action.add_argument("--installation-check", action="store_true", help="Verificar interface, importação e exportação com dados sintéticos")
    action.add_argument("--version", action="store_true")
    parser.add_argument("--output", type=Path, help="Guardar o resultado de uma verificação em UTF-8")
    args = parser.parse_args(argv)
    diagnostic = any((args.self_test, args.validation_suite, args.manual_validation,
                      args.audit, args.installation_check, args.version))
    if args.output and not diagnostic:
        parser.error("--output requer uma opção de verificação ou --version")
    try:
        if args.self_test:
            from slabsec2.selftest import run_core_regression_tests
            result = run_core_regression_tests()
        elif args.validation_suite:
            from slabsec2.validation import run_engineering_validation_suite
            result = run_engineering_validation_suite()
        elif args.manual_validation:
            from slabsec2.manual_validation import run_manual_reference_validation
            result = run_manual_reference_validation()
        elif args.audit:
            from slabsec2.audit_v2153 import run_audit
            result = run_audit()
        elif args.installation_check:
            from slabsec2.installation_check import run_installation_check
            result = run_installation_check()
        elif args.version:
            result = APP_VERSION
        else:
            from slabsec2.gui import SlabsEC2App
            app = SlabsEC2App()
            app.report_callback_exception = lambda exc, value, tb: show_unhandled_error(
                logger, log_path, (exc, value, tb), parent=app)
            app.mainloop()
            return 0
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(result + "\n", encoding="utf-8")
        print(result)
        return 0
    except Exception:
        details = sys.exc_info()
        logger.error("Falha durante a execução", exc_info=details)
        if diagnostic:
            if args.output:
                try:
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(f"FALHOU: {details[1]}\nRegisto: {log_path}\n", encoding="utf-8")
                except OSError:
                    pass
            print(f"FALHOU: {details[1]}", file=sys.stderr)
        else:
            show_unhandled_error(logger, log_path, details)
        return 1


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
