CREATE TABLE normalized_jira_issues (
    evidence_id TEXT PRIMARY KEY
        REFERENCES source_evidence(id) ON DELETE CASCADE,
    issue_key TEXT NOT NULL CHECK (length(issue_key) > 0),
    summary TEXT NOT NULL CHECK (length(summary) > 0),
    project_key TEXT NOT NULL CHECK (length(project_key) > 0),
    issue_type TEXT NOT NULL CHECK (length(issue_type) > 0),
    status TEXT NOT NULL CHECK (length(status) > 0),
    status_category TEXT NOT NULL CHECK (length(status_category) > 0),
    assignee_account_id TEXT NOT NULL CHECK (length(assignee_account_id) > 0),
    priority_name TEXT,
    due_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    parent_key TEXT
);

CREATE TABLE normalized_jira_issue_labels (
    evidence_id TEXT NOT NULL
        REFERENCES normalized_jira_issues(evidence_id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK (length(label) > 0),
    PRIMARY KEY (evidence_id, label)
);

CREATE TABLE normalized_jira_issue_links (
    evidence_id TEXT NOT NULL
        REFERENCES normalized_jira_issues(evidence_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK (length(relationship) > 0),
    related_issue_id TEXT NOT NULL CHECK (length(related_issue_id) > 0),
    related_issue_key TEXT NOT NULL CHECK (length(related_issue_key) > 0),
    display_url TEXT,
    PRIMARY KEY (
        evidence_id,
        relationship,
        related_issue_id,
        related_issue_key
    )
);
