-- Sandbox-only copy of the KM Control auth table schema (schema only, no data),
-- captured read-only from DEV Control DB with pg_dump --schema-only on 2026-10-15.
-- Used only to stand up a throwaway database before applying migrations/20261015_km_source_credentials.sql.

CREATE TABLE public.km_audit_events (
    event_id text NOT NULL,
    occurred_at bigint NOT NULL,
    actor_user_id text,
    target_user_id text,
    event_type text NOT NULL,
    detail_json text NOT NULL
);

CREATE TABLE public.km_control_schema_migrations (
    version text NOT NULL,
    applied_at bigint NOT NULL
);

CREATE TABLE public.km_external_identities (
    identity_id text NOT NULL,
    provider_issuer text NOT NULL,
    subject text NOT NULL,
    user_id text,
    binding_status text NOT NULL,
    profile_json text NOT NULL,
    requested_at bigint NOT NULL,
    verified_at bigint,
    approved_at bigint,
    approved_by text,
    updated_at bigint NOT NULL,
    reviewed_by text,
    reviewed_at bigint,
    reject_reason text,
    CONSTRAINT km_external_binding_review_check CHECK ((((binding_status = 'pending'::text) AND (user_id IS NULL) AND (reviewed_by IS NULL) AND (reviewed_at IS NULL) AND (reject_reason IS NULL)) OR ((binding_status = 'bound'::text) AND (user_id IS NOT NULL) AND (reviewed_by IS NOT NULL) AND (reviewed_at IS NOT NULL) AND (reject_reason IS NULL)) OR ((binding_status = 'rejected'::text) AND (user_id IS NULL) AND (reviewed_by IS NOT NULL) AND (reviewed_at IS NOT NULL) AND (length(btrim(reject_reason)) > 0) AND (reject_reason IS NOT NULL)))),
    CONSTRAINT km_external_binding_status_check CHECK ((binding_status = ANY (ARRAY['pending'::text, 'bound'::text, 'rejected'::text])))
);

CREATE TABLE public.km_instance_grants (
    user_id text NOT NULL,
    instance_id text NOT NULL,
    role text NOT NULL,
    active boolean DEFAULT true NOT NULL,
    approved_by text NOT NULL,
    approved_at bigint NOT NULL,
    updated_at bigint NOT NULL
);

CREATE TABLE public.km_login_codes (
    code_hash text NOT NULL,
    user_id text NOT NULL,
    instance_id text NOT NULL,
    expires_at bigint NOT NULL,
    used_at bigint
);

CREATE TABLE public.km_oidc_transactions (
    state_hash text NOT NULL,
    nonce text NOT NULL,
    verifier text NOT NULL,
    expires_at bigint NOT NULL,
    used_at bigint
);

CREATE TABLE public.km_users (
    user_id text NOT NULL,
    username text NOT NULL,
    password_hash text NOT NULL,
    status text NOT NULL,
    is_admin boolean DEFAULT false NOT NULL,
    session_epoch bigint DEFAULT 1 NOT NULL,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL
);

ALTER TABLE ONLY public.km_audit_events
    ADD CONSTRAINT km_audit_events_pkey PRIMARY KEY (event_id);

ALTER TABLE ONLY public.km_control_schema_migrations
    ADD CONSTRAINT km_control_schema_migrations_pkey PRIMARY KEY (version);

ALTER TABLE ONLY public.km_external_identities
    ADD CONSTRAINT km_external_identities_pkey PRIMARY KEY (identity_id);

ALTER TABLE ONLY public.km_external_identities
    ADD CONSTRAINT km_external_identities_provider_issuer_subject_key UNIQUE (provider_issuer, subject);

ALTER TABLE ONLY public.km_instance_grants
    ADD CONSTRAINT km_instance_grants_pkey PRIMARY KEY (user_id, instance_id);

ALTER TABLE ONLY public.km_login_codes
    ADD CONSTRAINT km_login_codes_pkey PRIMARY KEY (code_hash);

ALTER TABLE ONLY public.km_oidc_transactions
    ADD CONSTRAINT km_oidc_transactions_pkey PRIMARY KEY (state_hash);

ALTER TABLE ONLY public.km_users
    ADD CONSTRAINT km_users_pkey PRIMARY KEY (user_id);

ALTER TABLE ONLY public.km_users
    ADD CONSTRAINT km_users_username_key UNIQUE (username);

CREATE UNIQUE INDEX km_external_identities_bound_user_unique ON public.km_external_identities USING btree (user_id) WHERE (binding_status = 'bound'::text);

