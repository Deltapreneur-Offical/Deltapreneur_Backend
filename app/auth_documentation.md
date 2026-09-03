# Auth module documentation

This document describes the authentication HTTP API in
`app/controller/auth/auth_controller.py` and the implementation in
`app/service/auth/auth_service.py`, plus related security and repositories.

## Overview

The auth module provides:

- User registration (email + password)
- Email/password login
- **Google OAuth** via backend redirect only (`GET .../oauth/google/login`)
- Access-token refresh and logout (refresh-token rotation)
- Resend verification email and email verification link
- Forgot password and reset password (opaque token table)
- Change password and set password (authenticated)
- Current user (`/me`) and an admin role smoke route (disabled when `ENVIRONMENT=production`)

Session tokens are stored in **HttpOnly cookies** (`access_token`, `refresh_token`).
The API also accepts `Authorization: Bearer` for access tokens (e.g. Swagger).

**Prefixes**

- `/api/v1/auth` — primary API
- `/api/auth` — legacy mirror for the same handlers where implemented

**Ops / health** (not under `/auth`):

- `GET /health` — liveness
- `GET /ready` — database connectivity
- `GET /metrics` — basic uptime when `EXPOSE_METRICS=true`

## Request models (`app/model/auth/`)

| Model | Fields |
| --- | --- |
| `RegisterRequest` | `email`, `password` |
| `LoginRequest` | `email`, `password` |
| `RefreshTokenRequest` | `refreshToken` (optional if cookie set) |
| `LogoutRequest` | `refreshToken` (optional if cookie set) |
| `ResendVerificationRequest` | `email` |
| `ForgotPasswordRequest` | `email` |
| `ResetPasswordRequest` | `token`, `password` |
| `ChangePasswordRequest` | `currentPassword`, `newPassword` |
| `SetPasswordRequest` | `newPassword` |

## Session cookies

| Cookie | Purpose |
| --- | --- |
| `access_token` | JWT access token (HttpOnly) |
| `refresh_token` | Opaque refresh token (HttpOnly) |

Configured via `AUTH_COOKIE_DOMAIN` and `AUTH_COOKIE_SAMESITE` (see `.env.example`).

Frontend must call the API with **`credentials: 'include'`** so cookies are sent.

For **`POST /refresh`** and **`POST /logout`** when using the refresh cookie, also send header
**`X-CSRF-Token`** with the value of the `csrf_token` cookie (readable by JS).
Body-only refresh (e.g. Swagger) does not require CSRF.

## Google OAuth (redirect only)

1. Browser → `GET /api/v1/auth/oauth/google/login`
2. Backend → Google consent screen
3. Google → `GET /api/v1/auth/oauth/google/callback?code=...&state=...`
4. Backend sets session cookies and redirects to  
   `{GOOGLE_OAUTH_SUCCESS_REDIRECT}?success=1&newUser=true|false`  
   (or `?error=...` on failure — **no tokens in the URL**)
5. Frontend → `GET /api/v1/auth/me` with `credentials: 'include'`

Requires `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and the callback URI registered in Google Cloud Console.

## Endpoints (summary)

### Register / login

- **Register** — email/password; soft-deleted emails are reactivated.
- **Login** — sets session cookies + returns JSON `data` (Swagger-friendly).
- Anti-enumeration on duplicate register email.

### Refresh / logout

- **Refresh** — reads `refresh_token` cookie (or optional body); rotates token; updates cookies.
- **Logout** — revokes session chain; clears cookies.

### Google

- `GET /oauth/google/login` — start flow
- `GET /oauth/google/callback` — Google redirect target (do not call from frontend)

### Password / verification

- Forgot / reset / change / set password — see previous sections in team docs.
- Change/set password **clears** session cookies (re-login required).

### `GET /me`

Requires valid access token (cookie or Bearer). Returns `id`, `email`, `role`, `emailVerified`.

## Client IP

Uses `app/core/client_ip.get_client_ip(request)` for refresh rows and rate limits.
Set `TRUST_PROXY_HEADERS=True` only behind a trusted reverse proxy.

## Database migrations

Alembic head for auth hardening: **`c4e8f1a2b3d6`** (`uq_users_phone_number`, `otp` column widened for hashes).
Run `alembic upgrade head` before deploy.

## Environment variables

See `backend_py/.env.example` for the full list. Google OAuth requires:

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_OAUTH_REDIRECT_URI` (optional; default derived from `BACKEND_BASE_URL`)
- `GOOGLE_OAUTH_SUCCESS_REDIRECT` (optional; default `{FRONTEND_BASE_URL}/auth/google/callback`)
- `FRONTEND_BASE_URL`, `BACKEND_BASE_URL`
- `CORS_ALLOW_ORIGINS` in production (must include your SPA origin; credentials enabled)

## Example flows

**Email/password**

1. `POST /register` → verify email  
2. `POST /login` (cookies set)  
3. `GET /me` with credentials  
4. `POST /refresh` when needed  
5. `POST /logout`

**Google**

1. Navigate to `GET /oauth/google/login`  
2. After redirect to SPA with `?success=1`, call `GET /me` with credentials
