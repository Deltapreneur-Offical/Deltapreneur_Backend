from slowapi import Limiter

from app.core.client_ip import get_client_ip

# Uses client IP as the rate limit key (see get_client_ip and TRUST_PROXY_HEADERS).
limiter = Limiter(key_func=get_client_ip)

# Current rate limits applied:
#   POST /login                  → 5/minute
#   POST /register               → 3/minute
#   GET  /oauth/google/login     → 10/minute
#   POST /refresh                → 20/minute
#   POST /resend-verification    → 3/minute
#
FORGOT_PASSWORD_RATE_LIMIT = "3/minute"
RESET_PASSWORD_RATE_LIMIT = "5/minute"
CHANGE_PASSWORD_RATE_LIMIT = "5/minute"
