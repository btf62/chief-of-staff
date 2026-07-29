CREATE TABLE normalized_gmail_messages (
    evidence_id TEXT PRIMARY KEY
        REFERENCES source_evidence(id) ON DELETE CASCADE,
    thread_id TEXT NOT NULL CHECK (length(thread_id) > 0),
    direction TEXT NOT NULL
        CHECK (direction IN ('direct_inbound', 'outbound')),
    occurred_at TEXT NOT NULL,
    participant_references TEXT NOT NULL,
    subject TEXT,
    label_classification TEXT NOT NULL
        CHECK (length(label_classification) > 0),
    detection_type TEXT,
    processing_version TEXT NOT NULL CHECK (length(processing_version) > 0)
);
