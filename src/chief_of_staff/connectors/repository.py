"""Read approved Markdown files from one explicitly bounded repository."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from chief_of_staff.connectors.contracts import (
    ConnectorRequest,
    ConnectorResult,
    SourceCoverage,
    SourceItem,
)
from chief_of_staff.domain import CoverageStatus

MAX_APPROVED_FILES: Final = 32
MAX_FILE_BYTES: Final = 256 * 1024
MAX_SUMMARY_CHARACTERS: Final = 280


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class _ApprovedFile:
    path: Path
    relative_path: Path


@dataclass(frozen=True, slots=True)
class RepositoryContextConnector:
    """Retrieve bounded context from exact, pre-approved local Markdown files."""

    root: Path
    approved_paths: tuple[Path, ...]
    clock: Callable[[], datetime] = field(
        default=_utc_now,
        repr=False,
        compare=False,
    )
    source_name: str = field(default="repository_context", init=False)
    approved_scope: str = field(init=False)
    _approved_files: tuple[_ApprovedFile, ...] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        try:
            resolved_root = self.root.resolve(strict=True)
        except OSError:
            raise ValueError("repository root must exist") from None
        if not resolved_root.is_dir():
            raise ValueError("repository root must be a directory")
        if not self.approved_paths:
            raise ValueError("at least one repository file must be approved")
        if len(self.approved_paths) > MAX_APPROVED_FILES:
            raise ValueError(
                f"no more than {MAX_APPROVED_FILES} repository files may be approved"
            )

        approved: list[_ApprovedFile] = []
        seen: set[Path] = set()
        for configured_path in self.approved_paths:
            candidate = (
                configured_path
                if configured_path.is_absolute()
                else resolved_root / configured_path
            )
            try:
                resolved_path = candidate.resolve(strict=True)
            except OSError:
                raise ValueError("approved repository files must exist") from None
            try:
                relative_path = resolved_path.relative_to(resolved_root)
            except ValueError:
                raise ValueError(
                    "approved repository files must remain inside the root"
                ) from None
            if any(part.startswith(".") for part in relative_path.parts):
                raise ValueError("hidden repository paths may not be approved")
            if resolved_path.suffix.casefold() != ".md":
                raise ValueError("approved repository files must be Markdown")
            if not resolved_path.is_file():
                raise ValueError("approved repository paths must identify files")
            if resolved_path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(
                    f"approved repository files may not exceed {MAX_FILE_BYTES} bytes"
                )
            if relative_path in seen:
                raise ValueError("approved repository files must be unique")
            seen.add(relative_path)
            approved.append(
                _ApprovedFile(
                    path=resolved_path,
                    relative_path=relative_path,
                )
            )

        approved.sort(key=lambda item: item.relative_path.as_posix())
        relative_names = tuple(item.relative_path.as_posix() for item in approved)
        object.__setattr__(self, "root", resolved_root)
        object.__setattr__(
            self,
            "approved_paths",
            tuple(item.relative_path for item in approved),
        )
        object.__setattr__(self, "_approved_files", tuple(approved))
        object.__setattr__(
            self,
            "approved_scope",
            f"exact repository files: {', '.join(relative_names)}",
        )

    def retrieve(self, request: ConnectorRequest) -> ConnectorResult:
        """Read only the approved files and return minimal contextual facts."""

        if request.approved_scope != self.approved_scope:
            raise ValueError("request scope does not match connector scope")

        retrieved_at = self.clock()
        if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
            raise ValueError("connector clock must return a timezone-aware value")

        items: list[SourceItem] = []
        freshness_values: list[datetime] = []
        warnings: list[str] = []
        for approved_file in self._approved_files:
            relative_name = approved_file.relative_path.as_posix()
            try:
                if approved_file.path.resolve(strict=True) != approved_file.path:
                    raise ValueError("approved file target changed")
                stat = approved_file.path.stat()
                if stat.st_size > MAX_FILE_BYTES:
                    raise ValueError("file now exceeds the approved size limit")
                with approved_file.path.open("rb") as source:
                    raw_content = source.read(MAX_FILE_BYTES + 1)
                if len(raw_content) > MAX_FILE_BYTES:
                    raise ValueError("file now exceeds the approved size limit")
                content = raw_content.decode("utf-8")
                title, summary = _extract_context(content, approved_file.relative_path)
            except OSError, UnicodeError, ValueError:
                warnings.append(f"{relative_name} could not be read safely")
                continue

            freshness_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
            freshness_values.append(freshness_at)
            items.append(
                SourceItem(
                    id=f"repository:{relative_name}",
                    source_record_id=relative_name,
                    item_type="context",
                    facts={
                        "title": title,
                        "summary": summary,
                    },
                    retrieved_at=retrieved_at,
                    freshness_at=freshness_at,
                    display_url=f"repository://{relative_name}",
                )
            )

        status = (
            CoverageStatus.COMPLETE
            if not warnings
            else (CoverageStatus.PARTIAL if items else CoverageStatus.UNAVAILABLE)
        )
        return ConnectorResult(
            items=tuple(items),
            coverage=SourceCoverage(
                source=self.source_name,
                approved_scope=self.approved_scope,
                status=status,
                retrieved_at=retrieved_at,
                record_count=len(items),
                freshness_at=max(freshness_values) if freshness_values else None,
                warnings=tuple(warnings),
                error_category=(None if not warnings else "RepositoryFileUnavailable"),
            ),
        )


def _extract_context(content: str, relative_path: Path) -> tuple[str, str | None]:
    lines = content.splitlines()
    title = next(
        (
            line.removeprefix("# ").strip()
            for line in lines
            if line.startswith("# ") and line.removeprefix("# ").strip()
        ),
        relative_path.stem.replace("-", " ").title(),
    )

    paragraph_lines: list[str] = []
    in_code_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_fence = not in_code_fence
            continue
        if in_code_fence:
            continue
        if not stripped:
            if paragraph_lines:
                break
            continue
        if (
            stripped.startswith("#")
            or stripped.startswith("- **")
            or stripped.startswith("|")
        ):
            continue
        paragraph_lines.append(stripped)

    if not paragraph_lines:
        return title, None
    summary = " ".join(paragraph_lines)
    if len(summary) > MAX_SUMMARY_CHARACTERS:
        summary = summary[: MAX_SUMMARY_CHARACTERS - 1].rstrip() + "…"
    return title, summary
