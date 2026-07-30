"""Generate private Milestone 9 synthetic evaluation artifacts."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path

from chief_of_staff.pipeline.evaluation import run_synthetic_ranking_evaluation

DEFAULT_OUTPUT_DIRECTORY = Path(".local/milestone-9/review")
REPRESENTATIVE_SCENARIOS = (
    "normal-full-workday",
    "meeting-heavy-day",
    "accepted-contextual-inference",
    "conflicting-source-dates",
    "non-workday-with-fixed-commitment",
)


def main() -> int:
    """Write mode-0600 aggregate and representative synthetic artifacts."""

    report, outputs = run_synthetic_ranking_evaluation()
    output_directory = DEFAULT_OUTPUT_DIRECTORY
    output_directory.mkdir(parents=True, exist_ok=True)
    output_directory.chmod(0o700)

    report_path = output_directory / "aggregate-evaluation.json"
    _write_private(
        report_path,
        json.dumps(asdict(report), indent=2, sort_keys=True) + "\n",
    )
    output_by_name = dict(outputs)
    for name in REPRESENTATIVE_SCENARIOS:
        result = output_by_name[name]
        _write_private(
            output_directory / f"{name}.md",
            result.rendered.text,
        )
    summary_path = output_directory / "README.md"
    summary_lines = [
        "# Milestone 9 Synthetic Review",
        "",
        f"- Scenarios: {report.scenario_count}",
        f"- Passed: {report.passed_count}",
        f"- Failed: {report.failed_count}",
        f"- Unsupported claims: {report.unsupported_claims}",
        (
            "- False-positive actionable recommendations: "
            f"{report.false_positive_actionable_recommendations}"
        ),
        "- Provider calls: 0",
        "- Live connector calls: 0",
        "- External writes: 0",
        "",
        "Representative briefings:",
        "",
        *[f"- `{name}.md`" for name in REPRESENTATIVE_SCENARIOS],
        "",
        "Brad's review remains the Milestone 9 acceptance gate.",
        "",
    ]
    _write_private(summary_path, "\n".join(summary_lines))
    print(
        json.dumps(
            {
                "artifact_directory": str(output_directory),
                "passed": report.passed,
                "scenario_count": report.scenario_count,
            },
            sort_keys=True,
        )
    )
    return 0 if report.passed else 1


def _write_private(path: Path, content: str) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
    finally:
        path.chmod(0o600)


if __name__ == "__main__":
    raise SystemExit(main())
