# Architecture release validation — 30 October 2026

The deployed application is kept on the existing Vercel project and public URL.
The upstream review PR is intentionally left open. See `BACKEND_ARCHITECTURE.md`
for module ownership and `VERCEL.md` for deployment configuration.

## Verification completed

- Production frontend build and TypeScript passed.
- All seven Chromium regression flows passed on the final frontend, including
  320/390/891/1440px dialog layouts, filter cancellation, profile drafts, expired
  sessions, certificate history and mobile keyboard navigation.
- Focused React lint passed with no errors or warnings. The OAuth anchor has an
  explicit exception because authentication requires full-document navigation.
- The 110-case portal suite was exercised; three obsolete expectations were
  corrected and their cases passed on rerun. Catalogue, digest, OAuth, extraction,
  security, worker and architecture suites were also exercised with focused reruns
  after fixes. Reruns are not counted as additional unique tests.
- Eight migration tests passed. A disposable PostgreSQL schema containing copies
  of existing account/session rows verified preservation, backfill, idempotency,
  canonical writes and row locking. The disposable schema was removed afterward.
- Thirteen focused serverless/scraper tests passed after removing circular Vercel
  bindings. The backend holds a 240-second lease, its HTTP timeout is 210 seconds,
  and scraper execution is bounded to 180 seconds. Queue workers keep their prior
  heartbeat protocol. Paid extraction is never automatically retried.
- Catalogue benchmark: 1,000 sessions, 10 concurrent reads, p95 0.597 seconds on
  the isolated local run; the unchanged threshold is one second.
- Two opt-in/environment-specific live checks were skipped. Provider credentials
  are excluded from the isolated test runner; mocked tests do not establish a new
  successful live model run. Historical live-run evidence remains in `VERCEL.md`.

## Operational limits at the architecture release

Email digests and forgotten-password email recovery are not configured. The UI
does not promise delivery; current-password changes work and revoke sessions.
Unknown course dates, advertised credits and other unsupported provider claims
remain unknown rather than being fabricated.

The new CI workflow reports test/build/browser results. It does not, by itself,
gate Vercel's automatic production-branch deployments; configuring required
deployment checks remains separate work. Server-observed IP rate-limit buckets
can still group users behind the private proxy; trusted per-client attribution
needs a separately verified forwarding contract. The application does not trust
arbitrary client-supplied forwarding headers.

## Operational hardening follow-up

The follow-up adds signed per-client forwarding, a project-wide discovery attempt
ceiling, email recovery behind an explicit disabled flag, persistent maintenance
receipts, conservative scheduled digest claims and an operator catalogue-quality
queue. Vercel now requires the `backend` and `frontend` GitHub checks for production
alias assignment. See `OPERATIONS.md` for enablement, limits and release procedure.

Focused recovery/forwarding/digest tests passed, as did the schema19 migration
tests and a 16-table logical restoration drill in a disposable PostgreSQL schema.
Existing routes and columns were compared before updating the contract snapshot;
all were preserved. The seven existing browser regressions and three new recovery/
operator flows passed after fixing development-mode reset-token retention.

One live Tavily query returned no source pages (job
`8e163b6a6cf6432a88246d73e33c067c`); it made no model extraction and is not NVIDIA
execution proof. Repeating that terminal job returned its unchanged receipt. The
temporary verification account was removed and the job retained for the operator.
Another provider call requires the separately requested approval. Email delivery
remains disabled at the user's request, pending a sender and real delivery checks.
