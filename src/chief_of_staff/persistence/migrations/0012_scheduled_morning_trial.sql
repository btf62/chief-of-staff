CREATE TABLE scheduled_trials (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    timezone TEXT NOT NULL CHECK (length(timezone) > 0),
    eligible_weekdays_json TEXT NOT NULL CHECK (
        length(eligible_weekdays_json) > 0
    ),
    trigger_hour INTEGER NOT NULL CHECK (trigger_hour BETWEEN 0 AND 23),
    trigger_minute INTEGER NOT NULL CHECK (trigger_minute BETWEEN 0 AND 59),
    cutoff_hour INTEGER NOT NULL CHECK (cutoff_hour BETWEEN 0 AND 23),
    cutoff_minute INTEGER NOT NULL CHECK (cutoff_minute BETWEEN 0 AND 59),
    first_eligible_date TEXT NOT NULL,
    final_eligible_date TEXT NOT NULL,
    maximum_eligible_dates INTEGER NOT NULL CHECK (
        maximum_eligible_dates > 0
    ),
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    application_version TEXT NOT NULL CHECK (length(application_version) > 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE scheduled_occurrences (
    trial_id TEXT NOT NULL
        REFERENCES scheduled_trials(id) ON DELETE CASCADE,
    occurrence_date TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE CHECK (
        length(idempotency_key) > 0
    ),
    scheduled_for TEXT NOT NULL,
    actual_start_at TEXT NOT NULL,
    eligibility_decision TEXT NOT NULL CHECK (
        length(eligibility_decision) BETWEEN 1 AND 100
    ),
    outcome TEXT NOT NULL CHECK (
        outcome IN (
            'full_success',
            'reduced_success',
            'already_completed',
            'ineligible_day',
            'before_window',
            'missed_after_cutoff',
            'insufficient_sources',
            'credential_attention_required',
            'transient_failure',
            'configuration_failure',
            'trial_complete'
        )
    ),
    briefing_run_id TEXT
        REFERENCES briefing_runs(id) ON DELETE SET NULL,
    source_health_json TEXT NOT NULL DEFAULT '{}' CHECK (
        length(source_health_json) <= 4000
    ),
    aggregate_counts_json TEXT NOT NULL DEFAULT '{}' CHECK (
        length(aggregate_counts_json) <= 1000
    ),
    duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0),
    trial_ordinal INTEGER CHECK (
        trial_ordinal IS NULL OR trial_ordinal > 0
    ),
    application_version TEXT NOT NULL CHECK (length(application_version) > 0),
    notification_result TEXT CHECK (
        notification_result IS NULL OR length(notification_result) <= 100
    ),
    diagnostic_category TEXT CHECK (
        diagnostic_category IS NULL OR length(diagnostic_category) <= 100
    ),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (trial_id, occurrence_date)
);

CREATE INDEX scheduled_occurrences_outcome_idx
    ON scheduled_occurrences(outcome, occurrence_date);
