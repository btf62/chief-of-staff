ALTER TABLE oauth_clients
ADD COLUMN application_owner TEXT;

ALTER TABLE connector_authorizations
ADD COLUMN refresh_token_account TEXT;

ALTER TABLE connector_authorizations
ADD COLUMN refresh_health TEXT CHECK (
    refresh_health IS NULL OR
    refresh_health IN ('healthy', 'expired', 'missing', 'error')
);

CREATE TABLE normalized_source_tasks (
    evidence_id TEXT PRIMARY KEY
        REFERENCES source_evidence(id) ON DELETE CASCADE,
    title TEXT NOT NULL CHECK (length(title) > 0),
    provider_priority INTEGER NOT NULL CHECK (
        provider_priority BETWEEN 1 AND 4
    ),
    recurring INTEGER NOT NULL CHECK (recurring IN (0, 1)),
    all_day INTEGER NOT NULL CHECK (all_day IN (0, 1)),
    due_at TEXT,
    project_id TEXT,
    project_name TEXT,
    section_id TEXT,
    section_name TEXT,
    responsible_user_id TEXT,
    parent_task_id TEXT,
    created_at TEXT,
    updated_at TEXT
);

CREATE TABLE normalized_source_task_labels (
    evidence_id TEXT NOT NULL
        REFERENCES normalized_source_tasks(evidence_id) ON DELETE CASCADE,
    label_id TEXT,
    label_name TEXT NOT NULL CHECK (length(label_name) > 0),
    PRIMARY KEY (evidence_id, label_name)
);
