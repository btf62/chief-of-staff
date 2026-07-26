CREATE TABLE conclusions (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'commitment',
            'waiting_item',
            'preparation_item',
            'recommendation'
        )
    ),
    classification TEXT NOT NULL CHECK (
        classification IN ('explicit', 'inferred')
    ),
    statement TEXT NOT NULL CHECK (length(statement) > 0),
    explanation TEXT NOT NULL CHECK (length(explanation) > 0),
    confidence REAL CHECK (
        confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
    ),
    evidence_fingerprint TEXT NOT NULL CHECK (
        length(evidence_fingerprint) > 0
    ),
    processing_version TEXT NOT NULL CHECK (length(processing_version) > 0),
    created_at TEXT NOT NULL
);

CREATE TABLE conclusion_evidence (
    conclusion_id TEXT NOT NULL REFERENCES conclusions(id) ON DELETE CASCADE,
    evidence_id TEXT NOT NULL REFERENCES source_evidence(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    PRIMARY KEY (conclusion_id, evidence_id),
    UNIQUE (conclusion_id, ordinal)
);

CREATE TABLE disposition_events (
    id TEXT PRIMARY KEY,
    conclusion_id TEXT NOT NULL REFERENCES conclusions(id) ON DELETE CASCADE,
    briefing_run_id TEXT REFERENCES briefing_runs(id) ON DELETE SET NULL,
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
    replacement_text TEXT,
    note TEXT,
    created_at TEXT NOT NULL,
    CHECK (
        disposition != 'corrected'
        OR (replacement_text IS NOT NULL AND length(replacement_text) > 0)
    )
);

CREATE INDEX conclusions_fingerprint_idx
    ON conclusions(evidence_fingerprint, created_at);

CREATE INDEX disposition_events_conclusion_idx
    ON disposition_events(conclusion_id, created_at);

CREATE TRIGGER delete_orphaned_conclusion_after_evidence
AFTER DELETE ON conclusion_evidence
WHEN NOT EXISTS (
    SELECT 1
    FROM conclusion_evidence
    WHERE conclusion_id = OLD.conclusion_id
)
BEGIN
    DELETE FROM conclusions WHERE id = OLD.conclusion_id;
END;
