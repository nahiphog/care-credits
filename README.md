# Care Credits

Care Credits helps Malaysian doctors find CPD courses, inspect the provider's source information, and keep a personal learning record. Operators can discover courses with Tavily and an NVIDIA model on Nebius, review the extracted evidence, and publish listings without duplicating existing sessions.

**[Open the application](https://care-credits-hackathon.vercel.app/) · [Judge walkthrough](docs/JUDGE_WALKTHROUGH.md) · [Local setup](docs/SETUP.md)**

The hackathon application is on **[`codex/v1-integrated-demo`](https://github.com/nahiphog/care-credits/tree/codex/v1-integrated-demo)**. Clone that branch explicitly: `main` is not the integrated application. The dashboard opens at `/`, with discovery and review tools shown to operators in **Discover** and **Overview**. The alternate `/workspace` route remains available for compatibility; earlier dashboard experiments are archived.

## What you can try

Each dashboard section has a direct URL: `/overview`, `/my-credits`, `/discover`, `/events`, `/certificates`, `/about-credits` and `/settings`. The homepage `/` opens Discover. Sidebar navigation, refresh and browser Back/Forward select the matching page; signing in from a direct link keeps that destination.

- Search the published Malaysian CPD catalogue and filter by location, date and delivery mode.
- Inspect course details, advertised credits and provider/source links before registering externally.
- Record provider sign-up and attendance, track self-reported points, and export personal records as CSV.
- Issue a printable Care Credits affiliation record and view its history.
- As an operator, review discovered candidates and their source evidence, publish or reject them, and inspect discovery receipts and catalogue-quality checks.

Care Credits is not an accreditation authority. Opening a provider link does not register you. Advertised credits are source claims; recorded attendance and points are self-reported. A Care Credits affiliation record is **not** an MMC, MOH or APC certificate.

## Run the fictional demo locally

Requires **Git, Node.js 22.13 or newer with npm, and Python 3.12**. Use a fresh checkout and a terminal without deployment environment variables. No API keys, cloud account, Docker, credit card or `.env` file is needed for this demo. Installation requires internet access.

```sh
git clone --branch codex/v1-integrated-demo --single-branch https://github.com/nahiphog/care-credits.git
cd care-credits
```

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
.\.venv\Scripts\python.exe scripts/dev.py --demo
```

macOS / Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
.venv/bin/python scripts/dev.py --demo
```

Open the **frontend URL printed after `CareCredits live:`**, normally `http://127.0.0.1:3000`. The launcher selects nearby free ports if the defaults are occupied. Keep its terminal running.

| Local demo role | Email | Password |
| --- | --- | --- |
| Doctor | `doctor@carecredits.local` | `CareCredits-demo-2026` |
| Operator | `demo@carecredits.local` | `CareCredits-demo-2026` |

These are public, fictional **local-only** accounts. They do not provide access to production. The seed contains six example courses, personal records and an operator review queue. Follow the [judge walkthrough](docs/JUDGE_WALKTHROUGH.md) for the exact actions and expected results.

See [setup and troubleshooting](docs/SETUP.md) before reusing an existing checkout: `--demo` does not override an existing `DATABASE_URL`, and demo sign-in reseeds example data. Never point this mode at a shared or production database.

## Where NVIDIA and Nebius are used

The live discovery workflow is:

```text
Operator query → Tavily search/fetch → NVIDIA extraction on Nebius
              → schema and source-evidence checks → candidate review
              → duplicate check → published catalogue → doctor search
```

The configured live model is `nvidia/nemotron-3-super-120b-a12b`, served through Nebius Token Factory's API. It turns retrieved provider text into structured course candidates. Application validation checks required fields and supporting quotations; model output alone does not establish accreditation or permission to publish.

The successful **30 October 2026** run recorded job `541b975e26994f5f8c6feb1621390886`, **5,401 reported model tokens and four validated candidates**, with no warnings. See the [release validation record](docs/RELEASE_VALIDATION.md#extraction-repair-and-successful-live-verification--30-october-2026) and [hosting/run evidence](docs/VERCEL.md). This is historical live-run evidence, not a claim that the key-free local demo invokes the model. Those candidates are not a count of newly published courses.

`MODEL_ID` and `MODEL_BASE_URL` independently select the model and endpoint; the repository supplies [provisional defaults and model-card/licence links](shared/model_defaults.py). Live deployments set identity and provenance explicitly. Live reproduction requires privately configured Tavily and Nebius credentials and may consume provider credits; it is optional for the local walkthrough.

## Architecture and deployment

| Area | Responsibility |
| --- | --- |
| `app/`, `components/`, `lib/` | Next.js interface and same-origin API proxy |
| `backend/routers/`, `backend/schemas/` | HTTP routes, request/response contracts and validation |
| `backend/services/`, `backend/repository/` | Feature workflows, database queries and transactions |
| `backend/models/`, `backend/database/` | Domain mappings, sessions and explicit schema migrations |
| `backend/main.py`, `backend/lifecycle.py`, `backend/http_boundary.py` | Application composition, startup and request policy |
| `scraper/`, `shared/`, `config/` | Discovery, extraction, evidence validation and shared contracts |

The public deployment uses Next.js and FastAPI on Vercel Hobby, with PostgreSQL on Neon Free. Local demo storage is SQLite. Nebius hosts model inference; it is not the web application's hosting platform. See [backend architecture](docs/BACKEND_ARCHITECTURE.md), [reconciliation decisions](docs/RECONCILIATION.md) and [Vercel operations](docs/VERCEL.md).

## Verification and current limits

Use the isolated backend runner and the Next.js production build from the repository root. Substitute `.venv/bin/python` on macOS/Linux:

```powershell
.\.venv\Scripts\python.exe scripts/test_backend.py
npm run build:demo
```

The [setup guide](docs/SETUP.md#verification) also covers browser tests. [Local demo verification](docs/LOCAL_DEMO_VERIFICATION.md) records the fresh-checkout rehearsal; [release validation](docs/RELEASE_VALIDATION.md) records application tests and the live extraction receipt.

- The local demo uses fictional examples; missing live-provider readiness is expected without keys.
- Unknown dates, fees or credits stay unknown. Courses still need provider confirmation.
- Email delivery, password-recovery email and digests are disabled until a sender is configured and verified. Google sign-in also requires separate configuration.
- Free hosting and provider quotas impose limits; discovery is bounded and is not an unlimited background crawler. See [operational limits and controls](docs/OPERATIONS.md).

## Licence and attribution

Application source is available under the [MIT licence](LICENSE). The backend was developed in [dman1313/CareCredits](https://github.com/dman1313/CareCredits) and reconciled with this frontend; the upstream review remains separate. Third-party models, provider content and dependencies retain their own licences and terms.
