"""Validate repository-local Markdown links and heading anchors."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
    }
)

HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")
INLINE_LINK_PATTERN = re.compile(r"!?\[[^\]]*]\(([^)]+)\)")
MARKUP_PATTERN = re.compile(r"[`*_~]")
HTML_PATTERN = re.compile(r"<[^>]*>")
PUNCTUATION_PATTERN = re.compile(r"[^\w\s-]", flags=re.UNICODE)


def markdown_files() -> tuple[Path, ...]:
    """Return repository Markdown files outside ignored tool directories."""

    files = (
        path
        for path in ROOT.rglob("*.md")
        if not EXCLUDED_DIRECTORIES.intersection(path.relative_to(ROOT).parts)
    )
    return tuple(sorted(files))


def heading_anchors(path: Path) -> frozenset[str]:
    """Approximate GitHub heading slugs, including duplicate suffixes."""

    seen: defaultdict[str, int] = defaultdict(int)
    anchors: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = HEADING_PATTERN.match(line)
        if match is None:
            continue

        heading = HTML_PATTERN.sub("", match.group(1))
        heading = MARKUP_PATTERN.sub("", heading).lower()
        base = PUNCTUATION_PATTERN.sub("", heading).strip().replace(" ", "-")
        duplicate_index = seen[base]
        seen[base] += 1
        anchors.add(base if duplicate_index == 0 else f"{base}-{duplicate_index}")
    return frozenset(anchors)


def validate() -> tuple[str, ...]:
    """Return all missing local targets and anchors."""

    errors: list[str] = []
    anchor_cache: dict[Path, frozenset[str]] = {}
    for markdown_path in markdown_files():
        for line_number, line in enumerate(
            markdown_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            for match in INLINE_LINK_PATTERN.finditer(line):
                raw_target = match.group(1).strip().removeprefix("<").removesuffix(">")
                raw_target = raw_target.split(' "', maxsplit=1)[0]
                parsed = urlsplit(raw_target)
                if parsed.scheme or raw_target.startswith("//"):
                    continue

                target_path = (
                    markdown_path
                    if not parsed.path
                    else (markdown_path.parent / unquote(parsed.path)).resolve()
                )
                if not target_path.exists():
                    relative_source = markdown_path.relative_to(ROOT)
                    errors.append(
                        f"{relative_source}:{line_number}: missing {raw_target}"
                    )
                    continue

                if parsed.fragment and target_path.is_file():
                    anchors = anchor_cache.setdefault(
                        target_path,
                        heading_anchors(target_path),
                    )
                    fragment = unquote(parsed.fragment).lower()
                    if fragment not in anchors:
                        relative_source = markdown_path.relative_to(ROOT)
                        errors.append(
                            f"{relative_source}:{line_number}: "
                            f"missing anchor {raw_target}"
                        )
    return tuple(errors)


def main() -> int:
    """Run validation and return a shell-compatible status."""

    errors = validate()
    if errors:
        print("\n".join(errors))
        return 1

    print(
        f"Validated {len(markdown_files())} Markdown files; "
        "all local links and anchors resolve."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
