# V1 on Vercel Hobby and Neon Free

Project: `daily-gattai/care-credits`. Database: `care-credits-db`, Neon Free,
Singapore. No paid upgrades or credit card are authorized.

`vercel.json` uses Vercel Services (beta): Next.js owns public routing, and the
Python FastAPI service is reachable through the runtime `BACKEND_URL` binding.
The backend calls the separate scraper service through `SCRAPER_SERVICE_URL`.
Bindings form a one-way chain: frontend → backend → scraper. Vercel rejects
circular bindings, so bounded execution does not use scraper-to-backend callbacks.
Neither Python service has a public rewrite. Calls also require the
shared `SCRAPER_SERVICE_TOKEN`; a binding alone is not application authorization.
The existing Next API proxy preserves same-origin sessions. Database credentials
are provisioned by the Neon integration and must never be committed.

The Python entrypoint enforces production cookies, disables demo seed accounts,
and disables process-based schedulers. Deploy-time migrations must run explicitly
using the direct Neon connection, before production promotion; runtime uses the pooled
connection and NullPool to avoid stale connections after scale-to-zero.

## Discovery

Serverless jobs accept one source per run. The operator creates a persisted job,
then POSTs its `/run` endpoint. An atomic queued-to-running update prevents two
requests executing the same job. Completion is persisted; calling a completed
job again returns its result without spending again. Expired leases become
interrupted and require explicit retry. The UI can run a queued job if the first
request was interrupted before execution.

Full extraction results use the existing job-completion review path. They do not
use the optional separate Jev catalogue decision service in this mode; candidates
remain subject to operator review. Daily batch queueing is disabled on this
deployment. Existing non-serverless Docker deployments keep their worker mode.

The scraper runtime is `scraper.service:app`. The backend atomically claims a
240-second lease and supplies its expiry to the authenticated scraper. The scraper
rejects expired execution windows before provider work, enforces a 180-second
extraction deadline, and returns a validated completion payload. The backend
checks the stored lease token again before saving completion. Its HTTP client has
a 210-second timeout and never
automatically retries paid extraction. The scraper contains no database imports
or persistence code. Project-level environment variables remain managed by
Vercel; do not assume process separation itself scopes project secrets.

## Schema 18 rollout

The feature architecture and compatibility rules are documented in
`docs/BACKEND_ARCHITECTURE.md`. `scripts/verify_profile_postgres.py` tests the
profile migration against copies of existing account/session rows in a disposable
PostgreSQL schema, then removes that schema. It does not modify live tables or
export personal rows. This is a fallback for environments without Neon branch
management access, not a claim that a Neon branch was created.

Deploy with `vercel deploy --prod --skip-domain`, inspect the staged deployment,
apply the explicit additive migration through the direct database connection,
then promote the tested deployment. Preserve the existing project/domain and
repository connection. Never enable demo seeds in production.

Live discovery is deliberately disabled until MODEL_API_KEY, MODEL_BASE_URL,
MODEL_ID, MODEL_WEIGHTS_URL, MODEL_LICENSE_URL, MODEL_OPEN_WEIGHT_CONFIRMED and
TAVILY_API_KEY are configured privately. Select the supported NVIDIA model on
Nebius explicitly; no successful live run is claimed without a recorded receipt.
Model/Tavily usage is separate from free hosting quotas.

Production uses `https://care-credits-hackathon.vercel.app`. Set
`ALLOWED_ORIGINS`, `PUBLIC_FRONTEND_BASE`, and `PUBLIC_API_BASE` explicitly to
that origin: service-scoped Vercel host variables can describe the internal
backend rather than the public frontend. Keep preview authentication enabled;
the production domain is public with Standard Protection.
The former `care-credits-omega.vercel.app` domain redirects to this address.
The dashboard loads directly at `/`. Legacy `/v1`–`/v5` and `/live` paths
redirect to `/`; no version picker or version labels are shown to visitors.

## Owner access and email

Register an account through `/`; an administrator must then promote the owner's
specific account to operator using the database management command documented
in `docs/RENDER.md`. Do not auto-promote by email on unauthenticated signup.
Google OAuth and delivered email digests need their own credentials and are not
configured by this deployment. Certificates are self-reported affiliation records.

## Verification

Test `/api/v1/config`, registration, login, persistent profile/records, exports,
certificates, logout and operator authorization through the public frontend.
Run `python scripts/test_backend.py` for isolated backend and scraper tests.
Use `--module backend.tests.test_serverless` for the bounded-job tests. Each module
runs once in a fresh process with deployment credentials removed and an in-memory
default database; tests create their own disposable database fixtures.
Production builds use `npm run build:demo`, not the legacy Sites build script.

Free hosting has quotas and Vercel Hobby is limited to personal non-commercial
use. Do not enable a Pro trial, paid compute, or a paid Neon plan automatically.

## Verified deployment — 29 October 2026

Production branch: `codex/v1-integrated-demo`. Live model and Tavily credentials
are configured as Vercel production Secrets, never in source control.

The public production smoke test passed signup/login, secure cookies, doctor
role restrictions, persisted profile and attendance records, progress, CSV export,
certificate rendering, and logout. Its temporary account and course were removed.
Four bounded-job unit tests passed, including duplicate execution prevention.

Live job `c17a4923f36640bf9cd5d303a13fd7b3` fetched `https://cpdonline.my`
through Tavily and extracted four candidates with
`nvidia/nemotron-3-super-120b-a12b` on `api.tokenfactory.nebius.com`.
The saved extraction receipt is dated `2026-10-29T15:21:54.865455Z` and reports
3,120 model tokens. Tavily did not report a credit count; it is unknown, not zero.
This historical run was marked `partial` because the optional Jev decide/save service was absent. That classification has since been corrected for deployments without Jev. Its four candidates were subsequently reviewed and published; their catalogue fields remain limited to evidence actually extracted from the provider.
Calling the terminal job again returned its saved result. The temporary evidence
account's password was randomized and its sessions and operator role revoked.

The owner's confirmed account has operator access. Email delivery and Google
OAuth remain unconfigured. Discovery remains operator-triggered; maintenance scheduling is described below.

## Maintenance and deployment checks

The daily Vercel cron calls `/api/maintenance` at 20:00 UTC (04:00 Asia/Kuala_Lumpur).
Set the same strong `CRON_SECRET` privately on the frontend and backend services
before enabling this deployment. The frontend verifies Vercel's Bearer header,
then forwards it to `/internal/v1/maintenance`. This endpoint only performs
expired-job and source-text retention cleanup; it does not call Tavily or a model. Missing or invalid
credentials fail closed. Verify one authenticated maintenance response after
configuration and monitor scheduled invocations. No paid scheduler is required.

Serverless email digests remain unavailable, and the UI uses `digest_available`
to hide delivery controls. Configuring mail credentials alone does not enable a
scheduler. Do not promise delivered email until the deployment supports and tests it.

`Quality checks` runs backend regressions, a production frontend build, and Chromium browser regressions without
production secrets. Make these checks required in repository branch protection
before relying on them as a merge gate. A workflow alone does not block Vercel's
automatic branch deployment; review deployment protection/check settings separately.
The browser suite should run against an isolated local demo, never production,
because its test accounts and learning records are disposable.

New affiliation records preserve an issuance-time identity snapshot. History is
available from `/api/v1/me/certificates`; older records are labelled as legacy.
Printable HTML supports Unicode names. A direct PDF is offered only where the
backend reports `pdf_available`; otherwise use the browser's Save as PDF option.
