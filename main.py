# -*- coding: utf-8 -*-
import sys
from slabsec2.gui import SlabsEC2App
from slabsec2.selftest import run_core_regression_tests
from slabsec2.validation import run_engineering_validation_suite
from slabsec2.manual_validation import run_manual_reference_validation
from slabsec2.audit_v2153 import run_audit

if __name__ == "__main__":
    if "--self-test" in sys.argv:
        print(run_core_regression_tests())
    elif "--validation-suite" in sys.argv:
        print(run_engineering_validation_suite())
    elif "--manual-validation" in sys.argv:
        print(run_manual_reference_validation())
    elif "--audit" in sys.argv or "--audit-v2153" in sys.argv or "--audit-v2151" in sys.argv or "--audit-v215" in sys.argv:
        print(run_audit())
    else:
        app = SlabsEC2App()
        app.mainloop()
