# Local demo verification — 30 October 2026

[Setup instructions](SETUP.md) · [Judge walkthrough](JUDGE_WALKTHROUGH.md)

## Scope and environment

The documented judge journey was rehearsed against a fresh clone of
`codex/v1-integrated-demo`, with application code at `e3b8b9c`. The documentation
change does not alter application code or deployment settings.

- Windows, Python **3.12.14**, Node.js **24.19.0**, npm **11.17.0**.
- A newly created Python virtual environment and a fresh `npm ci` installation.
- No copied `.env` or deployment files; application/provider settings were removed
  from the verification process environment before launch.
- SQLite at the disposable checkout's `.data/demo.db`; no production database.
- Frontend `127.0.0.1:3000`, backend `127.0.0.1:8000`, scraper health `127.0.0.1:8002`.

The Windows machine's `python` alias did not point to an installed interpreter,
so the installed Python 3.12 executable was used to create `.venv`; all subsequent
Python commands used `.venv\Scripts\python.exe`. The setup guide documents this
fallback. The initial tool-sandbox launch could not complete its health checks;
launching the same disposable demo outside that sandbox succeeded. No application
change was needed. macOS/Linux commands were documented but were not executed in
this Windows rehearsal.

## Observed browser → API → storage results

| Check | Observed result |
| --- | --- |
| Install and launch | `pip install -r requirements.txt`, `npm ci` and `scripts/dev.py --demo` completed; launcher printed `CareCredits live:`. |
| Backend readiness | HTTP 200 with `status: ready` and `database: ready`. |
| Frontend configuration | `demo: true`; email recovery, digests and Google sign-in unavailable, as expected. |
| Doctor sign-in | Documented local credentials opened Dr Daniel Tan's dashboard with six fictional published courses. |
| Exact diabetes search | One result: Primary Care Learning Lab, Kuala Lumpur, MYR 180, 4 advertised CPD points, demo/unverified labels. |
| Filters and attendance eligibility | Filter modal opened and cancelled; attendance for the future diabetes course was disabled. |
| Personal record | Saved Communication in primary care as attended, completion date 30 September 2026, 2 self-reported points and a private note. Reload retained the values. |
| Progress | Overview showed 5 self-reported points, two attended courses and one signed-up course. |
| CSV | Browser download succeeded. The export API also confirmed the saved course, 2 points and completion date after the date was saved. |
| Affiliation record | Issued a 2026 record, opened the HTML document for Dr Daniel Tan with 5 points and the regulator-certificate disclaimer; history API retained it. |
| Operator review | Dr Aisha Rahman's local account opened the fixture source evidence and published Asthma updates for GPs (demo). |
| Publication and duplicate protection | Exact-title search returned one published result. Repeating publication through the API returned the same course ID; result count stayed one. |
| Access controls | Doctor requests to operator services, candidates, maintenance and catalogue-quality endpoints each returned 403; logout made `/me` return 401. |
| Diagnostics | Operator maintenance and catalogue-quality reads succeeded; `paid_scrape_ready` was false. |
| Browser console | No error-level browser log entries on the manually exercised demo tab. |
| Shutdown | Ctrl+C stopped all three demo listeners; no verification server remained on ports 3000, 8000 or 8002. |

The API checks went through the frontend's same-origin proxy, not an in-memory
mock backend. The database file was confirmed in the disposable checkout.
No production accounts, courses or configuration were changed. No new Tavily or
Nebius discovery call was made.

## Automated checks

- `npm run build:demo`: passed, including TypeScript and static-page generation.
- `npm run test:e2e` against the disposable demo: **10 passed** in Chromium. These
  cover desktop/phone layouts, modal and filter behaviour, profile drafts, expired
  sessions, affiliation-record history, mobile navigation, disabled recovery and
  operator diagnostics. Recovery success is a mocked UI case, not email delivery.
- `.venv\Scripts\python.exe scripts/test_backend.py`: **37 modules, 423 collected
  tests, 421 passed, 2 skipped, no failed modules**. The skipped opt-in/environment
  checks do not establish live-provider execution.
- Documentation checks: all 33 relative file/heading links resolved, code fences
  were balanced, and no API-key or database-credential patterns were found in the
  four changed documentation files.

## Interpretation and limits

This verification establishes the key-free local setup and the fictional
doctor/operator journey. It does not establish new live-model execution, provider
registration, email delivery, cloud quota availability or regulatory compliance.
The separate [live extraction record](RELEASE_VALIDATION.md#extraction-repair-and-successful-live-verification--30-october-2026)
documents the actual NVIDIA/Nebius run.

Fixture dates and seeded records refresh on demo sign-in. The numerical examples
above are observations from this rehearsal, not fixed dates or totals promised
for every later run. Seeded examples and `example.org` source links must never be
presented as real course evidence.
