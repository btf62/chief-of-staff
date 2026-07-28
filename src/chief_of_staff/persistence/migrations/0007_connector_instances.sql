CREATE TABLE connector_instances (
    id TEXT PRIMARY KEY CHECK (length(id) > 0),
    provider TEXT NOT NULL CHECK (length(provider) > 0),
    alias TEXT NOT NULL CHECK (length(alias) > 0),
    domain_classification TEXT NOT NULL CHECK (
        domain_classification IN ('work', 'personal', 'unclassified')
    ),
    approved_resource_boundary TEXT NOT NULL CHECK (
        length(approved_resource_boundary) > 0
    ),
    approved_scopes TEXT NOT NULL CHECK (length(approved_scopes) > 0),
    retrieval_configuration TEXT NOT NULL CHECK (
        length(retrieval_configuration) > 0
    ),
    last_coverage_status TEXT CHECK (
        last_coverage_status IS NULL OR
        last_coverage_status IN (
            'complete',
            'partial',
            'unavailable',
            'unauthorized'
        )
    ),
    last_freshness_at TEXT,
    enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
    retention_policy_reference TEXT NOT NULL CHECK (
        length(retention_policy_reference) > 0
    ),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX connector_instances_provider_idx
    ON connector_instances(provider, enabled);

INSERT INTO connector_instances(
    id,
    provider,
    alias,
    domain_classification,
    approved_resource_boundary,
    approved_scopes,
    retrieval_configuration,
    last_coverage_status,
    last_freshness_at,
    enabled,
    retention_policy_reference,
    created_at,
    updated_at
)
SELECT
    client.connector || ':primary',
    client.connector,
    CASE client.connector
        WHEN 'google_calendar' THEN 'Primary Calendar'
        WHEN 'todoist' THEN 'Todoist'
        WHEN 'jira' THEN 'Jira'
        ELSE client.connector
    END,
    'unclassified',
    COALESCE(
        (
            SELECT run.approved_scope
            FROM connector_runs AS run
            WHERE run.source = client.connector
               OR (
                    client.connector = 'jira'
                    AND run.source = 'jira_project_discovery'
                )
            ORDER BY run.started_at DESC, run.id DESC
            LIMIT 1
        ),
        client.connector
    ),
    COALESCE(authorization.granted_scope, 'not-authorized'),
    'provider-default',
    (
        SELECT run.coverage_status
        FROM connector_runs AS run
        WHERE run.source = client.connector
           OR (
                client.connector = 'jira'
                AND run.source = 'jira_project_discovery'
            )
        ORDER BY run.started_at DESC, run.id DESC
        LIMIT 1
    ),
    (
        SELECT run.freshness_at
        FROM connector_runs AS run
        WHERE run.source = client.connector
           OR (
                client.connector = 'jira'
                AND run.source = 'jira_project_discovery'
            )
        ORDER BY run.started_at DESC, run.id DESC
        LIMIT 1
    ),
    CASE
        WHEN authorization.authorization_status = 'authorized' THEN 1
        ELSE 0
    END,
    'adr-0004-default',
    client.configured_at,
    COALESCE(authorization.updated_at, client.configured_at)
FROM oauth_clients AS client
LEFT JOIN connector_authorizations AS authorization
    ON authorization.connector = client.connector;

CREATE TABLE oauth_clients_v2 (
    connector_instance_id TEXT PRIMARY KEY
        REFERENCES connector_instances(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (length(provider) > 0),
    oauth_project_id TEXT NOT NULL CHECK (length(oauth_project_id) > 0),
    oauth_client_id TEXT NOT NULL CHECK (length(oauth_client_id) > 0),
    credential_service TEXT NOT NULL CHECK (length(credential_service) > 0),
    client_secret_account TEXT NOT NULL CHECK (
        length(client_secret_account) > 0
    ),
    configured_at TEXT NOT NULL,
    application_owner TEXT,
    oauth_grant_type TEXT CHECK (
        oauth_grant_type IS NULL OR
        length(oauth_grant_type) > 0
    )
);

INSERT INTO oauth_clients_v2
SELECT
    connector || ':primary',
    connector,
    oauth_project_id,
    oauth_client_id,
    credential_service,
    client_secret_account,
    configured_at,
    application_owner,
    oauth_grant_type
FROM oauth_clients;

CREATE TABLE connector_authorizations_v2 (
    connector_instance_id TEXT PRIMARY KEY
        REFERENCES oauth_clients_v2(connector_instance_id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (length(provider) > 0),
    account_reference TEXT NOT NULL CHECK (length(account_reference) > 0),
    account_identity TEXT NOT NULL CHECK (length(account_identity) > 0),
    granted_scope TEXT NOT NULL CHECK (length(granted_scope) > 0),
    credential_service TEXT NOT NULL CHECK (length(credential_service) > 0),
    access_token_account TEXT NOT NULL CHECK (
        length(access_token_account) > 0
    ),
    refresh_token_account TEXT,
    authorization_status TEXT NOT NULL CHECK (
        authorization_status IN ('authorized', 'expired', 'revoked', 'error')
    ),
    credential_health TEXT NOT NULL CHECK (
        credential_health IN ('healthy', 'expired', 'missing', 'error')
    ),
    refresh_health TEXT CHECK (
        refresh_health IS NULL OR
        refresh_health IN ('healthy', 'expired', 'missing', 'error')
    ),
    token_expires_at TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    last_used_at TEXT,
    updated_at TEXT NOT NULL
);

INSERT INTO connector_authorizations_v2
SELECT
    connector || ':primary',
    connector,
    account_reference,
    account_identity,
    granted_scope,
    credential_service,
    access_token_account,
    refresh_token_account,
    authorization_status,
    credential_health,
    refresh_health,
    token_expires_at,
    authorized_at,
    last_used_at,
    updated_at
FROM connector_authorizations;

CREATE TABLE connector_resources_v2 (
    connector_instance_id TEXT PRIMARY KEY
        REFERENCES connector_authorizations_v2(connector_instance_id)
        ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (length(provider) > 0),
    resource_reference TEXT NOT NULL CHECK (
        length(resource_reference) > 0
    ),
    resource_id TEXT NOT NULL CHECK (length(resource_id) > 0),
    resource_url TEXT NOT NULL CHECK (length(resource_url) > 0),
    resource_type TEXT NOT NULL CHECK (length(resource_type) > 0),
    grant_type TEXT NOT NULL CHECK (length(grant_type) > 0),
    selected_at TEXT NOT NULL
);

INSERT INTO connector_resources_v2
SELECT
    connector || ':primary',
    connector,
    resource_reference,
    resource_id,
    resource_url,
    resource_type,
    grant_type,
    selected_at
FROM connector_resources;

DROP TABLE connector_resources;
DROP TABLE connector_authorizations;
DROP TABLE oauth_clients;

ALTER TABLE oauth_clients_v2 RENAME TO oauth_clients;
ALTER TABLE connector_authorizations_v2
    RENAME TO connector_authorizations;
ALTER TABLE connector_resources_v2 RENAME TO connector_resources;

CREATE INDEX oauth_clients_provider_idx
    ON oauth_clients(provider);

CREATE INDEX connector_authorizations_provider_idx
    ON connector_authorizations(provider, authorization_status);

CREATE INDEX connector_resources_provider_idx
    ON connector_resources(provider);

ALTER TABLE connector_runs
ADD COLUMN connector_instance_id TEXT
    REFERENCES connector_instances(id) ON DELETE SET NULL;

UPDATE connector_runs
SET connector_instance_id = CASE source
    WHEN 'google_calendar' THEN 'google_calendar:primary'
    WHEN 'todoist' THEN 'todoist:primary'
    WHEN 'jira' THEN 'jira:primary'
    WHEN 'jira_project_discovery' THEN 'jira:primary'
    ELSE NULL
END;

CREATE INDEX connector_runs_instance_idx
    ON connector_runs(connector_instance_id, started_at);

ALTER TABLE source_evidence
ADD COLUMN connector_instance_id TEXT
    REFERENCES connector_instances(id) ON DELETE SET NULL;

UPDATE source_evidence
SET connector_instance_id = COALESCE(
    (
        SELECT connector_runs.connector_instance_id
        FROM connector_runs
        WHERE connector_runs.id = source_evidence.connector_run_id
    ),
    CASE source
        WHEN 'google_calendar' THEN 'google_calendar:primary'
        WHEN 'todoist' THEN 'todoist:primary'
        WHEN 'jira' THEN 'jira:primary'
        ELSE NULL
    END
);

CREATE INDEX source_evidence_instance_record_idx
    ON source_evidence(connector_instance_id, source_record_id);
