"""Convert an application-owned briefing plan into minimized local UI state."""

from __future__ import annotations

import hashlib
from datetime import datetime

from chief_of_staff.domain import (
    BriefingPresentation,
    BriefingPresentationItem,
    BriefingPresentationSection,
    BriefingPresentationSource,
)
from chief_of_staff.persistence import StateStore
from chief_of_staff.pipeline import BriefingPlan, BriefingSectionName


def presentation_from_plan(
    plan: BriefingPlan,
    *,
    briefing_run_id: str,
    created_at: datetime,
    state_store: StateStore,
) -> BriefingPresentation:
    """Create a safe structured presentation without raw source payloads."""

    note = next(
        (
            section.summary or ""
            for section in plan.sections
            if section.name is BriefingSectionName.CHIEF_OF_STAFF_NOTE
        ),
        "",
    )
    sections: list[BriefingPresentationSection] = []
    for section in plan.sections:
        if section.name in {
            BriefingSectionName.CHIEF_OF_STAFF_NOTE,
            BriefingSectionName.SOURCE_COVERAGE,
        }:
            continue
        items: list[BriefingPresentationItem] = []
        for ordinal, item in enumerate(section.items):
            source_records = tuple(
                (source.source, source.source_record_id) for source in item.sources
            )
            conclusion_id = state_store.find_conclusion_id_by_source_records(
                source_records
            )
            explanation = item.inference_explanation
            if explanation is None and item.priority_inputs is not None:
                explanation = item.priority_inputs.explanation()
            item_id = hashlib.sha256(
                (
                    f"{briefing_run_id}\x00{section.name.value}\x00"
                    f"{ordinal}\x00{item.key}"
                ).encode()
            ).hexdigest()
            items.append(
                BriefingPresentationItem(
                    id=item_id,
                    conclusion_id=conclusion_id,
                    headline=item.headline,
                    detail=item.detail,
                    content_kind=item.content_kind.value,
                    uncertainty=item.uncertainty,
                    explanation=explanation,
                    sources=tuple(
                        BriefingPresentationSource(
                            source=source.source,
                            display_url=source.display_url,
                        )
                        for source in item.sources
                    ),
                    temporal_state=(
                        None
                        if item.temporal_state is None
                        else item.temporal_state.value
                    ),
                    starts_at=item.starts_at,
                    ends_at=item.ends_at,
                )
            )
        if items or section.summary:
            sections.append(
                BriefingPresentationSection(
                    name=section.name.value,
                    summary=section.summary,
                    items=tuple(items),
                )
            )
    return BriefingPresentation(
        briefing_run_id=briefing_run_id,
        generation_mode=plan.generation_mode,
        chief_of_staff_note=note,
        created_at=created_at,
        sections=tuple(sections),
    )
