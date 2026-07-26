CREATE TABLE connector_runs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (length(source) > 0),
    approved_scope TEXT NOT NULL CHECK (length(approved_scope) > 0),
    retrieval_window_start TEXT,
    retrieval_window_end TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('running', 'succeeded', 'partial', 'failed')
    ),
    coverage_status TEXT NOT NULL CHECK (
        coverage_status IN (
            'complete',
            'partial',
            'unavailable',
            'unauthorized'
        )
    ),
    freshness_at TEXT,
    error_category TEXT
);

CREATE TABLE briefing_runs (
    id TEXT PRIMARY KEY,
    briefing_date TEXT NOT NULL,
    timezone TEXT NOT NULL CHECK (length(timezone) > 0),
    invocation_mode TEXT NOT NULL CHECK (length(invocation_mode) > 0),
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('running', 'succeeded', 'withheld', 'failed')
    )
);

CREATE TABLE briefing_connector_runs (
    briefing_run_id TEXT NOT NULL REFERENCES briefing_runs(id) ON DELETE CASCADE,
    connector_run_id TEXT NOT NULL REFERENCES connector_runs(id) ON DELETE CASCADE,
    PRIMARY KEY (briefing_run_id, connector_run_id)
);

CREATE TABLE source_evidence (
    id TEXT PRIMARY KEY,
    connector_run_id TEXT REFERENCES connector_runs(id) ON DELETE SET NULL,
    source TEXT NOT NULL CHECK (length(source) > 0),
    source_record_id TEXT NOT NULL CHECK (length(source_record_id) > 0),
    display_url TEXT,
    excerpt TEXT CHECK (excerpt IS NULL OR length(excerpt) <= 2000),
    evidence_fingerprint TEXT NOT NULL CHECK (
        length(evidence_fingerprint) > 0
    ),
    retrieved_at TEXT NOT NULL,
    freshness_at TEXT
);

CREATE INDEX source_evidence_fingerprint_idx
    ON source_evidence(evidence_fingerprint);

CREATE INDEX source_evidence_source_record_idx
    ON source_evidence(source, source_record_id);
