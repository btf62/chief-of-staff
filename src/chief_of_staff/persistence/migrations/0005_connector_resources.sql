ALTER TABLE oauth_clients
ADD COLUMN oauth_grant_type TEXT CHECK (
    oauth_grant_type IS NULL OR
    oauth_grant_type IN ('resource_level')
);

CREATE TABLE connector_resources (
    connector TEXT PRIMARY KEY
        REFERENCES connector_authorizations(connector) ON DELETE CASCADE,
    resource_reference TEXT NOT NULL CHECK (
        length(resource_reference) > 0
    ),
    resource_id TEXT NOT NULL CHECK (length(resource_id) > 0),
    resource_url TEXT NOT NULL CHECK (length(resource_url) > 0),
    resource_type TEXT NOT NULL CHECK (length(resource_type) > 0),
    grant_type TEXT NOT NULL CHECK (
        grant_type IN ('resource_level')
    ),
    selected_at TEXT NOT NULL
);
