CREATE TABLE IF NOT EXISTS admin_identities (
    subject       TEXT PRIMARY KEY,
    required_role TEXT NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at    INTEGER NOT NULL,
    updated_at    INTEGER NOT NULL,
    CHECK (length(subject) BETWEEN 1 AND 255),
    CHECK (length(required_role) BETWEEN 1 AND 255)
);

CREATE TABLE IF NOT EXISTS admin_oauth_transactions (
    handle_hash   TEXT PRIMARY KEY,
    state_hash    TEXT UNIQUE NOT NULL,
    nonce         TEXT NOT NULL,
    code_verifier TEXT NOT NULL,
    return_to     TEXT NOT NULL,
    created_at    INTEGER NOT NULL,
    expires_at    INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_admin_oauth_transactions_expires
    ON admin_oauth_transactions(expires_at);

CREATE TABLE IF NOT EXISTS admin_sessions (
    token_hash              TEXT PRIMARY KEY,
    subject                 TEXT NOT NULL,
    email                   TEXT NOT NULL,
    role                    TEXT NOT NULL,
    csrf_token              TEXT NOT NULL,
    access_token_ciphertext TEXT NOT NULL,
    id_token_ciphertext     TEXT NOT NULL,
    oauth_expires_at        INTEGER NOT NULL,
    created_at              INTEGER NOT NULL,
    expires_at              INTEGER NOT NULL,
    last_seen_at            INTEGER NOT NULL,
    FOREIGN KEY (subject) REFERENCES admin_identities(subject) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires
    ON admin_sessions(expires_at);

CREATE INDEX IF NOT EXISTS idx_admin_sessions_subject
    ON admin_sessions(subject);
