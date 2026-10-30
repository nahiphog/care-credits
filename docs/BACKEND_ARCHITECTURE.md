# Backend architecture and migration

This architecture follows the domain separation reviewed in `dman1313/CareCredits`, at upstream commit `b7e87655de479479af2401b7103d51fe502f176b`, while retaining this application's deployed API and data. It is an integration of the two implementations, not a replacement of the existing database with the upstream schema.

## Request and persistence boundaries

The request path is:

`Next.js same-origin proxy -> FastAPI router -> feature service -> repository -> SQLAlchemy model/database`

- `backend/main.py` constructs FastAPI, installs HTTP error/middleware boundaries, and composes feature routers. It does not alias another module or implement catalogue/account workflows.
- `backend/routers/` owns HTTP requests, dependencies, response types, validation DTOs and status codes. `http_boundary.py` owns origin checks and request logging.
- `backend/services/` owns application decisions and workflow orchestration. Active services do not import FastAPI, Pydantic or SQLAlchemy, and do not issue session queries or commits directly. Domain exceptions are translated at the HTTP boundary.
- `backend/repository/` owns queries, writes, row locks and transaction operations. Methods express persistence intentions, such as finding a job, locking the scheduling account, inserting a scheduled job or updating a learning record.
- `backend/models/` owns passive ORM mappings grouped into account/profile, session, course/evidence, records, ingestion, digest, certificate and operational metadata modules. `models/schema.py` is an export facade, not a store for business logic.
- `backend/database/` owns connection/session setup and explicit schema migrations. A readiness request verifies schema compatibility; it never silently migrates production.
- `backend/domain/` contains shared application rules and errors without HTTP or database ownership.

`portal_models.py`, `schedule.py`, `catalogue.py` and the deprecated discovery-service facade retain selected old imports for scripts/tests. Active feature paths import their canonical service/repository directly. The old large portal service is not the application entrypoint.

## Discovery and catalogue domains

Discovery responsibilities are split across `discovery_status_service`, `ingestion_job_service`, `ingestion_completion_service`, `candidate_review_service`, and `catalogue_connect_service`. Catalogue reads and catalogue review policy have separate services and repositories.

`services/schedule_service.py` reads curated topics, validates limits, applies the daily ceiling and chooses which failed jobs may be retried. `repository/schedule_repository.py` owns account locking, day-scoped job counting, unique-key inserts and requeue persistence. The account lock uses `FOR UPDATE OF accounts`; this avoids trying to lock the nullable side of the eager profile join on PostgreSQL. Successful jobs are never replayed by force-retry.

The `scraper/` package remains separate: it uses the shared training contract and authenticated HTTP/catalogue boundaries, not backend ORM/database imports. Vercel's bounded single-source execution and the external-worker lease protocol are retained. A partial extraction remains visibly partial when malformed candidates are discarded.

## Account/profile separation: schema 18

Authentication data remains in `accounts`: stable account ID, email, password hash, identity-provider IDs, authorization role and creation time. Role intentionally remains an authorization attribute rather than a user-editable public-profile field.

`account_profiles` is the canonical one-to-one store for name, biography, city/state, coordinates/location consent, public visibility and public slug. Its primary key is the existing account ID. Profiles load with their account in one query.

The additive migration `database/profile_migration.py::upgrade_profile_schema` creates the profile table and backfills only missing profiles using `INSERT ... SELECT`. It preserves IDs, credentials, sessions, public URLs and existing profile values. Re-running it does not overwrite profile edits. The migration caller owns transaction completion and schema-version stamping; both version-17 and unversioned existing databases are handled by `database/migrations.py`.

The old physical profile columns remain in `accounts` during rollout. Temporary `Account` hybrid attributes read the canonical profile, fall back to legacy data only when a profile is absent, and dual-write both stores. Explicit canonical null values do not accidentally fall back to old coordinates. This compatibility layer is storage plumbing, not an application service.

### Deployment order and rollback

1. Validate the upgrade on an isolated PostgreSQL/Neon branch, including existing accounts, sessions, public links and learning records. Local SQLite regression tests are useful but do not replace that check.
2. Apply the explicit migration with the direct database connection before routing production traffic to schema-18 code. Keep runtime on its configured pooled connection. Request startup must not execute DDL.
3. Check `/health/ready`, authentication/profile editing, public profiles, catalogue search and certificate history on the deployed application.
4. Preserve the legacy columns until the rollback window closes. Compatibility setters maintain rollback data. Direct writes to `AccountProfile` do not mirror old columns, so writes during this phase must use the account repository/compatibility setters or explicitly mirror the legacy projection.

Rolling the application back does not require dropping `account_profiles`. Do not delete the new table or revert schema data as part of an application rollback. After running an older application that writes legacy columns only, reconcile those writes before returning to the canonical-profile application; the idempotent backfill deliberately will not overwrite existing profiles.

## Extensions deliberately preserved

The upstream separation is adopted without losing the production extensions: session/origin protections, record history and private notes, public-profile consent, source evidence, versioned candidate corrections, immutable certificate snapshots/history, bounded serverless discovery, job leases/retries, retention and operational readiness. Schema 18 changes profile ownership; it does not renumber accounts or migrate course/learning-record IDs.

Certificate identity snapshots stay in the existing append-only audit JSON and need no additional certificate-table migration. New snapshots are hash-checked; historical certificates without identity snapshots are labelled as legacy rather than regenerated with today's profile.

Automatic email digests remain unavailable on the current serverless deployment. Changing a password requires the current password and revokes all sessions; email-based account recovery requires a separately configured delivery flow. Architecture cleanup does not imply those external capabilities are configured.

## Enforcement and verification

`backend/tests/test_architecture.py` locks the existing route/table contract and checks composition, service boundaries, passive model imports and scraper isolation. Existing table metadata is unchanged; `account_profiles` is the intentional additive contract.

`test_profile_migration.py` verifies backfill preservation, idempotency, explicit null semantics, compatibility writes, joined loading and both upgrade entry paths. `test_schedule_layers.py` verifies daily ceiling/idempotency and failed-only force-retry behavior against disposable databases.

The broader API suites continue to verify behavior through HTTP. Test patches target the feature that owns a dependency, rather than manufacturing exports on `main.py`. No production deployment or database validation is implied by these local test descriptions.
