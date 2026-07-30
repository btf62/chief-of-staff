"""Conservative exact-duplicate handling that preserves conflicts."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from chief_of_staff.connectors import connector_instance_key
from chief_of_staff.pipeline.normalization import (
    NormalizedRecord,
    record_completion_state,
    record_priority_fact,
    record_status_fact,
)


@dataclass(frozen=True, slots=True)
class RecordCluster:
    """Traceable group of records sharing one authoritative source identity."""

    source: str
    source_record_id: str
    member_ids: tuple[str, ...]
    connector_instance_id: str | None = None


@dataclass(frozen=True, slots=True)
class CrossSourceAssociation:
    """Non-destructive relationship supported by an explicit source reference."""

    member_ids: tuple[str, str]
    basis: str
    conflicting_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Records plus explicit duplicate and conflict decisions."""

    records: tuple[NormalizedRecord, ...]
    exact_duplicates: tuple[RecordCluster, ...]
    conflicts: tuple[RecordCluster, ...]
    associations: tuple[CrossSourceAssociation, ...]


def deduplicate_records(
    records: tuple[NormalizedRecord, ...],
) -> DeduplicationResult:
    """Collapse only semantically identical records from the same source ID."""

    grouped: defaultdict[tuple[str, str, str], list[NormalizedRecord]] = defaultdict(
        list
    )
    for record in records:
        source_key = connector_instance_key(
            source=record.provenance.source,
            connector_instance_id=record.provenance.connector_instance_id,
        )
        key = (*source_key, record.provenance.source_record_id)
        grouped[key].append(record)

    retained: list[NormalizedRecord] = []
    duplicates: list[RecordCluster] = []
    conflicts: list[RecordCluster] = []
    for (source, instance_key, source_record_id), group in grouped.items():
        if len(group) == 1:
            retained.extend(group)
            continue

        cluster = RecordCluster(
            source=source,
            source_record_id=source_record_id,
            member_ids=tuple(record.id for record in group),
            connector_instance_id=(None if instance_key == source else instance_key),
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
    retained_records = tuple(retained)
    return DeduplicationResult(
        records=retained_records,
        exact_duplicates=tuple(duplicates),
        conflicts=tuple(conflicts),
        associations=_cross_source_associations(retained_records),
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
        record.provider_priority,
        record.explicit_priority_link,
        record.calendar_dependency,
        record.effort_minutes,
        record.source_priority,
        record.project_reference,
        record.issue_type,
        record.status_category,
        record.assignee_reference,
        record.parent_reference,
        record.labels,
        record.dependency_references,
        record.dependency_relationships,
        record.dependency_display_urls,
        record.membership_references,
        record.dependent_references,
        record.related_source_ids,
        record.blocked,
        record.source_owned_risk,
        record.source_created_at,
        record.source_updated_at,
        record.hard_deadline,
        record.primary_stewardship,
        record.relationship_consequence,
        record.six_month_goal,
        record.seasonal_initiative,
        record.delegation_opportunity,
        record.energy_requirement,
        record.opportunity_cost,
        record.uncertainty,
        record.inference_explanation,
        record.evidence_fingerprint,
        record.associated_provenance,
        record.associated_source_facts,
        record.association_conflicts,
    )


def _freshness_key(record: NormalizedRecord) -> tuple[datetime, datetime]:
    return (
        record.provenance.freshness_at or record.provenance.retrieved_at,
        record.provenance.retrieved_at,
    )


def _cross_source_associations(
    records: tuple[NormalizedRecord, ...],
) -> tuple[CrossSourceAssociation, ...]:
    by_id = {record.id: record for record in records}
    associations: dict[tuple[str, str], CrossSourceAssociation] = {}
    for record in records:
        for related_id in record.related_source_ids:
            related = by_id.get(related_id)
            if related is None or _same_connector_instance(record, related):
                continue
            first_id, second_id = sorted((record.id, related.id))
            pair = (first_id, second_id)
            associations[pair] = CrossSourceAssociation(
                member_ids=pair,
                basis="explicit cross-source reference",
                conflicting_fields=_conflicting_fields(record, related),
            )
    return tuple(associations[key] for key in sorted(associations))


def _same_connector_instance(
    first: NormalizedRecord,
    second: NormalizedRecord,
) -> bool:
    return connector_instance_key(
        source=first.provenance.source,
        connector_instance_id=first.provenance.connector_instance_id,
    ) == connector_instance_key(
        source=second.provenance.source,
        connector_instance_id=second.provenance.connector_instance_id,
    )


def _conflicting_fields(
    first: NormalizedRecord,
    second: NormalizedRecord,
) -> tuple[str, ...]:
    comparisons = (
        ("title", first.title, second.title),
        ("status", record_status_fact(first), record_status_fact(second)),
        ("due_at", first.due_at, second.due_at),
        ("owner", first.assignee_reference, second.assignee_reference),
        ("priority", record_priority_fact(first), record_priority_fact(second)),
        (
            "completion",
            record_completion_state(first),
            record_completion_state(second),
        ),
    )
    return tuple(
        field
        for field, first_value, second_value in comparisons
        if first_value is not None
        and second_value is not None
        and first_value != second_value
    )
