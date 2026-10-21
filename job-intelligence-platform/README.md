# Scout Job Intelligence — Phase 2 MVP

A local-first starter for a startup serving **job seekers** and **hiring-intelligence customers**. It includes a Next.js job discovery portal, FastAPI backend, PostgreSQL persistence, source-specific ingestion, cross-source deduplication, run history, admin API protection, scheduled collection worker, Docker Compose, and an initial Alembic migration.

> Coverage is connector-based, not universal. Some job boards disallow automation or require commercial API agreements. Do not bypass logins, CAPTCHAs, access controls, or terms.

## WhatsApp-first Bengaluru rental search

This backend also includes a WhatsApp-only renter experience. A renter messages **Hi** to your WhatsApp Business number, then answers three short questions: locality, maximum monthly rent, and bedrooms. The bot returns up to three matches. There is no renter web app in this flow.

Listings must come from owners, authorized partners, or a licensed feed. This project does not scrape 99acres, Housing.com, NoBroker, or other portals. A match is shown only when it is marked available and owner-confirmed within the past 14 days. Contact links are shared only when `contact_share_allowed` is true. This freshness check improves trust but cannot independently prove property details; encourage users to visit and verify before paying.

### Configure WhatsApp

1. Create/configure a Meta WhatsApp Business Cloud API app and a public HTTPS webhook URL: `https://YOUR_HOST/api/whatsapp/webhook`.
2. Set `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_VERIFY_TOKEN`, and `WHATSAPP_APP_SECRET` in `.env`. Keep these server-side. The webhook verifies Meta's challenge and validates `X-Hub-Signature-256` on each event.
3. Subscribe the Meta app to the WhatsApp `messages` webhook field. The API is intentionally not usable until all WhatsApp credentials are configured.
4. Apply the database migration with `docker compose run --rm migrate` (or your normal deployment migration step), then start/restart the API.
5. Set the Graph API version in `WHATSAPP_GRAPH_VERSION` to a version supported by your Meta app before deployment.

### Add and maintain rental listings

Operators can add owner-authorized inventory using the admin API. Set `verified: true` only after confirming with the owner that the property is still available. Refresh that confirmation at least every 14 days. Example:

```bash
curl -X POST http://localhost:8000/api/admin/rentals \
  -H 'Content-Type: application/json' -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  -d '{"title":"Sunny 2 BHK near metro","locality":"Indiranagar","rent":42000,"bedrooms":2,"furnishing":"semi-furnished","contact_phone":"919876543210","contact_share_allowed":true,"source_name":"owner","verified":true}'
```

Use `GET /api/admin/rentals` to review inventory. `PATCH /api/admin/rentals/{id}` accepts `{"verified":true}` to refresh an owner check, or `{"available":false}` when rented. Admin routes require `X-Admin-Token`.

Renter commands: `Hi`/`SEARCH` starts a search, `RESET` restarts preference capture, and `STOP` opts out. A fresh inbound message is required to restart after opt-out (`START`). The backend stores the phone number, current search preferences, and opt-out state to run the conversation.

The pilot currently supports plain-text replies, one locality, a maximum monthly rent, and bedroom count. It uses locality substring matching. It does not yet support map radius searches, multiple areas, automatic listing ingestion, duplicate detection, scheduled alerts, language selection, or owner self-service listing intake. No WhatsApp credentials or real listing feed are included in this repository.

## Supported connectors

| Connector | Source setup `kind` | Required `config_json` |
|---|---|---|
| Greenhouse public Job Board API | `greenhouse` | `{"board_token":"acme"}` |
| Lever public postings API | `lever` | `{"site":"acme"}` |
| Ashby public Job Postings API | `ashby` | `{"job_board_name":"acme"}` |
| SmartRecruiters public postings | `smartrecruiters` | `{"company_identifier":"acme"}` |
| Adzuna job-search API (requires approved app credentials) | `adzuna` | `{"what":"software engineering","where":"Bengaluru","country":"in","max_pages":3}` |
| Single page with public JSON-LD JobPosting | `jsonld` | optional `{"url":"https://company.example/careers"}` |
| Public careers page crawler, bounded to same origin and robots policy | `career_page` | optional `{"max_pages":8}` |

`ADZUNA_APP_ID` and `ADZUNA_APP_KEY` must be configured in the backend environment for Adzuna and are never stored in the source JSON. Create distinct Adzuna sources for role/location query segments, with a modest `max_pages` value and within the API account limits. The Adzuna search API requires `app_id` and `app_key` query parameters and returns job-ad listings; Scout loads credentials from environment variables and redacts them from stored ingestion errors. Review Adzuna API terms and permitted downstream use before productizing. `company_name` and `website_url` can also be passed when creating a source. Provider identifiers are public board slugs/identifiers, not secret API credentials. Source creation defaults to disabled until a human confirms applicable source terms; the admin screen has an explicit policy-review checkbox. The generic career-page crawler also checks robots.txt and follows a bounded number of same-origin links.

## Run locally with Docker

1. Copy `.env.example` to `.env` and replace both placeholder secrets with strong values:

```bash
cp .env.example .env
# Set POSTGRES_PASSWORD in .env as well. Generate secrets with: openssl rand -hex 32
```

2. Set `NEXT_PUBLIC_API_URL=http://localhost:8000` for local development (for production, set this to the public HTTPS API URL and set `CORS_ORIGINS` to the portal’s public origin). Start the complete stack:

```bash
docker compose up --build -d
```

Docker Compose starts PostgreSQL, runs Alembic migrations, and then starts the API, portal and scheduled ingestion worker. View logs with `docker compose logs -f api web worker migrate`.

Portal: `http://localhost:3000`; API: `http://localhost:8000`; interactive OpenAPI: `http://localhost:8000/docs`; source operations console: `http://localhost:3000/admin`; companies: `http://localhost:3000/companies`; intelligence preview: `http://localhost:3000/intelligence`.

For frontend-only local development, use `cd web && cp .env.example .env.local && npm install && npm run dev` and set `NEXT_PUBLIC_API_URL=http://localhost:8000` in `web/.env.local`.

## Create a source

Example Greenhouse source:

```bash
curl -X POST http://localhost:8000/api/admin/sources \
  -H 'Content-Type: application/json' -H "X-Admin-Token: $ADMIN_API_TOKEN" \
  -d '{"name":"Acme","company_name":"Acme","kind":"greenhouse","base_url":"https://boards.greenhouse.io/acme","config_json":{"board_token":"acme"},"terms_reviewed":true,"enabled":true}'
```

The returned source ID is used for an immediate crawl:

```bash
curl -X POST http://localhost:8000/api/admin/ingest/1 -H "X-Admin-Token: $ADMIN_API_TOKEN"
```

To ingest all enabled sources, call `POST /api/admin/ingest-all`. Runs also happen on the worker's schedule (default 30 minutes; minimum configured interval is five minutes). `ADMIN_API_TOKEN` is checked on every administrative API request. Keep it server-side; never put it in the browser or frontend environment.

## India-first aggregation with Adzuna

After obtaining approved credentials from Adzuna, set `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` in the backend environment. In `/admin`, create an `adzuna` source with a public base URL such as `https://api.adzuna.com/v1/api/jobs/in/search/1` and config JSON like:

```json
{"what":"generative AI","where":"Bengaluru","country":"in","results_per_page":50,"max_pages":3,"max_days_old":30}
```

Create several carefully chosen role/location slices (for example, AI/ML, platform engineering, SRE, data engineering, and software engineering across major Indian hubs). Adzuna is a query-driven feed, not a one-time export of every vacancy. Confirm the applicable API licence allows your intended aggregation and paid redistribution before commercially exposing collected results.

## API overview

- `GET /api/health`
- `GET /api/jobs?q=&location=&company=&employment_type=&remote=&posted_within_days=&fresh_within_days=30&limit=&offset=` — hides results not seen in a successful source run within 30 days by default; each result includes `last_seen_at`.
- `GET /api/jobs/{id}`
- `GET /api/jobs/{id}/sources` — active source provenance and original listing URLs
- `GET /api/companies?q=&limit=&offset=`
- `GET /api/sources` — safe metadata only; no connector config
- `GET /api/analytics/overview`
- `GET /api/analytics/top-companies`
- `GET /api/analytics/locations`
- `GET /api/analytics/roles`
- `GET /api/analytics/skills`
- `POST /api/admin/sources` — admin token required
- `POST /api/admin/companies/import-csv` — seed the company directory from `data/company-seed-template.csv` format, with optional source auto-registration
- `GET /api/admin/discover-careers?website_url=https%3A%2F%2Fcompany.example&company_name=Company` — discover reviewable source candidates
- `PATCH /api/admin/sources/{id}` — admin token required
- `POST /api/admin/ingest/{id}` — admin token required
- `POST /api/admin/ingest-all` — admin token required
- `GET /api/admin/runs` — admin token required

## Data model and deduplication

- `companies`: normalized company identity and official careers URL.
- `jobs`: canonical normalized vacancy record, salary fields when supplied, and heuristic skill tags extracted from title/description.
- `job_listings`: source-specific references to a canonical vacancy, preserving multiple provider URLs and provenance. The preferred displayed application link favors company career pages and direct ATS links over an aggregator redirect when both records appear.
- `sources`: connector configuration and operational status.
- `ingestion_runs`: durable history of success/failure and collection counts.

Every source is created disabled unless an operator explicitly sets `terms_reviewed=true`; terms URL and approval timestamp are retained. The cross-source dedupe key now also includes posting day and normalized description, reducing accidental merges of similar requisitions. It remains heuristic: provider requisition IDs are the stable within-source identity, and ambiguous cross-source matches need review. A successful snapshot deactivates missing source listings only when it is not empty or unexpectedly smaller than the previous active inventory (default 50% threshold; configurable per source with `min_snapshot_ratio`). Incomplete snapshots retain earlier listings and are marked `incomplete`. Search and analytics hide jobs not seen in 30 days; use `fresh_within_days` to change the search window.

## Operational and security notes

- Production uses PostgreSQL and schema migration (`alembic upgrade head` in the API container).
- The worker is a separate service so scheduled polling does not depend on API request traffic. Keep one worker replica and avoid concurrent manual runs across replicas until a database advisory lock/queue is configured. The local lock prevents duplicate runs within one process. SmartRecruiters pagination is capped at 100 pages; exceeding the cap fails the run so it cannot close inventory.
- Admin endpoints fail closed when `ADMIN_API_TOKEN` is absent and use constant-time token comparison.
- Source URL validation rejects obvious private-network SSRF targets; the generic crawler follows a bounded number of same-origin links and checks `robots.txt` before crawling. This is a practical safeguard, not a substitute for network-level egress controls or a security review.
- Provider APIs are called on their public endpoints; confirm current provider terms, allowed use, rate limits, and branding requirements before commercial deployment.
- Configure TLS/reverse proxy, firewall egress, managed secrets, backups, retention/deletion policy, dependency scanning, structured logs and alerting before opening to the public.
- The admin UI is available at `/admin`; it supports token-based source registration, career-page discovery, ingestion and run history. To import a company CSV, POST the raw UTF-8 CSV to `/api/admin/companies/import-csv` with `Content-Type: text/csv` plus the admin token.
- The commercial analytics endpoints are a **pilot surface, not a complete paid subscription system**. Before charging customers, add user accounts, organization tenancy, billing/webhooks, API quotas, entitlements, audit logging, and data licensing review.

## Validation

Run `cd backend && pip install -r requirements-dev.txt && pytest`. Then run `python -m compileall app worker.py`. Use a test PostgreSQL instance before a production deployment.
