# Operations and release safeguards

The public origin remains https://care-credits-hackathon.vercel.app. The project
uses the existing Vercel Hobby and Neon Free resources. No paid upgrade is required.
Provider API credits are separate from hosting quotas.

## Releases

Vercel requires both GitHub check runs `backend` and `frontend` before assigning
production domains. Keep these job names in `.github/workflows/quality.yml`; update
the Vercel check configuration if they change. The frontend job includes browser
regressions and the proxy-signature test. Never force-promote a failed check.

For schema releases, hold automatic alias assignment, stage the build, verify the
additive migration in an isolated database/schema, apply the migration explicitly,
test the staged deployment, then promote and restore automatic assignment with
both required checks still present. Preserve the previous deployment for rollback.
Schema19 adds tables only; existing columns and routes are preserved. Application
rollback requires checking its schema-version readiness contract, not blindly
removing the version row or dropping data.

## Client attribution and abuse limits

The Next API proxy reads only Vercel's edge-overwritten `x-vercel-forwarded-for`.
It removes browser-supplied internal identity headers, then signs the IP, timestamp,
HTTP method and API path with server-only `PROXY_IDENTITY_SECRET`. Backend signatures
expire after 60 seconds. Invalid/missing signatures fall back to the connecting host.
IPv4/IPv6 addresses are validated; arbitrary forwarding chains are not accepted.
Per-email login throttles remain in place. The operator maintenance response exposes
only `client_identity_verified`, never the address or signature.

## Discovery and evidence

Serverless discovery remains one source per run, with 180-second scraper work,
210-second backend HTTP timeout and 240-second job lease. The default
`DISCOVERY_DAILY_RUN_LIMIT=10` caps project-wide attempts per UTC day, including
manual retries. Configure 1–100 explicitly; invalid configuration fails closed.
This is an attempt limit, not a currency spending guarantee. Provider-reported
usage can be unknown. Configure account-level budgets with each provider as well.

No paid extraction retries occur automatically. Repeating a terminal job returns
its stored result. A discovery run with no source pages does not prove a model
call occurred; the UI reports this explicitly. Only evidence-backed candidates
should be published, with missing claims left unknown.

Directory results preserve Markdown links. Discovery may follow one unambiguous,
query-matching course-detail link on the same hostname, with at most one additional
Tavily extraction per job and no recursive crawling. It replaces the directory as
the model source; a failed fetch retains the directory and reports the failure.
This can consume additional provider credits within the existing daily run limit.
Pasting a public course URL into discovery skips search and extracts that page
directly. Private addresses and credential-bearing URLs are rejected. This also
works when a directory's extracted content does not retain usable detail links.

Extraction warnings distinguish HTTP/network errors, truncated output, invalid JSON,
empty model results, schema fields and evidence failures. They never include raw
model values, response bodies or credentials. Optional null descriptions become
empty text; missing provider or mode still rejects the record. Model instructions
distinguish publication dates from course dates and accreditors from providers.
When an identity quotation is misselected, it can be replaced only by a literal,
word-bounded match of the unchanged title/provider in the fetched source (ignoring
case and whitespace). Invented names remain rejected; normal evidence validation
still runs on the corrected record.

`scripts/verify_live_discovery.py` is an opt-in, one-run live check scoped to the
existing production origin. It creates a temporary test identity, retains the run
for the permanent operator, verifies terminal-repeat idempotency and removes that
temporary identity. It never publishes candidates. Do not run it in CI.

The operator's **Maintenance and catalogue quality** panel lists published courses
with missing fields or reviews older than 30 days. A review date is not a claim
that a provider page was fetched recently. Reopen provider evidence and use the
existing review workflow; never mark an undated course self-paced without evidence.

## Email — intentionally disabled

Both password recovery and scheduled digests are prepared but disabled. The user
has no mail provider and explicitly requested this state. Do not enable either
until a free/no-card sender is configured and real delivery is verified.

Recovery requires `PASSWORD_RECOVERY_ENABLED=true`, SMTP configuration and an HTTPS
`PUBLIC_FRONTEND_BASE`. Tokens are hashed in storage, expire after 30 minutes and
are consumed atomically. Reset links use fragments rather than query parameters;
the UI removes the fragment. Successful resets invalidate all sessions and other
reset tokens. Changing a known password also invalidates outstanding reset tokens.
Unknown accounts and delivery failures get the same generic public response.
Delivery failures record an audit event without provider bodies or secrets.

SMTP uses certificate-verified STARTTLS. No recovery token is logged to disk by
the development mail adapter. Add sender credentials privately to Vercel and
verify delivery to an owner-controlled mailbox before enabling the UI.

Scheduled digests require **both** `DIGEST_ENABLED=true` and
`SERVERLESS_DIGEST_ENABLED=true`, SMTP and `PUBLIC_FRONTEND_BASE`. The maintenance
cron attempts at most one due message per invocation. A persistent unique dispatch
claim prevents concurrent/repeated delivery for the same cadence. An ambiguous
SMTP result or interrupted send stays claimed for operator review; it is not
automatically resent. This conservative pilot implementation prioritises avoiding
duplicate mail over guaranteed delivery. A larger audience needs a durable mail
outbox/worker and provider idempotency before increasing throughput.

## Maintenance and recovery

The authenticated daily cron expires abandoned ingestion jobs, applies source-text
retention and removes up to 500 expired sessions/reset tokens and old receipts per
table. Receipts retain timestamps, completion/failure status and counts without
secrets. The operator panel flags missing/overdue runs after 48 hours and runs
left unfinished for over five minutes. Scheduled timing is approximate on Hobby.

`scripts/verify_operational_restore.py` performs a logical row-restoration drill
inside a disposable schema in the existing database, verifies fingerprints and
tests migration idempotency. It exports no private rows and changes no live rows.
It is not an offsite backup or a test of Neon point-in-time retention. Confirm the
project's actual restore window and arrange an encrypted, tested backup appropriate
to the data before depending on this application for irreplaceable records.

## Deliberately deferred

Google OAuth, larger discovery batches, automatic upstream repository merging,
removal of legacy profile columns, external alert delivery and higher-volume email
are not required for this pilot. Keep the friend's review PR open. Review future
upstream changes through a tested integration PR rather than overwriting this backend.
