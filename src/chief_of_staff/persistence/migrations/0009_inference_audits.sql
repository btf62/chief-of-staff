CREATE TABLE inference_audits (
    id TEXT PRIMARY KEY,
    briefing_run_id TEXT REFERENCES briefing_runs(id) ON DELETE SET NULL,
    candidate_id_hash TEXT NOT NULL,
    task_name TEXT NOT NULL,
    task_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    model_configuration_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    sensitivity_tier TEXT NOT NULL CHECK (
        sensitivity_tier IN (
            'tier_1_ordinary_operational',
            'tier_2_heightened',
            'tier_3_highly_sensitive',
            'unknown_or_ambiguous',
            'mixed_sensitivity',
            'prohibited_secret'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN ('completed', 'refused', 'unavailable', 'rejected', 'skipped')
    ),
    validation_status TEXT CHECK (
        validation_status IS NULL OR validation_status IN (
            'accepted',
            'schema_rejected',
            'provenance_rejected',
            'policy_rejected'
        )
    ),
    request_count INTEGER NOT NULL CHECK (request_count >= 0),
    latency_ms INTEGER NOT NULL CHECK (latency_ms >= 0),
    input_tokens INTEGER NOT NULL CHECK (input_tokens >= 0),
    output_tokens INTEGER NOT NULL CHECK (output_tokens >= 0),
    total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
    estimated_cost_microusd INTEGER CHECK (
        estimated_cost_microusd IS NULL OR estimated_cost_microusd >= 0
    ),
    error_category TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_inference_audits_created_at
    ON inference_audits(created_at);
