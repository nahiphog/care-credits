# Local setup

[README](../README.md) · [Judge walkthrough](JUDGE_WALKTHROUGH.md) · [Verification record](LOCAL_DEMO_VERIFICATION.md)

## 1. Prerequisites and checkout

Install Git, Node.js **22.13 or newer** (including npm), and **Python 3.12**. Check `git --version`, `node --version`, `npm --version` and `python --version` in your terminal. On macOS/Linux, the Python command below is `python3.12`.

Use a new directory and a terminal without deployment environment variables:

```sh
git clone --branch codex/v1-integrated-demo --single-branch https://github.com/nahiphog/care-credits.git
cd care-credits
git branch --show-current
```

The last command must print `codex/v1-integrated-demo`. The default `main` branch is an older starter, not the submitted integrated application. If a directory named `care-credits` already exists, choose a different destination, for example add `care-credits-demo` to the clone command and enter that directory instead.

**Do not copy `.env`, `.env.local` or deployment env files into this demo checkout.** No keys or cloud services are required. The launcher uses `.data/demo.db` unless a `DATABASE_URL` is already supplied through the shell or root `.env`. `--demo` does not replace that URL: pointing it at a production database can seed fictional data there. A fresh clone does not remove variables inherited by your terminal.

## 2. Install dependencies

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
```

macOS / Linux:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm ci
```

These commands use the virtual environment directly, so no activation script or PowerShell execution-policy change is needed. On Windows, if `python` opens the Microsoft Store, install Python 3.12 or use the full path to your installed interpreter for the first command. PowerShell needs `&` before a quoted executable path; for example, replace the placeholder path in `& 'C:\Path\To\Python312\python.exe' -m venv .venv`. Subsequent commands use the new `.venv` interpreter.

The initial package install needs internet access and can take several minutes. pip may backtrack while resolving `typesafe-sdk` dependencies; allow it to finish. Optional discovery integrations being installed does not mean the offline demo will use them.

## 3. Start the demo

Windows:

```powershell
.\.venv\Scripts\python.exe scripts/dev.py --demo
```

macOS / Linux:

```sh
.venv/bin/python scripts/dev.py --demo
```

This starts three local processes:

| Service | Preferred address | Purpose |
| --- | --- | --- |
| Next.js frontend | `http://127.0.0.1:3000` | Dashboard and same-origin API proxy |
| FastAPI backend | `http://127.0.0.1:8000` | Authentication, catalogue, records and review |
| Scraper health service | `http://127.0.0.1:8002` | Worker readiness; paid discovery stays unavailable without keys |

Each service selects a free nearby port when needed. Wait for **`CareCredits live:`** and open the frontend URL printed on that line. Use that same host and port throughout the session; do not open the backend URL as the dashboard. The first page compilation can take longer than later requests. Keep the terminal open; use Ctrl+C when finished.

To request other ports, append `--frontend-port 3030 --backend-port 8030` to the launch command. The printed addresses remain authoritative.

### Demo sign-in and expected state

| Role | Email | Password |
| --- | --- | --- |
| Doctor | `doctor@carecredits.local` | `CareCredits-demo-2026` |
| Operator | `demo@carecredits.local` | `CareCredits-demo-2026` |

The sign-in screen identifies demo mode. A fresh database contains six fictional published courses and a review queue with asthma, vaccination and reserve-queue examples. The rehearsal showed three pending candidates before publication; the queue changes as fixtures are published and reseeded. Example course dates are relative to the local current date; do not expect dates from old screenshots.

Search for `Diabetes care in general practice`: expect one fictional course from **Primary Care Learning Lab**, in Kuala Lumpur, with **MYR 180** and **4 advertised CPD points**. Example provider links use `example.org` and are not real registrations. Both demo accounts start with a self-reported attendance record and an ECG sign-up record.

This mode is a rehearsal. Signing in with the documented demo credentials refreshes fixture dates, restores seeded learning records and replenishes the review queue as needed. Reloading an already signed-in page preserves your saved changes; a later demo sign-in may restore the seeded examples. Do not store important personal records in this database. To repeat from scratch, use another fresh clone rather than resetting an existing database.

## Verification

At the printed frontend address, open `/health/live` and `/api/v1/config`. Expect `status: "live"` and `demo: true`. At the printed backend address, `/health/ready` checks the database and schema. These are local health checks, not evidence that a model call occurred.

Follow the [judge walkthrough](JUDGE_WALKTHROUGH.md) to check the real browser → API → SQLite path. The doctor and operator routes should work even while live-discovery readiness is false.

For the automated backend suite, use the portable runner. It isolates application/provider settings and uses test databases; do not replace it with a shell-specific `PYTHONPATH` command:

```powershell
.\.venv\Scripts\python.exe scripts/test_backend.py
npm run build:demo
```

On macOS/Linux use `.venv/bin/python` instead. The frontend production build is a separate check; it does not start the backend or switch the running local demo into production.

For the existing browser regressions, leave the demo running and open a second terminal in the same repository:

```powershell
npx playwright install chromium
$env:E2E_BASE_URL = 'http://127.0.0.1:3000'
npm run test:e2e
```

Replace `3000` with the frontend port actually printed by the launcher. On macOS/Linux:

```sh
npx playwright install chromium
E2E_BASE_URL=http://127.0.0.1:3000 npm run test:e2e
```

Linux may also need Playwright's operating-system browser dependencies (`npx playwright install --with-deps chromium`). Browser tests change fictional records and issue local affiliation records; run them only against the disposable local demo. Some recovery/session error cases use mocked responses and do not prove email delivery. The browser suite defaults to port **3111** if `E2E_BASE_URL` is omitted.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Wrong project or missing scripts | Confirm the branch and run commands from the repository root. |
| `Python was not found` / Microsoft Store opens | Use an installed Python 3.12 interpreter, then the `.venv` executable. |
| `ModuleNotFoundError` | Install requirements with the same `.venv` interpreter used to launch. |
| pip dependency resolution seems slow | Wait for the resolver; check the final exit status before launching. |
| Port occupied or a different app appears | Use the URL printed by this launch, not a remembered port. |
| `/health/live` not ready | Read the named service's terminal error; check install completion and retry after the first compile. |
| Sign-in fails or no demo banner | Check `/api/v1/config` for `demo: true`, the selected URL, and use `--demo` in an isolated checkout. |
| `Request origin not allowed` | Use the printed frontend origin; remove conflicting env configuration instead of disabling the origin check. |
| Search looks empty | Clear filters and search the exact fictional title above; live production does not contain these demo fixtures. |
| Fixture changes reset | Demo credential sign-in deliberately refreshes seeded records; use page reload to test persistence within a session. |
| Live discovery unavailable | Expected without keys. Use the fixture review queue; do not submit a paid discovery job for this walkthrough. |
| Password recovery/digests unavailable | Expected until an email sender is configured and verified. |

## Optional live discovery and deployment

The key-free demo is the recommended judging setup. Live reproduction is a separate, credit-consuming operator workflow. Configure secrets privately using [.env.sample](../.env.sample) as the variable reference and [Vercel operations](VERCEL.md) for deployment details. `MODEL_BASE_URL` selects the endpoint; `MODEL_ID` selects the model. Supplying only an endpoint does not establish NVIDIA model usage.

Keep `MODEL_API_KEY`, `TAVILY_API_KEY`, database URLs and internal service credentials server-side. Do not paste them into documentation, commit them, or use `NEXT_PUBLIC_` variables for secrets. Set model identity and provenance explicitly for a live run. Inspect its receipt for actual extraction and token usage; a configured model name or a search with no pages is not execution proof.

Production keeps `DEMO_MODE=false` and uses the existing Vercel Hobby and Neon Free resources. The [operations guide](OPERATIONS.md) explains limits, migrations, maintenance and the intentionally disabled email features. A cloud deployment is not needed to reproduce the local judge walkthrough.
