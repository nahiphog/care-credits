# Care Credits

Care Credits helps Malaysian doctors discover source-backed CPD courses and keep personal learning records. The public dashboard is at `/`; operator tools are at `/workspace`. Alternative dashboards are archived and are not public entry points.

Production: https://care-credits-hackathon.vercel.app/

## One application, one backend

- `app/`, `components/`, `lib/`: Next.js frontend and same-origin API proxy.
- `backend/routers/`: auth, doctor/catalogue, operator, internal worker and public HTTP routes.
- `backend/services/portal.py`: application services, validation, session/origin policy and lifecycle.
- `backend/models/schema.py`: canonical schema v17, compatible with the existing Neon database.
- `backend/database/`: shared engine/session/metadata registry.
- `backend/main.py` and `backend/portal_models.py`: compatibility entrypoints for existing workers and tests.
- `scraper/`, `shared/`, `config/`: week-key discovery pipeline and contracts, including evidence validation and operator review.

The previous root refactor and deployed snapshot are reconciled here. There is no separate `deployments/web` backend. See [reconciliation decisions](docs/RECONCILIATION.md).

## Local development and tests

```sh
python -m pip install -r requirements.txt
npm ci
python scripts/dev.py --demo
```

Demo data is fictional and disabled in production. Run backend tests from this root:

```sh
PYTHONPATH=.:backend python -m unittest discover -s backend/tests -v
npm run build:demo
```

## Hosting

The existing Vercel Hobby project runs Next.js and FastAPI, using the existing Neon Free database. Configure secrets privately in Vercel; never commit environment files. No schema migration is required for the repository reconciliation. See [Vercel operations](docs/VERCEL.md).

Live discovery requires configured Tavily and Nebius credentials. Courses remain unverified source claims until reviewed; personal attendance and CPD totals are self-reported, not regulator certification. Existing source/evidence, review, authentication and audit controls are retained.
