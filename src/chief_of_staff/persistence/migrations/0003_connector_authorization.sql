ALTER TABLE connector_runs
ADD COLUMN page_count INTEGER CHECK (page_count IS NULL OR page_count >= 0);

CREATE TABLE oauth_clients (
    connector TEXT PRIMARY KEY CHECK (length(connector) > 0),
    oauth_project_id TEXT NOT NULL CHECK (length(oauth_project_id) > 0),
    oauth_client_id TEXT NOT NULL CHECK (length(oauth_client_id) > 0),
    credential_service TEXT NOT NULL CHECK (length(credential_service) > 0),
    client_secret_account TEXT NOT NULL CHECK (
        length(client_secret_account) > 0
    ),
    configured_at TEXT NOT NULL
);

CREATE TABLE connector_authorizations (
    connector TEXT PRIMARY KEY
        REFERENCES oauth_clients(connector) ON DELETE CASCADE,
    account_reference TEXT NOT NULL CHECK (length(account_reference) > 0),
    account_identity TEXT NOT NULL CHECK (length(account_identity) > 0),
    granted_scope TEXT NOT NULL CHECK (length(granted_scope) > 0),
    credential_service TEXT NOT NULL CHECK (length(credential_service) > 0),
    access_token_account TEXT NOT NULL CHECK (
        length(access_token_account) > 0
    ),
    authorization_status TEXT NOT NULL CHECK (
        authorization_status IN ('authorized', 'expired', 'revoked', 'error')
    ),
    credential_health TEXT NOT NULL CHECK (
        credential_health IN ('healthy', 'expired', 'missing', 'error')
    ),
    token_expires_at TEXT NOT NULL,
    authorized_at TEXT NOT NULL,
    last_used_at TEXT,
    updated_at TEXT NOT NULL
);
