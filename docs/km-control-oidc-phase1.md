# KM Control Auth OIDC Phase 1

OIDC login is disabled by default. It must remain disabled until a trusted KM
DEV FQDN, registered Client ID, issuer discovery metadata and protected runtime
secrets are available. The public JWKS may be enabled independently so Shared
Identity can register the confidential client before OIDC login is activated.
The legacy local KM login remains the active path.

When enabled, Control Auth exposes these fixed paths:

- `/oidc/login`: authorization-code initiation with PKCE S256, random state and nonce.
- `/oidc/availability`: exposes only whether Shared Identity sign-in is enabled.
- `/oidc/callback`: backend-only token exchange and ID-token validation.
- `/.well-known/km-oidc-client-jwks.json`: public registration JWK set.
- `/signed-out`: KM-only logout landing page.
- `/oidc/logout`: KM-only logout by default; `?shared=true` is the explicit
  RP-initiated path and is unavailable until an end-session endpoint is configured.
- `/oidc/logout/callback`: post-logout landing route.

The Control DB stores only immutable `(provider_issuer, subject)` identity
bindings. Profile claims are retained as metadata and are never automatic
binding keys. New OIDC identities remain `pending`; a local KM account password
verification changes them to `awaiting_approval`; an administrator alone changes
them to `bound`. Existing account grants, role and status remain on the same
local account ID.

Use `client_secret_basic` for the Phase 1 confidential client. Keep the
Shared Identity client secret only in the protected Control Auth runtime
environment; never put it in browser code, this repository, logs, or project
memory. Map the confirmed `account`, `name`, `email`, and `department` claims
through `KM_OIDC_CLAIM_MAPPING_JSON`. `sub` is stored only as part of the
`(issuer, sub)` identity key. Do not depend on `EmailConfirmed` or `TeamCode`
until Shared Identity explicitly issues those claims.
