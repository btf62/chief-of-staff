ALTER TABLE briefing_runs ADD COLUMN generated_at TEXT;
ALTER TABLE briefing_runs ADD COLUMN as_of TEXT;
ALTER TABLE briefing_runs ADD COLUMN historical_mode TEXT NOT NULL
    DEFAULT 'current'
    CHECK (
        historical_mode IN (
            'current',
            'recorded',
            'replay',
            'reconstructed',
            'synthetic'
        )
    );
ALTER TABLE briefing_runs ADD COLUMN originating_recorded_run_id TEXT
    REFERENCES briefing_runs(id) ON DELETE SET NULL;
ALTER TABLE briefing_runs ADD COLUMN processing_versions_json TEXT NOT NULL
    DEFAULT '{}';

UPDATE briefing_runs
SET generated_at = COALESCE(completed_at, started_at),
    as_of = COALESCE(completed_at, started_at)
WHERE generated_at IS NULL OR as_of IS NULL;

ALTER TABLE briefing_items ADD COLUMN temporal_state TEXT
    CHECK (
        temporal_state IS NULL OR
        temporal_state IN ('Earlier today', 'In progress', 'Upcoming')
    );
ALTER TABLE briefing_items ADD COLUMN starts_at TEXT;
ALTER TABLE briefing_items ADD COLUMN ends_at TEXT;
ALTER TABLE connector_runs ADD COLUMN record_count INTEGER
    CHECK (record_count IS NULL OR record_count >= 0);

CREATE TABLE briefing_archived_facts (
    briefing_run_id TEXT NOT NULL
        REFERENCES briefing_runs(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
    source TEXT NOT NULL CHECK (length(source) > 0),
    source_record_id TEXT NOT NULL CHECK (length(source_record_id) > 0),
    normalized_fact_json TEXT NOT NULL CHECK (
        length(normalized_fact_json) > 0
    ),
    PRIMARY KEY (briefing_run_id, ordinal)
);

CREATE INDEX briefing_archived_facts_source_idx
    ON briefing_archived_facts(source, source_record_id);

CREATE INDEX briefing_runs_historical_date_idx
    ON briefing_runs(briefing_date, generated_at, id);
