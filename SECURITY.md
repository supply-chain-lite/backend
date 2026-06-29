# Security Policy

## Supported Versions

Only the latest release of **Supply Chain Lite — Backend v2** receives security patches.

| Version | Supported |
|---------|-----------|
| Latest (`main`) | ✅ |
| Older branches | ❌ |

---

## Reporting a Vulnerability

If you discover a security vulnerability, **please do not open a public GitHub issue.**

Report it privately by emailing:

> **support@summence.com**

Include as much detail as possible:
- A description of the vulnerability and its potential impact
- Steps to reproduce or a proof-of-concept
- Affected endpoint(s), component(s), or configuration(s)
- Any suggested fix (optional)

You can expect an acknowledgement within **48 hours** and a resolution or status update within **7 days**.

---

## Security Features

### Authentication & Sessions
- Passwords are hashed using a strong one-way algorithm before storage — plain-text passwords are never persisted.
- Session tokens are signed **JWT** (via `PyJWT`) with a configurable expiry (`ACCESS_TOKEN_EXPIRE_MINUTES`).
- Tokens are delivered as **HTTP-only cookies** to mitigate XSS-based theft.
- Brute-force protection: accounts are locked after `MAX_ATTEMPTS` consecutive failed logins for `LOCK_TIME_MINUTES` minutes.

### Secrets Management
- All sensitive values (`SECRET_KEY`, SMTP credentials, AWS keys, Redis URL) are loaded exclusively from environment variables / `.env` and are **never hard-coded** in source.
- The `.env` file is listed in `.gitignore` and must never be committed to version control.
- Use `.env.example` as a template — it contains only placeholder values.

### File Uploads
- File uploads are handled via `python-multipart`; validate MIME type and file size limits in your deployment configuration.
- Uploaded artifacts should be stored outside the web root or in a dedicated S3 bucket with restricted ACLs.

### AWS S3
- Grant the IAM user/role only the minimum permissions required for the configured bucket (`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject`).
- Enable S3 bucket versioning and block all public access unless explicitly required.
- Rotate `S3_ACCESS_KEY` / `S3_SECRET_KEY` periodically and prefer IAM instance roles when deployed on AWS infrastructure.

### Database (SQLite)
- The SQLite database file path is controlled by `SQLITE_DB_PATH`.
- Restrict filesystem permissions on the database file so only the application process can read/write it.
- For production deployments that require multi-user or network access, consider migrating to PostgreSQL.

### Transport Security
- Always serve the API behind HTTPS in production (Nginx/Caddy with TLS termination).
- Set `Secure`, `HttpOnly`, and `SameSite=Strict` (or `Lax`) flags on the access-token cookie.
- Configure appropriate CORS origins in `app/main.py` — do **not** use `allow_origins=["*"]` in production.

### Celery / Redis
- Protect the Redis broker (`BROKER_URL`) behind a firewall or VPN; do not expose it publicly.
- Enable Redis authentication (`requirepass`) in production.
- Treat Celery task arguments as untrusted input — validate and sanitize before use.

### Dependency Management
- Dependencies are pinned in `uv.lock`. Run `uv sync` and review the lockfile diff when upgrading.
- Dependabot is configured (`.github/dependabot.yml`) to flag outdated or vulnerable packages automatically.
- Before a release, audit dependencies with:
  ```bash
  uv run pip-audit
  ```

---

## Deployment Hardening Checklist

- [ ] Generate a strong, random `SECRET_KEY` (≥ 32 bytes of entropy, e.g. `openssl rand -hex 32`).
- [ ] Set `ACCESS_TOKEN_EXPIRE_MINUTES` to the shortest practical value for your use case.
- [ ] Serve exclusively over HTTPS with a valid TLS certificate.
- [ ] Restrict CORS to known frontend origin(s).
- [ ] Set `LOG_LEVEL=WARNING` or higher in production to avoid leaking sensitive data in logs.
- [ ] Ensure the `.env` file has `chmod 600` (or equivalent) permissions.
- [ ] Place the SQLite database file outside the project directory and restrict its permissions.
- [ ] Enable Redis authentication and bind it to `127.0.0.1` or a private network interface.
- [ ] Restrict outbound SMTP to the configured relay only.
- [ ] Review and tighten S3 bucket policy and IAM permissions before going live.

---

## Out of Scope

The following are considered out of scope for this security policy:

- Vulnerabilities in third-party dependencies (report those upstream).
- Issues that require physical access to the server.
- Social engineering attacks against maintainers or users.
- Extreme, infrastructure-scale denial-of-service attacks that require massive external resources; application-layer resource-exhaustion vulnerabilities remain in scope.

---

*This policy was last updated: June 2026.*
