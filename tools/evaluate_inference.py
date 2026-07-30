"""Run the privacy-safe mocked Milestone 8 inference evaluation."""

from __future__ import annotations

import json
from dataclasses import asdict

from chief_of_staff.inference.evaluation import run_synthetic_inference_evaluation


def main() -> int:
    """Print aggregate non-content metrics and return the gate status."""

    report = run_synthetic_inference_evaluation()
    print(json.dumps(asdict(report), indent=2, sort_keys=True))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
