"""Minimized Daily Briefing archive and historical lineage support."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from chief_of_staff.connectors import SourceCoverage
from chief_of_staff.domain import (
    BriefingArchivedFact,
    BriefingPresentationState,
    BriefingRun,
    BriefingStatus,
    ConnectorDomain,
    ConnectorRun,
    ConnectorStatus,
    CoverageStatus,
)
from chief_of_staff.persistence import StateStore
from chief_of_staff.pipeline import (
    AssociatedSourceFacts,
    DeduplicationResult,
    HistoricalMode,
    NormalizedRecord,
    PipelineResult,
    Provenance,
    RecordKind,
    build_reduced_plan,
    render_briefing,
    resolve_context,
    validate_briefing,
)
from chief_of_staff.web import presentation_from_plan

ARCHIVE_SCHEMA_VERSION = 1
PROCESSING_VERSIONS = {
    "archive_schema": ARCHIVE_SCHEMA_VERSION,
    "briefing_rules": "milestone-11+calendar-self-response-v1",
    "ranking_rules": "milestone-9",
}


@dataclass(frozen=True, slots=True)
class HistoricalGeneration:
    """One generated historical result and its explicit lineage."""

    run_id: str | None
    result: PipelineResult | None
    mode: HistoricalMode
    originating_recorded_run_id: str | None
    disclosure: str


def archive_pipeline_facts(
    state_store: StateStore,
    *,
    briefing_run_id: str,
    result: PipelineResult,
) -> None:
    """Archive normalized facts only after the successful run exists."""

    facts = tuple(
        BriefingArchivedFact(
            briefing_run_id=briefing_run_id,
            ordinal=ordinal,
            source=record.provenance.source,
            source_record_id=record.provenance.source_record_id,
            normalized_fact_json=serialize_normalized_record(record),
        )
        for ordinal, record in enumerate(result.deduplication.records)
    )
    state_store.save_briefing_archived_facts(briefing_run_id, facts)


def serialize_normalized_record(record: NormalizedRecord) -> str:
    """Serialize one normalized fact without provider payloads or credentials."""

    payload = {
        "archive_schema_version": ARCHIVE_SCHEMA_VERSION,
        "record": asdict(record),
    }
    return json.dumps(
        payload,
        default=_json_default,
        separators=(",", ":"),
        sort_keys=True,
    )


def deserialize_normalized_record(value: str) -> NormalizedRecord:
    """Load one schema-versioned normalized fact for replay."""

    payload = json.loads(value)
    if (
        not isinstance(payload, dict)
        or payload.get("archive_schema_version") != ARCHIVE_SCHEMA_VERSION
        or not isinstance(payload.get("record"), dict)
    ):
        raise ValueError("unsupported archived normalized fact")
    record = dict(payload["record"])
    record["kind"] = RecordKind(str(record["kind"]))
    record["provenance"] = _provenance(record["provenance"])
    for name in (
        "start_at",
        "end_at",
        "due_at",
        "source_created_at",
        "source_updated_at",
    ):
        record[name] = _optional_datetime(record.get(name))
    for name in (
        "labels",
        "dependency_references",
        "dependency_relationships",
        "dependency_display_urls",
        "membership_references",
        "dependent_references",
        "related_source_ids",
        "association_conflicts",
    ):
        record[name] = tuple(record.get(name, ()))
    record["associated_provenance"] = tuple(
        _provenance(item) for item in record.get("associated_provenance", ())
    )
    record["associated_source_facts"] = tuple(
        _associated_source_facts(item)
        for item in record.get("associated_source_facts", ())
    )
    return NormalizedRecord(**record)


@dataclass(frozen=True, slots=True)
class HistoricalBriefingService:
    """Select recorded runs and create explicit replay/reconstruction artifacts."""

    state_store: StateStore

    def recorded_for_date(
        self,
        briefing_date: date,
    ) -> tuple[BriefingPresentationState, ...]:
        """Return exact persisted presentations; never silently recompute."""

        return self.state_store.list_briefing_presentations_for_date(briefing_date)

    def replay(
        self,
        recorded_run_id: str,
        *,
        generated_at: datetime,
    ) -> HistoricalGeneration:
        """Run current logic against archived facts from one recorded run."""

        recorded = self.state_store.get_briefing_presentation(recorded_run_id)
        facts = self.state_store.get_briefing_archived_facts(recorded_run_id)
        if recorded is None or not facts:
            return HistoricalGeneration(
                run_id=None,
                result=None,
                mode=HistoricalMode.REPLAY,
                originating_recorded_run_id=recorded_run_id,
                disclosure=(
                    "No reliable replay can be produced because sufficient "
                    "archived normalized facts are unavailable."
                ),
            )
        records = tuple(
            deserialize_normalized_record(fact.normalized_fact_json) for fact in facts
        )
        as_of = recorded.run.as_of or recorded.run.generated_at
        if as_of is None:
            return HistoricalGeneration(
                run_id=None,
                result=None,
                mode=HistoricalMode.REPLAY,
                originating_recorded_run_id=recorded_run_id,
                disclosure="No reliable replay can be produced without an as-of time.",
            )
        coverage = tuple(
            SourceCoverage(
                source=item.source,
                approved_scope=item.approved_scope,
                status=item.coverage_status,
                retrieved_at=item.freshness_at or as_of,
                freshness_at=item.freshness_at,
                record_count=item.record_count,
                error_category=item.error_category,
                warnings=(
                    ("Archived facts may not include every source detail.",)
                    if item.coverage_status is not CoverageStatus.COMPLETE
                    else ()
                ),
            )
            for item in recorded.coverage
        )
        return self._generate(
            records=records,
            coverage=coverage,
            briefing_date=recorded.run.briefing_date,
            timezone=recorded.run.timezone,
            generated_at=generated_at,
            as_of=as_of,
            mode=HistoricalMode.REPLAY,
            originating_recorded_run_id=recorded_run_id,
            disclosure=(
                "Replay using current product logic and archived normalized facts. "
                "This is not the briefing originally shown."
            ),
            persist=True,
        )

    def reconstruct(
        self,
        *,
        records: tuple[NormalizedRecord, ...],
        coverage: tuple[SourceCoverage, ...],
        briefing_date: date,
        timezone: str,
        generated_at: datetime,
        as_of: datetime,
    ) -> HistoricalGeneration:
        """Create an explicitly limited later reconstruction."""

        zone = ZoneInfo(timezone)
        localized_as_of = _in_timezone(as_of, zone)
        localized_records = _records_in_timezone(records, zone)
        localized_coverage = _coverage_in_timezone(coverage, zone)
        filtered_records, filtered_coverage = _historical_snapshot(
            localized_records,
            localized_coverage,
            as_of=localized_as_of,
        )
        if not filtered_records or not any(
            item.status in {CoverageStatus.COMPLETE, CoverageStatus.PARTIAL}
            for item in filtered_coverage
        ):
            return HistoricalGeneration(
                run_id=None,
                result=None,
                mode=HistoricalMode.RECONSTRUCTED,
                originating_recorded_run_id=None,
                disclosure="No reliable historical briefing can be produced.",
            )
        return self._generate(
            records=filtered_records,
            coverage=filtered_coverage,
            briefing_date=briefing_date,
            timezone=timezone,
            generated_at=generated_at,
            as_of=localized_as_of,
            mode=HistoricalMode.RECONSTRUCTED,
            originating_recorded_run_id=None,
            disclosure=(
                "Reconstructed from available source history. Later source changes "
                "and unavailable historical state may affect accuracy."
            ),
            persist=True,
        )

    def synthetic(
        self,
        *,
        records: tuple[NormalizedRecord, ...],
        coverage: tuple[SourceCoverage, ...],
        briefing_date: date,
        timezone: str,
        generated_at: datetime,
        as_of: datetime,
    ) -> HistoricalGeneration:
        """Generate an evaluation scenario without adding personal history."""

        return self._generate(
            records=records,
            coverage=coverage,
            briefing_date=briefing_date,
            timezone=timezone,
            generated_at=generated_at,
            as_of=as_of,
            mode=HistoricalMode.SYNTHETIC,
            originating_recorded_run_id=None,
            disclosure="Synthetic evaluation scenario; no live personal data.",
            persist=False,
        )

    def _generate(
        self,
        *,
        records: tuple[NormalizedRecord, ...],
        coverage: tuple[SourceCoverage, ...],
        briefing_date: date,
        timezone: str,
        generated_at: datetime,
        as_of: datetime,
        mode: HistoricalMode,
        originating_recorded_run_id: str | None,
        disclosure: str,
        persist: bool,
    ) -> HistoricalGeneration:
        run_id = f"{mode.value}-{uuid.uuid4().hex}"
        context = resolve_context(
            run_id=run_id,
            briefing_date=briefing_date,
            timezone=timezone,
            invocation_mode=f"historical_{mode.value}",
            generated_at=generated_at,
            as_of=as_of,
            historical_mode=mode,
            originating_recorded_run_id=originating_recorded_run_id,
        )
        zone = ZoneInfo(context.timezone)
        records = _records_in_timezone(records, zone)
        coverage = _coverage_in_timezone(coverage, zone)
        decisions = (
            {}
            if mode is HistoricalMode.SYNTHETIC
            else {
                record.evidence_fingerprint: self.state_store.recurrence_decision(
                    record.evidence_fingerprint,
                    effective_at=context.as_of,
                )
                for record in records
                if record.evidence_fingerprint
            }
        )
        plan = build_reduced_plan(
            context,
            records,
            coverage,
            recurrence_decisions=decisions,
        )
        rendered = render_briefing(plan)
        validate_briefing(plan, rendered)
        result = PipelineResult(
            deduplication=DeduplicationResult(
                records=records,
                exact_duplicates=(),
                conflicts=(),
                associations=(),
            ),
            plan=plan,
            rendered=rendered,
        )
        if persist:
            self._persist_historical_result(
                run_id=run_id,
                result=result,
                generated_at=context.generated_at,
                as_of=context.as_of,
                mode=mode,
                originating_recorded_run_id=originating_recorded_run_id,
            )
        return HistoricalGeneration(
            run_id=run_id if persist else None,
            result=result,
            mode=mode,
            originating_recorded_run_id=originating_recorded_run_id,
            disclosure=disclosure,
        )

    def _persist_historical_result(
        self,
        *,
        run_id: str,
        result: PipelineResult,
        generated_at: datetime,
        as_of: datetime,
        mode: HistoricalMode,
        originating_recorded_run_id: str | None,
    ) -> None:
        context = result.plan.context
        self.state_store.add_briefing_run(
            BriefingRun(
                id=run_id,
                briefing_date=context.briefing_date,
                timezone=context.timezone,
                invocation_mode=context.invocation_mode,
                started_at=generated_at,
                completed_at=generated_at,
                status=BriefingStatus.SUCCEEDED,
                generated_at=generated_at,
                as_of=as_of,
                historical_mode=mode.value,
                originating_recorded_run_id=originating_recorded_run_id,
                processing_versions_json=json.dumps(
                    PROCESSING_VERSIONS,
                    sort_keys=True,
                ),
            )
        )
        for ordinal, coverage in enumerate(result.plan.coverage):
            connector_run_id = f"{run_id}:archive:{ordinal}"
            self.state_store.add_connector_run(
                ConnectorRun(
                    id=connector_run_id,
                    source=coverage.source,
                    approved_scope=coverage.approved_scope,
                    started_at=generated_at,
                    completed_at=generated_at,
                    status=(
                        ConnectorStatus.SUCCEEDED
                        if coverage.status is CoverageStatus.COMPLETE
                        else (
                            ConnectorStatus.PARTIAL
                            if coverage.status is CoverageStatus.PARTIAL
                            else ConnectorStatus.FAILED
                        )
                    ),
                    coverage_status=coverage.status,
                    freshness_at=coverage.freshness_at,
                    error_category=coverage.error_category,
                    record_count=coverage.record_count,
                )
            )
            self.state_store.link_connector_run(run_id, connector_run_id)
        self.state_store.save_briefing_presentation(
            presentation_from_plan(
                result.plan,
                briefing_run_id=run_id,
                created_at=generated_at,
                state_store=self.state_store,
            )
        )
        archive_pipeline_facts(
            self.state_store,
            briefing_run_id=run_id,
            result=result,
        )


def _provenance(value: object) -> Provenance:
    if not isinstance(value, dict):
        raise ValueError("archived provenance is invalid")
    data = dict(value)
    data["retrieved_at"] = _datetime(data["retrieved_at"])
    data["freshness_at"] = _optional_datetime(data.get("freshness_at"))
    domain = data.get("domain_classification")
    data["domain_classification"] = (
        None if domain is None else ConnectorDomain(str(domain))
    )
    return Provenance(**data)


def _associated_source_facts(value: object) -> AssociatedSourceFacts:
    if not isinstance(value, dict):
        raise ValueError("archived associated source fact is invalid")
    data = dict(value)
    data["provenance"] = _provenance(data["provenance"])
    data["due_at"] = _optional_datetime(data.get("due_at"))
    return AssociatedSourceFacts(**data)


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("archived timestamp is invalid")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("archived timestamp must be timezone-aware")
    return parsed


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else _datetime(value)


def _json_default(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    raise TypeError(f"unsupported archive value: {type(value).__name__}")


def _records_in_timezone(
    records: tuple[NormalizedRecord, ...],
    zone: ZoneInfo,
) -> tuple[NormalizedRecord, ...]:
    """Project archived instants into the briefing's authoritative timezone."""

    return tuple(
        replace(
            record,
            start_at=_optional_in_timezone(record.start_at, zone),
            end_at=_optional_in_timezone(record.end_at, zone),
            due_at=_optional_in_timezone(record.due_at, zone),
            source_created_at=_optional_in_timezone(record.source_created_at, zone),
            source_updated_at=_optional_in_timezone(record.source_updated_at, zone),
            provenance=_provenance_in_timezone(record.provenance, zone),
            associated_provenance=tuple(
                _provenance_in_timezone(item, zone)
                for item in record.associated_provenance
            ),
            associated_source_facts=tuple(
                replace(
                    item,
                    provenance=_provenance_in_timezone(item.provenance, zone),
                    due_at=_optional_in_timezone(item.due_at, zone),
                )
                for item in record.associated_source_facts
            ),
        )
        for record in records
    )


def _coverage_in_timezone(
    coverage: tuple[SourceCoverage, ...],
    zone: ZoneInfo,
) -> tuple[SourceCoverage, ...]:
    return tuple(
        replace(
            item,
            retrieved_at=_in_timezone(item.retrieved_at, zone),
            freshness_at=_optional_in_timezone(item.freshness_at, zone),
        )
        for item in coverage
    )


def _provenance_in_timezone(provenance: Provenance, zone: ZoneInfo) -> Provenance:
    return replace(
        provenance,
        retrieved_at=_in_timezone(provenance.retrieved_at, zone),
        freshness_at=_optional_in_timezone(provenance.freshness_at, zone),
    )


def _optional_in_timezone(value: datetime | None, zone: ZoneInfo) -> datetime | None:
    return None if value is None else _in_timezone(value, zone)


def _in_timezone(value: datetime, zone: ZoneInfo) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("historical timestamps must be timezone-aware")
    return value.astimezone(zone)


def _historical_snapshot(
    records: tuple[NormalizedRecord, ...],
    coverage: tuple[SourceCoverage, ...],
    *,
    as_of: datetime,
) -> tuple[tuple[NormalizedRecord, ...], tuple[SourceCoverage, ...]]:
    """Exclude facts that cannot honestly be known at the historical as-of."""

    retained: list[NormalizedRecord] = []
    omitted_by_source: dict[str, int] = {}
    volatile_sources = {"gmail", "todoist", "jira", "repository_context"}
    for record in records:
        evidence_time = record.source_updated_at or record.provenance.freshness_at
        unavailable = (evidence_time is not None and evidence_time > as_of) or (
            record.provenance.source in volatile_sources
            and evidence_time is None
            and record.provenance.retrieved_at > as_of
        )
        if unavailable:
            source = record.provenance.source
            omitted_by_source[source] = omitted_by_source.get(source, 0) + 1
            continue
        retained.append(record)
    adjusted = tuple(
        replace(
            item,
            status=(
                CoverageStatus.PARTIAL
                if omitted_by_source.get(item.source, 0)
                and item.status is CoverageStatus.COMPLETE
                else item.status
            ),
            warnings=(
                *item.warnings,
                *(
                    (
                        "Later or non-as-of source facts were excluded from the "
                        "historical reconstruction.",
                    )
                    if omitted_by_source.get(item.source, 0)
                    else ()
                ),
            ),
        )
        for item in coverage
    )
    return tuple(retained), adjusted
