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

## Extraction repair and successful live verification — 30 October 2026

The later approved investigation supersedes the live-extraction gap above. A
diagnostic reproduction rejected directory records on description/provider/mode
schema fields, then identified provider quotations that did not support the
claimed name. A direct course fetch also exposed an empty Tavily extraction.

The repair distinguishes safe error categories, normalizes missing optional
descriptions, corrects identity quotations only from literal fetched text, supports
direct course URLs and bounded matching detail links, and adds a restricted public
HTML fallback for CPD Online. Required identity and source-evidence checks remain.
The restricted adapter's directory-to-detail path passed a public-page check and
mocked safety tests. No authenticated lesson content is accessed.

Live job `541b975e26994f5f8c6feb1621390886` succeeded with no warnings. Its receipt
records `nvidia/nemotron-3-super-120b-a12b` at `api.tokenfactory.nebius.com`, 5,401
reported model tokens and four validated candidates. Search selected the provider
homepage on this run, so this is live proof of extraction, not an isolated live
proof of the fallback. All four candidates are held for operator review; no new
courses were auto-published. Unknown dates, fees and points remain null. Repeating
the terminal run returned the unchanged receipt without another extraction.

Code release `6597d59` passed the 423-test backend suite (37 modules, no failed
modules), ten browser tests, and staged end-to-end checks covering authentication,
profile/learning-record persistence, CSV, certificates, permissions, maintenance
and disabled email. The temporary verification accounts were removed. The public
URL remains `https://care-credits-hackathon.vercel.app/`.
