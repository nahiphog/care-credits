# Coding-agent handoff — CareCredits full MVP

Use this prompt to continue implementation against the living specification:

> Read `docs/SDD.md` (current version in the document header), `README.md`, and the current code before editing. Confirmed scope: Malaysia-only CPD discovery and personal sign-up/attendance/progress tracking; three application services; PostgreSQL owned only by the backend; real Tavily usage inside scraper jobs; open-weight application AI; **DEC-09** owned catalogue; **DEC-10** engagement (digest, suggestions, affiliation certificate); **DEC-11** API connect + Jev exists/new/uncertain + save new events. Preserve the distinction between confirmed requirements, proposed defaults, and unresolved OPEN-* decisions.
>
> **Architecture (current):** Python FastAPI backend (`backend/`), separate Python scraper (`scraper/`), TypeScript/Next.js frontend (`frontend/`). The scraper never opens PostgreSQL; it uses authenticated `/internal/v1/catalogue/*` connect endpoints. Doctors and the public profile always read the owned catalogue — never call Tavily on doctor search.
>
> **Credentials:** ask the developer to run `python3 scripts/setup_integrations.py` in their own terminal when live testing is needed. It prompts privately and saves into the ignored `.env`. Never ask for keys in chat. Do not write OPEN-03 sample model identity into `.env` or `.env.sample` (blank fields + `env_or_provisional()` labels). Never expose Tavily/model keys, database credentials, or service tokens in frontend code or logs. Continue independent work while keys are unavailable; never fake live success or invent a T-10 pass.
>
> **Spend gate:** operator enqueue / daily scrape / interrupted-job retry return 409 unless `paid_scrape_ready`; job claim returns 204 unless ready; workers skip Search/Firehose when the open-weight model is not ready.
>
> **DEMO-01:** offline FIXTURE path is labelled on `/live` and must stay honest. Live Search/Extract + open-weight extraction stays owner-blocked until `MODEL_API_KEY` and `MODEL_OPEN_WEIGHT_CONFIRMED=true` (do not auto-confirm). BUILD-08 / T-10 need that live evidence. OPEN-01 / OPEN-09 remain owner answers.
>
> **UI honesty (UI-01):** loading / empty / error / retry — no false `0` CPD counts, false empty queues, or silent failed preference loads. Prefer `…` / `Couldn't load…` / Retry.
>
> **Doctor experience:** session cookies + ownership isolation; Malaysia city/state; FIND-01 filters; source-backed details; personal records with reversible attendance; progress exclusions disclosed; suggestions advisory only. Clicking an external registration link must not register the doctor.
>
> Link changes to requirement and test IDs. Keep SDD status claims current. Mocked suite success is not live DEMO-01. Report remaining gaps without credentials.
