# V1 integrated demo

The root Next.js application serves the functional V1 dashboard at `/v1` (also `/live`), with the operator workspace at `/workspace`. V2–V5 remain design prototypes.

## Provenance

Backend and portal recovered from dman1313/CareCredits commit e51f3d5, before the incomplete router/model refactor. Scraper, shared contracts and topic configuration imported from b7e8765 (PR #8). PR #19 is not included. The restored backend uses authenticated leased scraper jobs; the newer worker retains compatibility with this protocol. No claim is made that all roadmap issues are complete.

## Run locally

Use Python 3.12 and Node 22. Install backend and scraper requirements in a virtual environment, then run `python scripts/dev.py --demo`. Open the printed frontend address followed by `/v1`. The runner starts the root Next.js app, API and scraper. Demo login: `demo@carecredits.local` / `CareCredits-demo-2026`. Fixture courses are fictional. The doctor-only fixture account is `doctor@carecredits.local`.

For a production-style deployment, configure `.env` using `python scripts/setup_integrations.py`, then run `docker compose up --build`. Set the public frontend URL and allowed origins to the actual HTTPS domain. Production must have DEMO_MODE=false. PostgreSQL data uses a named volume. Do not expose the API or scraper directly to the internet.

## Hackathon live AI

Live extraction now requires explicit MODEL_ID, MODEL_BASE_URL, MODEL_API_KEY, MODEL_WEIGHTS_URL and MODEL_LICENSE_URL plus MODEL_OPEN_WEIGHT_CONFIRMED=true. The development runner no longer injects provisional identities. Publisher/host labels are optional metadata; the actual endpoint hostname is recorded independently. The operator job view displays successful source-validated extraction receipts with requested model, endpoint hostname, timestamp and candidate count. Receipts are scraper-reported evidence, not independent provider attestation. Fixtures never display a live success label. Existing candidate review and source links remain alongside the receipts.

The approved bounded live verification could not run because MODEL_API_KEY and TAVILY_API_KEY are absent locally. Configure them privately with scripts/setup_integrations.py, restart services, then enqueue one job with max_results=1 in the operator workspace. Review its receipt and candidate before publishing. Do not claim the demo used NVIDIA until this succeeds.

The suggested model is NVIDIA Nemotron 3 Super on Nebius Token Factory, ID `nvidia/nemotron-3-super-120b-a12b`. Configure MODEL_API_KEY and TAVILY_API_KEY privately using the setup script, confirm the model's licence and open weights, and inspect operator integration status. Suggested identity is not proof of a live call. Execute a bounded discovery job, review source evidence, publish a candidate, find it as a doctor, record attendance and confirm progress changes.

Before submission: verify that live sequence, deploy the application, record a public video under three minutes, describe changes made during the submission period, and provide platform feedback. An open-source licence for the combined work still needs agreement from the original code owners; this import does not invent a licence grant for their contributions.

## Remaining scope

Verification on Windows: production Next.js compilation and type checking passed; 52 scraper tests passed; live login, catalogue search and course detail through the frontend proxy passed. The full portal regression suite is tracked separately. Live paid AI and public deployment are not verified.

Renewal rule sets, evidence attachments, calendar reminders, saved-course ranking and organization views remain roadmap work. Displayed learning totals are self-reported, not regulator certification. Existing source documentation may describe the previous standalone layout; use this document for the combined repository.
