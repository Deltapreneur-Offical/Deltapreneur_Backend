# CoBrother — Python Backend

Production-oriented FastAPI backend for CoBrother: authentication, domain auctions, venture marketplace, technology/cocreation, creator profiles & auctions, Google Meet scheduling, payments, analytics, admin, and WebSockets.

---

## Prerequisites

- Python 3.11+
- PostgreSQL 14+
- pip

---

## Quick start (local)

```bash
cd cobrother_backend
python -m venv venv   # or .venv

# Windows
venv\Scripts\activate

# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` with your database URL, JWT secrets, mail settings, and third-party keys (see [Environment variables](#environment-variables)).

### Create and migrate the database

```bash
psql -U postgres -c "CREATE DATABASE cobrother_dev;"
alembic upgrade head
alembic heads    # should show exactly one head (b85582604c7b or later)
```

After pulling teammate changes, always run `alembic upgrade head` before starting the API. If two Alembic heads appear locally, upgrade to the merge revision in the repo — do not skip migrations.

For a full graph + database check (recommended on servers):

```bash
python scripts/repair_alembic_database.py
```

### Run the API

**Recommended (avoids stale Windows env overriding `.env` for Google OAuth):**

```bash
# Git Bash / macOS / Linux
bash run_dev.sh

# PowerShell
.\run_dev.ps1
```

Or manually:

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Use `http://` for local port 8000** — Uvicorn does not serve TLS; `https://127.0.0.1:8000` causes `ERR_SSL_PROTOCOL_ERROR`.

- API: `http://127.0.0.1:8000`
- OpenAPI docs: `http://127.0.0.1:8000/docs`
- Health: `GET /health`
- Readiness (DB ping): `GET /ready`

---

## Environment variables

Copy `.env.example` to `.env`. **Never commit `.env`.**

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL (asyncpg or psycopg2 URL) |
| `TEST_DATABASE_URL` | Separate DB for pytest (must differ from `DATABASE_URL`) |
| `JWT_SECRET_KEY` | Access token signing secret |
| `JWT_REFRESH_TOKEN_PEPPER` | Refresh token HMAC pepper (32+ chars) |
| `MAIL_*` | SMTP — verification, password reset, **meeting emails** |
| `BACKEND_BASE_URL` | Public API base URL |
| `FRONTEND_BASE_URL` | SPA origin (OAuth redirects, CORS, meeting email links) |
| `CORS_ALLOW_ORIGINS` | Comma-separated origins; required in production |
| `ENVIRONMENT` | `development` or `production` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | Google OAuth (login + Calendar/Meet for meeting confirm) |
| `SUPABASE_*` | Supabase Storage (S3-compatible uploads) |
| `RAZORPAY_*` | Payments |
| `RESELLERCLUB_*` / `DOMAIN_PROVIDER` | Domain registration (ResellerClub; see `docs/RESELLERCLUB_DEMO.md`) |
| `OPENPROVIDER_*` | Legacy domain registrar |

In **development**, when `CORS_ALLOW_ORIGINS` is empty, localhost origins including Vite `:5173` are allowed automatically.

---

## Architecture

```
app/
├── main.py                 # App factory, lifespan, middleware, routers
├── core/                   # Config, DB, auth deps, rate limits, logging
├── controller/             # HTTP routers (auth, auction, venture, domain, admin…)
├── service/                # Business logic
├── repository/             # Data access
├── entity/                 # SQLAlchemy models
├── model/                  # Pydantic request/response schemas
├── integrations/           # Razorpay, Supabase, OpenProvider, Google Calendar/Meet
├── websocket/              # Auction + notification WebSocket handlers
└── tests/                  # pytest suite
alembic/                    # Database migrations
```

**Sync DB** (`get_db`): auth, admin, analytics, meetings.  
**Async DB** (`get_async_db`): auctions, ventures, domains, payments, cocreation.

---

## API surface (summary)

| Area | Prefix | Notes |
|---|---|---|
| Auth | `/api/v1/auth` | Register, login, refresh, OAuth, password reset |
| Domains | `/api/v1/domain` | Listings, verification, registration |
| Ventures | `/api/v1/venture` | CRUD, GSTIN, pitches, deals, co-venture applications |
| Technology | `/api/v1/technology`, `/api/v1/cocreation` | **Dual mount** — listings, purchases, auctions |
| Technology metadata | `/api/v1/technology/categories` | Static category labels (not listings) |
| Creator profiles | `/api/v1/creator`, `/api/v1/community` | **Dual mount** |
| Creator auctions | `/api/v1/creator-auction`, `/api/v1/community-auction` | **Dual mount** — listing fee, winner payment |
| Meetings | `/api/v1/meetings` | Request, confirm (Google Meet), cancel + email |
| Likes | `/api/v1/likes` | Toggle likes, counts |
| Analytics | `/api/v1/analytics` | Profile / venture / software views |
| Admin | `/api/v1/admin` | Listings, verify technology/domains, forward, takedown |
| WebSockets | `/ws` | SockJS/STOMP auction + notification streams |
| Health | `/health`, `/ready` | Ops endpoints |

### Important technology endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/v1/technology/all` | Public software listings |
| `GET` | `/api/v1/admin/technologies` | Admin Technology tab (all listings) |
| `POST` | `/api/v1/admin/softwares/{id}/mark-verified` | Admin verifies a listing |

Full route list: `/docs` when the server is running.

---

## Meetings & email

Creator auction participants can schedule Google Meet sessions:

1. **Request** — bidder pays participation fee, submits meeting request
2. **Confirm** — profile owner (Google OAuth) creates Calendar event + Meet link
3. **Email** — SMTP notifications on request, confirm (Meet link to both parties), and cancel

Requires `MAIL_*` env vars. If mail is not configured, meetings still work but emails are skipped (logged as warnings).

---

## Background jobs (lifespan)

1. **Auction timer** — ends expired domain, venture, software, and creator auctions
2. **Scheduler (every 30s)** — registration retries, stale order expiry

---

## Testing

```bash
psql -U postgres -c "CREATE DATABASE cobrother_test;"
# Set TEST_DATABASE_URL in .env (must differ from DATABASE_URL)

pytest app/tests -v
pytest app/tests/auction -v
pytest app/tests/community -v
pytest app/tests/admin/test_java_parity_routes.py -v
```

**Safety:** Tests refuse destructive operations when `TEST_DATABASE_URL == DATABASE_URL`.

---

## Alembic migrations

```bash
alembic heads          # exactly one head expected
alembic upgrade head
alembic history
```

### Team workflow

Always chain new migrations from the current head so parallel branches do not diverge:

```bash
git pull
python scripts/repair_alembic_database.py   # or: alembic upgrade head
alembic heads                                 # must show exactly one head
# make schema changes, then:
alembic revision --autogenerate -m "describe change"
```

If two heads appear after merging branches (two teammates added migrations from the same parent):

```bash
python scripts/merge_alembic_heads.py
git add alembic/versions/
git commit -m "chore: merge alembic heads"
alembic upgrade head
```

Deploy blocks on multiple heads (`scripts/check_alembic_graph.py` in CI). The merge file must be committed before deploy succeeds.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Can't locate revision identified by '…'` | `alembic upgrade head`; or drop/recreate local DB |
| `column community_auctions.winner_payment_* does not exist` | Run `alembic upgrade head` |
| Admin Technology tab empty | Pull latest; endpoint now returns all listings (not purchases only) |
| `GET /technology/all` returns `["AI",…]` | Pull latest; categories moved to `/technology/categories` |
| Google OAuth wrong redirect on Windows | Use `run_dev.ps1` / `run_dev.sh`; clear system `GOOGLE_OAUTH_*` env vars |
| Meeting emails not sent | Configure `MAIL_*` in `.env` |
| Google Meet confirm 400 | Profile owner must sign in with Google (refresh token stored) |
| CORS blocked from Vite `:5173` | `ENVIRONMENT=development` or set `CORS_ALLOW_ORIGINS` |
| Browser CORS errors from `https://cobrother.com` | Set `FRONTEND_BASE_URL=https://cobrother.com` and `BACKEND_BASE_URL=https://backend.cobrother.com`; ensure `CORS_ALLOW_ORIGINS` includes the SPA origin — see [`deploy/nginx-backend.conf.example`](deploy/nginx-backend.conf.example) |
| WebSocket `/ws/notifications` fails in browser | Ensure nginx proxies `/ws/` with `Upgrade` headers — see [`deploy/nginx-backend.conf.example`](deploy/nginx-backend.conf.example); enable WebSockets in Cloudflare |

---

## Production checklist

- [ ] `ENVIRONMENT=production`
- [ ] `CORS_ALLOW_ORIGINS` set to frontend origin(s)
- [ ] Secrets in environment / secret manager — not in git
- [ ] `alembic upgrade head` on deploy
- [ ] Health probes on `/health` and `/ready`
- [ ] Google OAuth redirect URIs match production domains
- [ ] SMTP configured for auth + meeting emails
- [ ] Separate DB for tests

See also: [`pre_production_checklist.txt`](pre_production_checklist.txt)

---

## License

Proprietary — CoBrother team.
