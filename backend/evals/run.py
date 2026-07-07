#!/usr/bin/env python3
"""Run quality evaluation suite: python -m evals.run"""

import json
import sys

sys.path.insert(0, ".")

from app.services.eval_suite import run_eval_suite


def main():
    result = run_eval_suite()
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
