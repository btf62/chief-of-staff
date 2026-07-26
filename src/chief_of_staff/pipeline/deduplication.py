"""Conservative exact-duplicate handling that preserves conflicts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from chief_of_staff.pipeline.normalization import NormalizedRecord


@dataclass(frozen=True, slots=True)
class RecordCluster:
    """Traceable group of records sharing one authoritative source identity."""

    source: str
    source_record_id: str
    member_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Records plus explicit duplicate and conflict decisions."""

    records: tuple[NormalizedRecord, ...]
    exact_duplicates: tuple[RecordCluster, ...]
    conflicts: tuple[RecordCluster, ...]


def deduplicate_records(
    records: tuple[NormalizedRecord, ...],
) -> DeduplicationResult:
    """Collapse only semantically identical records from the same source ID."""

    grouped: defaultdict[tuple[str, str], list[NormalizedRecord]] = defaultdict(list)
    for record in records:
        key = (record.provenance.source, record.provenance.source_record_id)
        grouped[key].append(record)

    retained: list[NormalizedRecord] = []
    duplicates: list[RecordCluster] = []
    conflicts: list[RecordCluster] = []
    for (source, source_record_id), group in grouped.items():
        if len(group) == 1:
            retained.extend(group)
            continue

        cluster = RecordCluster(
            source=source,
            source_record_id=source_record_id,
            member_ids=tuple(record.id for record in group),
        )
        signatures = {_semantic_signature(record) for record in group}
        if len(signatures) == 1:
            newest = max(group, key=_freshness_key)
            retained.append(newest)
            duplicates.append(cluster)
        else:
            retained.extend(group)
            conflicts.append(cluster)

    retained.sort(key=lambda record: record.id)
    return DeduplicationResult(
        records=tuple(retained),
        exact_duplicates=tuple(duplicates),
        conflicts=tuple(conflicts),
    )


def _semantic_signature(record: NormalizedRecord) -> tuple[object, ...]:
    return (
        record.kind,
        record.title,
        record.summary,
        record.status,
        record.importance,
        record.explicit_commitment,
        record.preparation,
        record.all_day,
        record.start_at,
        record.end_at,
        record.due_at,
    )


def _freshness_key(record: NormalizedRecord) -> tuple[datetime, datetime]:
    return (
        record.provenance.freshness_at or record.provenance.retrieved_at,
        record.provenance.retrieved_at,
    )
