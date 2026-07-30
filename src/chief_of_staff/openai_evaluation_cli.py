"""Private setup and execution entry point for the bounded OpenAI evaluation."""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Protocol, Self

from chief_of_staff.auth import KeychainSecretReference, MacOSKeychain
from chief_of_staff.inference.live_evaluation import (
    APPROVED_PROJECT_NAME,
    LIVE_CALL_CAP,
    TRIAL_COST_CAP_MICROUSD,
    LiveComparisonReport,
    run_live_comparison,
    write_private_report,
)
from chief_of_staff.inference.providers.openai import (
    OPENAI_API_KEY_REFERENCE,
    OpenAIRetentionStatus,
)

DEFAULT_PRIVATE_ROOT: Final = Path(".local/inference")
DEFAULT_CONFIGURATION_PATH: Final = (
    DEFAULT_PRIVATE_ROOT / "m8-provider-configuration.json"
)
DEFAULT_AUDIT_DATABASE_PATH: Final = DEFAULT_PRIVATE_ROOT / "m8-audits.sqlite3"
DEFAULT_REPORT_PATH: Final = (
    DEFAULT_PRIVATE_ROOT / "milestone-8-live-comparison-2026-07-29.json"
)
EXECUTION_CONFIRMATION: Final = "execute-bounded-synthetic-trial"


class KeychainWriter(Protocol):
    """Narrow Keychain behavior required by clipboard import."""

    def store(self, reference: KeychainSecretReference, secret: str) -> None:
        """Store one secret without displaying it."""

    def exists(self, reference: KeychainSecretReference) -> bool:
        """Return whether the exact item exists."""


@dataclass(frozen=True, slots=True)
class PrivateProviderConfiguration:
    """Ignored non-secret provider metadata, including private identifiers."""

    project_name: str
    organization_id: str
    project_id: str
    organization_ownership: str
    project_ownership: str
    billing_availability: str
    billing_source: str
    retention_status: str
    model_access: list[str]
    api_access: str
    service_account_name: str
    provider_policy_review_owner: str
    spend_control: str
    configured_at: str

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load and validate the mode-0600 private provider configuration."""

        if not path.is_file():
            raise RuntimeError("private provider configuration is unavailable")
        if path.stat().st_mode & 0o077:
            raise RuntimeError("private provider configuration must use mode 0600")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError("private provider configuration is invalid")
        try:
            configuration = cls(**value)
        except TypeError:
            raise RuntimeError("private provider configuration is incomplete") from None
        configuration.validate()
        return configuration

    def validate(self) -> None:
        """Fail closed on a different project, owner, billing, or review boundary."""

        if self.project_name != APPROVED_PROJECT_NAME:
            raise RuntimeError("the configured project is outside the approved trial")
        if not self.organization_id.strip() or not self.project_id.strip():
            raise RuntimeError("explicit organization and project IDs are required")
        if self.organization_ownership != "northridge_controlled":
            raise RuntimeError("organization ownership is not approved")
        if self.project_ownership != "Brad":
            raise RuntimeError("Brad must own the evaluation project")
        if self.provider_policy_review_owner != "Brad":
            raise RuntimeError("Brad must own provider-policy review")
        if self.billing_availability != "active_existing":
            raise RuntimeError("existing API billing is not confirmed")
        if self.model_access != [
            "gpt-5.6-terra",
            "gpt-5.6-luna",
        ]:
            raise RuntimeError("provider model access exceeds the approved comparison")
        if self.api_access != "responses_only":
            raise RuntimeError("provider API access exceeds the approved endpoint")
        if self.service_account_name != "chief-of-staff-local":
            raise RuntimeError("the configured service account is not approved")
        if self.spend_control not in {"alert", "hard_limit"}:
            raise RuntimeError("project spend control is not recorded")
        try:
            OpenAIRetentionStatus(self.retention_status)
        except ValueError:
            raise RuntimeError("provider retention status is invalid") from None


def store_key_from_clipboard(
    *,
    keychain: KeychainWriter | None = None,
    read_clipboard: Callable[[], str] | None = None,
    clear_clipboard: Callable[[], None] | None = None,
) -> None:
    """Move one copied project key into Keychain and clear the clipboard."""

    selected_keychain = keychain or MacOSKeychain()
    reader = read_clipboard or _read_system_clipboard
    clearer = clear_clipboard or _clear_system_clipboard
    secret = ""
    try:
        secret = reader().strip()
        if len(secret) < 20 or any(character.isspace() for character in secret):
            raise RuntimeError("clipboard does not contain one plausible API key")
        selected_keychain.store(OPENAI_API_KEY_REFERENCE, secret)
    finally:
        clearer()
        secret = ""
    if not selected_keychain.exists(OPENAI_API_KEY_REFERENCE):
        raise RuntimeError("the approved Keychain item is unavailable after storage")


def comparison_passed(report: LiveComparisonReport) -> bool:
    """Return whether the bounded live gate completed without trust violations."""

    metrics = tuple(evaluation.metrics for evaluation in report.evaluations)
    policy_rejections_fail_closed = all(
        evaluation.metrics.policy_failures
        == sum(
            scenario.validation_status == "policy_rejected"
            and scenario.reduced_mode_reason == "provider_policy_rejected"
            for scenario in evaluation.scenarios
        )
        for evaluation in report.evaluations
    )
    return (
        sum(item.attempted_calls for item in metrics) == LIVE_CALL_CAP
        and all(item.completed_calls == 10 for item in metrics)
        and all(item.provider_failures == 0 for item in metrics)
        and all(item.false_positives == 0 for item in metrics)
        and all(item.schema_failures == 0 for item in metrics)
        and all(item.provenance_failures == 0 for item in metrics)
        and policy_rejections_fail_closed
        and all(item.cache_write_tokens == 0 for item in metrics)
        and all(item.cached_input_tokens == 0 for item in metrics)
        and all(item.correction_regressions == 0 for item in metrics)
        and report.conservative_trial_cost_microusd <= TRIAL_COST_CAP_MICROUSD
        and not report.production_model_selected
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the approved synthetic-only Milestone 8 comparison."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "credential-health",
        help="Check only whether the approved Keychain item exists.",
    )
    subparsers.add_parser(
        "store-key-from-clipboard",
        help="Move a copied project key into Keychain and clear the clipboard.",
    )
    run = subparsers.add_parser(
        "run",
        help="Execute the bounded twenty-call synthetic comparison.",
    )
    run.add_argument(
        "--confirmation",
        required=True,
        choices=(EXECUTION_CONFIRMATION,),
    )
    run.add_argument(
        "--configuration",
        type=Path,
        default=DEFAULT_CONFIGURATION_PATH,
    )
    run.add_argument(
        "--audit-database",
        type=Path,
        default=DEFAULT_AUDIT_DATABASE_PATH,
    )
    run.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one safe command without printing private identifiers or secrets."""

    arguments = _parser().parse_args(argv)
    keychain = MacOSKeychain()
    if arguments.command == "credential-health":
        healthy = keychain.exists(OPENAI_API_KEY_REFERENCE)
        print(json.dumps({"credential_healthy": healthy}))
        return 0 if healthy else 1
    if arguments.command == "store-key-from-clipboard":
        store_key_from_clipboard(keychain=keychain)
        print(json.dumps({"credential_healthy": True, "clipboard_cleared": True}))
        return 0

    configuration = PrivateProviderConfiguration.load(arguments.configuration)
    if not keychain.exists(OPENAI_API_KEY_REFERENCE):
        raise RuntimeError("the approved Keychain credential is unavailable")
    report = run_live_comparison(
        organization_id=configuration.organization_id,
        project_id=configuration.project_id,
        retention_status=OpenAIRetentionStatus(configuration.retention_status),
        audit_database_path=arguments.audit_database,
        keychain=keychain,
    )
    write_private_report(report, arguments.report)
    summary = {
        "report": str(arguments.report),
        "audit_database": str(arguments.audit_database),
        "calls_attempted": sum(
            evaluation.metrics.attempted_calls for evaluation in report.evaluations
        ),
        "models": [asdict(evaluation.metrics) for evaluation in report.evaluations],
        "comparison_passed": comparison_passed(report),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if comparison_passed(report) else 1


def _read_system_clipboard() -> str:
    completed = subprocess.run(
        ("/usr/bin/pbpaste",),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise RuntimeError("macOS clipboard could not be read")
    return completed.stdout


def _clear_system_clipboard() -> None:
    completed = subprocess.run(
        ("/usr/bin/pbcopy",),
        check=False,
        input="",
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if completed.returncode != 0:
        raise RuntimeError("macOS clipboard could not be cleared")


if __name__ == "__main__":
    raise SystemExit(main())
