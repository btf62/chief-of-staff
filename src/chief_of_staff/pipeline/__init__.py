"""Deterministic reduced-briefing pipeline."""

from chief_of_staff.pipeline.briefing import (
    BriefingItem,
    BriefingPlan,
    BriefingSection,
    BriefingSectionName,
    BriefingValidationError,
    PriorityInputs,
    RenderedBriefing,
    SourceLink,
    build_reduced_plan,
    render_briefing,
    validate_briefing,
)
from chief_of_staff.pipeline.context import InvocationContext, resolve_context
from chief_of_staff.pipeline.deduplication import (
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
)

__all__ = (
    "BriefingItem",
    "BriefingPlan",
    "BriefingSection",
    "BriefingSectionName",
    "BriefingValidationError",
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
    "build_reduced_plan",
    "deduplicate_records",
    "normalize_item",
    "render_briefing",
    "resolve_context",
    "validate_briefing",
)
