# V1 on Vercel Hobby and Neon Free

Project: `daily-gattai/care-credits`. Database: `care-credits-db`, Neon Free,
Singapore. No paid upgrades or credit card are authorized.

`vercel.json` uses Vercel Services (beta): Next.js owns public routing, and the
Python FastAPI service is reachable through the runtime `BACKEND_URL` binding.
The existing Next API proxy preserves same-origin sessions. Database credentials
are provisioned by the Neon integration and must never be committed.

The Python entrypoint enforces production cookies, disables demo seed accounts,
and disables process-based schedulers. Deploy-time migrations must run explicitly
using the direct Neon connection, before deployment; runtime uses the pooled
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

Live discovery is deliberately disabled until MODEL_API_KEY, MODEL_BASE_URL,
MODEL_ID, MODEL_WEIGHTS_URL, MODEL_LICENSE_URL, MODEL_OPEN_WEIGHT_CONFIRMED and
TAVILY_API_KEY are configured privately. Select the supported NVIDIA model on
Nebius explicitly; no successful live run is claimed without a recorded receipt.
Model/Tavily usage is separate from free hosting quotas.

Production uses `https://care-credits-omega.vercel.app`. Set
`ALLOWED_ORIGINS`, `PUBLIC_FRONTEND_BASE`, and `PUBLIC_API_BASE` explicitly to
that origin: service-scoped Vercel host variables can describe the internal
backend rather than the public frontend. Keep preview authentication enabled;
the production domain is public with Standard Protection.

## Owner access and email

Register an account through `/v1`; an administrator must then promote the owner's
specific account to operator using the database management command documented
in `docs/RENDER.md`. Do not auto-promote by email on unauthenticated signup.
Google OAuth and delivered email digests need their own credentials and are not
configured by this deployment. Certificates are self-reported affiliation records.

## Verification

Test `/api/v1/config`, registration, login, persistent profile/records, exports,
certificates, logout and operator authorization through the public frontend.
Run `python -m unittest backend.tests.test_serverless.ServerlessTests` with
`PYTHONPATH` including the repository root and `backend` for bounded-job tests.
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
The result is `partial` because the optional Jev decide/save service is absent;
the four candidates await operator review and were not automatically published.
Calling the terminal job again returned its saved result. The temporary evidence
account's password was randomized and its sessions and operator role revoked.

The owner's confirmed account has operator access. Email delivery and Google
OAuth remain unconfigured; automatic scheduled jobs remain disabled.
