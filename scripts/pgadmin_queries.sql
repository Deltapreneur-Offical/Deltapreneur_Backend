-- CoBrother — useful pgAdmin / psql queries
-- Database: postgres on AWS RDS
-- Main user table: public.users (role column uses enum user_role_enum)

-- 1) Check migration / schema version
SELECT version_num FROM alembic_version;

-- 2) List all tables
SELECT schemaname, tablename
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;

-- 3) View all users (roles, status)
SELECT
    id,
    email,
    firstname,
    lastname,
    role,
    active,
    email_verified,
    profile_complete,
    auth_provider,
    oauth_provider,
    is_deleted,
    created_at,
    updated_at
FROM users
ORDER BY created_at DESC;

-- 4) Count users by role
SELECT role, COUNT(*) AS count
FROM users
WHERE is_deleted = false
GROUP BY role
ORDER BY role;

-- 5) Find a specific user by email
-- SELECT id, email, role, active FROM users WHERE lower(email) = lower('you@example.com');

-- 6) Make a user ADMIN (admin dashboard + admin APIs)
-- UPDATE users
-- SET role = 'ADMIN', updated_at = NOW()
-- WHERE lower(email) = lower('you@example.com');

-- 7) Make a user COBROTHER (CoBrother portal — different from ADMIN)
-- UPDATE users
-- SET role = 'COBROTHER', updated_at = NOW()
-- WHERE lower(email) = lower('you@example.com');

-- 8) Reset to normal registered user
-- UPDATE users
-- SET role = 'USER', updated_at = NOW()
-- WHERE lower(email) = lower('you@example.com');

-- 9) Reactivate account / verify email if login blocked
-- UPDATE users
-- SET active = true, email_verified = true, is_deleted = false, updated_at = NOW()
-- WHERE lower(email) = lower('you@example.com');

-- Valid role values (enum user_role_enum): USER, GUEST, ADMIN, COBROTHER
-- Frontend admin pages check role = ADMIN (not COBROTHER).
