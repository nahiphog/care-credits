# Oracle Always Free deployment

Use the existing `docker-compose.yml` with `compose.oracle.yml`. This runs the
complete app on one Linux VM. Only Caddy exposes public HTTP/HTTPS ports;
PostgreSQL has no host port, and existing frontend/API host ports bind loopback.
PostgreSQL and Caddy certificate state use persistent Docker volumes.

## Provisioning

In the Oracle console, verify the shape is Always Free eligible, the region has
capacity, and all resource estimates are zero before creating anything. Target
an Ubuntu Ampere A1 VM within the account's free allocation (currently documented
as 2 OCPUs and 12 GB for Always Free tenancies). Verify the actual account limits;
do not substitute a paid shape automatically. Include boot disks in the free
storage allowance and avoid paid load balancers or NAT gateways.

Allow TCP 80/443 publicly and restrict SSH to the operator's IP in both Oracle
network rules and the host firewall. Use SSH keys. Install Docker Engine and the
Compose plugin from Docker's official Ubuntu repository. Confirm that the
selected images and dependencies build on ARM64 before announcing deployment.

## Application setup

Clone `https://github.com/nahiphog/care-credits.git` and check out
`codex/v1-integrated-demo`. Point a hostname you control to the public VM IP.
The hostname must resolve publicly for Caddy to obtain a trusted TLS certificate.

Create `.env.oracle` on the VM with mode 600. Never commit it. Required fields:

```dotenv
SITE_HOST=your-hostname.example
POSTGRES_PASSWORD=replace-with-random-hex-secret
SCRAPER_SERVICE_TOKEN=replace-with-another-random-hex-secret
DAILY_SCRAPE_ENABLED=false
DIGEST_ENABLED=false
```

Use two independently generated `openssl rand -hex 32` values for the secrets.
Hex avoids database-URL escaping problems. Enter model/Tavily settings privately
using the explicit fields documented in `.env.sample`. Do not enable scheduled
discovery until the credentials and a single live job have been verified.

```sh
docker compose --env-file .env.oracle -f docker-compose.yml -f compose.oracle.yml config --quiet
docker compose --env-file .env.oracle -f docker-compose.yml -f compose.oracle.yml up -d --build
docker compose --env-file .env.oracle -f docker-compose.yml -f compose.oracle.yml ps
```

Do not print the expanded Compose configuration: it contains secrets.

Register the owner's account on `/v1`. Promote only that account using the
operator command in `docs/RENDER.md`, run inside `docker compose ... exec backend`.
Demo seed accounts are disabled in production.

## Verification and operations

Verify HTTPS, signup/login/logout, operator discovery and review, doctor records,
CSV export, and certificate printing. Restart the stack and verify records still
exist. A healthy web server alone does not prove live AI discovery works.

Keep encrypted database backups off this VM, test restoration, and patch the OS
and container images regularly. Never use `docker compose down -v` on a populated
deployment: it deletes database and certificate volumes. Free cloud capacity and
quotas are subject to provider policies; keep a portable database backup.

Hosting may be free within the account allocation. Model/Tavily calls, a custom
domain, and any resources outside free limits are separate costs.
