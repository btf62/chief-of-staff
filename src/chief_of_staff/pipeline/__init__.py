"""Deterministic reduced-briefing pipeline."""

from chief_of_staff.pipeline.briefing import (
    BriefingItem,
    BriefingPlan,
    BriefingSection,
    BriefingSectionName,
    BriefingValidationError,
    CalendarEventClassification,
    PriorityInputs,
    RenderedBriefing,
    SourceLink,
    TaskCandidateAudit,
    TaskPlanningConfidence,
    build_reduced_plan,
    classify_calendar_event,
    render_briefing,
    validate_briefing,
)
from chief_of_staff.pipeline.context import (
    InvocationContext,
    WorkdayType,
    reconcile_calendar_workday_context,
    resolve_context,
)
from chief_of_staff.pipeline.deduplication import (
    CrossSourceAssociation,
    DeduplicationResult,
    RecordCluster,
    deduplicate_records,
)
from chief_of_staff.pipeline.normalization import (
    NormalizedRecord,
    Provenance,
    RecordKind,
    normalize_item,
)
from chief_of_staff.pipeline.runner import (
    DeterministicBriefingPipeline,
    PipelineResult,
    recompose_pipeline_result,
)

__all__ = (
    "BriefingItem",
    "BriefingPlan",
    "BriefingSection",
    "BriefingSectionName",
    "BriefingValidationError",
    "CalendarEventClassification",
    "CrossSourceAssociation",
    "DeduplicationResult",
    "DeterministicBriefingPipeline",
    "InvocationContext",
    "NormalizedRecord",
    "PipelineResult",
    "PriorityInputs",
    "Provenance",
    "RecordCluster",
    "RecordKind",
    "RenderedBriefing",
    "SourceLink",
    "TaskCandidateAudit",
    "TaskPlanningConfidence",
    "WorkdayType",
    "build_reduced_plan",
    "classify_calendar_event",
    "deduplicate_records",
    "normalize_item",
    "recompose_pipeline_result",
    "reconcile_calendar_workday_context",
    "render_briefing",
    "resolve_context",
    "validate_briefing",
)
