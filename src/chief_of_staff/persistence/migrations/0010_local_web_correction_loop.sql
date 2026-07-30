ALTER TABLE disposition_events RENAME TO disposition_events_legacy;

CREATE TABLE disposition_events (
    id TEXT PRIMARY KEY,
    conclusion_id TEXT NOT NULL
        REFERENCES conclusions(id) ON DELETE CASCADE,
    originating_briefing_id TEXT
        REFERENCES briefing_runs(id) ON DELETE SET NULL,
    disposition TEXT NOT NULL CHECK (
        disposition IN (
            'confirmed',
            'corrected',
            'dismissed',
            'delegated',
            'rescheduled',
            'completed',
            'intentionally_abandoned'
        )
    ),
    previous_state TEXT NOT NULL CHECK (
        previous_state IN (
            'active',
            'confirmed',
            'corrected',
            'dismissed',
            'delegated',
            'rescheduled',
            'completed',
            'intentionally_abandoned'
        )
    ),
    new_state TEXT NOT NULL CHECK (
        new_state IN (
            'confirmed',
            'corrected',
            'dismissed',
            'delegated',
            'rescheduled',
            'completed',
            'intentionally_abandoned'
        )
    ),
    replacement_text TEXT,
    explanation TEXT,
    delegate_description TEXT,
    follow_up_at TEXT,
    rescheduled_for TEXT,
    evidence_fingerprint TEXT NOT NULL CHECK (
        length(evidence_fingerprint) > 0
    ),
    processing_version TEXT NOT NULL CHECK (
        length(processing_version) > 0
    ),
    expected_version INTEGER NOT NULL CHECK (expected_version >= 0),
    resulting_version INTEGER NOT NULL CHECK (
        resulting_version = expected_version + 1
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) >= 16
    ),
    created_at TEXT NOT NULL,
    CHECK (
        disposition != 'corrected'
        OR (replacement_text IS NOT NULL AND length(replacement_text) > 0)
    )
);

WITH ordered_events AS (
    SELECT
        legacy.*,
        ROW_NUMBER() OVER (
            PARTITION BY legacy.conclusion_id
            ORDER BY legacy.created_at, legacy.id
        ) AS event_version,
        LAG(legacy.disposition) OVER (
            PARTITION BY legacy.conclusion_id
            ORDER BY legacy.created_at, legacy.id
        ) AS prior_disposition
    FROM disposition_events_legacy AS legacy
)
INSERT INTO disposition_events(
    id,
    conclusion_id,
    originating_briefing_id,
    disposition,
    previous_state,
    new_state,
    replacement_text,
    explanation,
    evidence_fingerprint,
    processing_version,
    expected_version,
    resulting_version,
    idempotency_key,
    created_at
)
SELECT
    ordered.id,
    ordered.conclusion_id,
    ordered.briefing_run_id,
    ordered.disposition,
    COALESCE(ordered.prior_disposition, 'active'),
    ordered.disposition,
    ordered.replacement_text,
    ordered.note,
    conclusions.evidence_fingerprint,
    conclusions.processing_version,
    ordered.event_version - 1,
    ordered.event_version,
    'legacy-event:' || ordered.id,
    ordered.created_at
FROM ordered_events AS ordered
JOIN conclusions ON conclusions.id = ordered.conclusion_id;

DROP TABLE disposition_events_legacy;

CREATE INDEX disposition_events_conclusion_idx
    ON disposition_events(conclusion_id, created_at);

CREATE TABLE conclusion_current_state (
    conclusion_id TEXT PRIMARY KEY
        REFERENCES conclusions(id) ON DELETE CASCADE,
    current_state TEXT NOT NULL CHECK (
        current_state IN (
            'active',
            'confirmed',
            'corrected',
            'dismissed',
            'delegated',
            'rescheduled',
            'completed',
            'intentionally_abandoned'
        )
    ),
    display_statement TEXT NOT NULL CHECK (length(display_statement) > 0),
    delegate_description TEXT,
    follow_up_at TEXT,
    rescheduled_for TEXT,
    version INTEGER NOT NULL CHECK (version >= 0),
    last_event_id TEXT,
    updated_at TEXT NOT NULL
);

INSERT INTO conclusion_current_state(
    conclusion_id,
    current_state,
    display_statement,
    delegate_description,
    follow_up_at,
    rescheduled_for,
    version,
    last_event_id,
    updated_at
)
SELECT
    conclusion.id,
    COALESCE(
        (
            SELECT event.disposition
            FROM disposition_events AS event
            WHERE event.conclusion_id = conclusion.id
            ORDER BY event.created_at DESC, event.id DESC
            LIMIT 1
        ),
        'active'
    ),
    COALESCE(
        (
            SELECT event.replacement_text
            FROM disposition_events AS event
            WHERE event.conclusion_id = conclusion.id
              AND event.replacement_text IS NOT NULL
            ORDER BY event.created_at DESC, event.id DESC
            LIMIT 1
        ),
        conclusion.statement
    ),
    (
        SELECT event.delegate_description
        FROM disposition_events AS event
        WHERE event.conclusion_id = conclusion.id
        ORDER BY event.created_at DESC, event.id DESC
        LIMIT 1
    ),
    (
        SELECT event.follow_up_at
        FROM disposition_events AS event
        WHERE event.conclusion_id = conclusion.id
        ORDER BY event.created_at DESC, event.id DESC
        LIMIT 1
    ),
    (
        SELECT event.rescheduled_for
        FROM disposition_events AS event
        WHERE event.conclusion_id = conclusion.id
        ORDER BY event.created_at DESC, event.id DESC
        LIMIT 1
    ),
    (
        SELECT COUNT(*)
        FROM disposition_events AS event
        WHERE event.conclusion_id = conclusion.id
    ),
    (
        SELECT event.id
        FROM disposition_events AS event
        WHERE event.conclusion_id = conclusion.id
        ORDER BY event.created_at DESC, event.id DESC
        LIMIT 1
    ),
    COALESCE(
        (
            SELECT event.created_at
            FROM disposition_events AS event
            WHERE event.conclusion_id = conclusion.id
            ORDER BY event.created_at DESC, event.id DESC
            LIMIT 1
        ),
        conclusion.created_at
    )
FROM conclusions AS conclusion;

CREATE TABLE conclusion_tombstones (
    evidence_fingerprint TEXT PRIMARY KEY CHECK (
        length(evidence_fingerprint) > 0
    ),
    processing_version TEXT NOT NULL CHECK (
        length(processing_version) > 0
    ),
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) >= 16
    ),
    deleted_at TEXT NOT NULL
);

CREATE TABLE briefing_presentations (
    briefing_run_id TEXT PRIMARY KEY
        REFERENCES briefing_runs(id) ON DELETE CASCADE,
    generation_mode TEXT NOT NULL CHECK (length(generation_mode) > 0),
    chief_of_staff_note TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE briefing_sections (
    id INTEGER PRIMARY KEY,
    briefing_run_id TEXT NOT NULL
        REFERENCES briefing_presentations(briefing_run_id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    name TEXT NOT NULL CHECK (length(name) > 0),
    summary TEXT,
    UNIQUE (briefing_run_id, ordinal)
);

CREATE TABLE briefing_items (
    id TEXT PRIMARY KEY,
    briefing_run_id TEXT NOT NULL
        REFERENCES briefing_presentations(briefing_run_id) ON DELETE CASCADE,
    section_id INTEGER NOT NULL
        REFERENCES briefing_sections(id) ON DELETE CASCADE,
    conclusion_id TEXT
        REFERENCES conclusions(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    headline TEXT NOT NULL CHECK (length(headline) > 0),
    detail TEXT NOT NULL,
    content_kind TEXT NOT NULL CHECK (
        content_kind IN (
            'authoritative_source_fact',
            'explicit_detection',
            'inferred_conclusion',
            'recommendation',
            'presentation_only_synthesis'
        )
    ),
    uncertainty TEXT,
    explanation TEXT,
    UNIQUE (section_id, ordinal)
);

CREATE INDEX briefing_items_conclusion_idx
    ON briefing_items(conclusion_id);

CREATE TABLE briefing_item_sources (
    briefing_item_id TEXT NOT NULL
        REFERENCES briefing_items(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    source TEXT NOT NULL CHECK (length(source) > 0),
    display_url TEXT,
    freshness_at TEXT,
    PRIMARY KEY (briefing_item_id, ordinal)
);
