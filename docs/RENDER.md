# Render deployment

Deploy `render.yaml` from `codex/v1-integrated-demo`, not the older `main` branch.
Review the paid resource summary before applying. The stack uses Singapore for
all four services: Next.js public web, private FastAPI, private scraper health
and worker, and managed PostgreSQL with external connections disabled.

## Configuration

Set `PUBLIC_FRONTEND_BASE` on the API to the exact HTTPS URL Render assigns to
the web service (no trailing slash). Restart the API after changing it. It
supplies the mutation origin allowlist and public callback/unsubscribe links.
The Docker commands translate Render's private host/port references to URLs.

Enter model and Tavily secrets only in Render. The scraper also needs explicit
model ID, endpoint, weights URL and licence URL. Set
`MODEL_OPEN_WEIGHT_CONFIRMED=true` only after confirming the selected model's
open-weight status. Do not describe fixture runs as successful live AI calls.

Scheduled discovery and email digests start disabled. Enable discovery after
verifying credentials and reviewing the daily job ceiling. Configure SMTP before
enabling digests; the default log mail provider does not deliver mail.

## First operator

Register your own account on `/v1` using a private password. In the API service's
Render shell, run the following with your registered account email:

```sh
python -c 'from database import SessionLocal; from portal_models import Account; import sys; db=SessionLocal(); a=db.query(Account).filter_by(email=sys.argv[1]).one(); a.role="operator"; db.commit(); db.close()' your-email@example.com
```

This deliberately fails if the account does not exist. Do not enable production
demo seed accounts or give anonymous users operator access. Sign out and back in,
then visit `/workspace` to create and review discovery jobs.

## Acceptance checks

1. Web `/health/live` returns success; API connects to PostgreSQL.
2. Sign up, sign in, refresh, and sign out at `/v1`; cookie is Secure/HttpOnly.
3. Operator creates one discovery job; worker leases/completes it and stores
   model provenance. Review and publish a real candidate.
4. Doctor searches, opens provider link, saves sign-up/attendance, reloads the
   record, exports CSV, and prints an affiliation certificate.
5. Redeploy API and confirm records persist in PostgreSQL.
6. Verify no model keys, service tokens or database URLs appear in browser assets.

Public Git repository deployment may require manual deploys. Connect the GitHub
app separately if automatic deployments are desired. Deployment and live AI
verification are not complete merely because this configuration is committed.
