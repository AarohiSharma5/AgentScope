# Security Policy

We take the security of AgentScope seriously. Thank you for helping keep the
project and its users safe.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x | ✅ |
| < 1.0 | ❌ (please upgrade to 1.0.x) |

Security fixes are released against the latest `1.0.x` line.

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues,
discussions, or pull requests.**

Instead, report privately using one of:

1. **GitHub Security Advisories** — open a private report via the repository's
   **Security → Report a vulnerability** tab (preferred).
2. **Email** — **aarohisharma5005@gmail.com** with the subject line
   `SECURITY: AgentScope`.

Please include as much of the following as you can:

- A description of the vulnerability and its impact.
- Steps to reproduce (proof-of-concept, affected endpoint/component, config).
- The version / commit affected.
- Any suggested remediation.

## What to expect

- **Acknowledgement** within 3 business days.
- An initial **assessment and severity** rating shortly after.
- We will keep you informed of remediation progress and coordinate a disclosure
  timeline with you. We aim to ship a fix for confirmed high-severity issues
  promptly and will credit reporters who wish to be acknowledged.

Please act in good faith: give us reasonable time to remediate before any public
disclosure, and avoid privacy violations, data destruction, or service
disruption while researching.

## Security-relevant design notes

AgentScope ships several security features (see the
[Deployment guide](docs/deployment.md) for hardening):

- **Authentication is opt-in** (`AUTH_ENABLED`, default `false`). Enable it and
  set a strong `JWT_SECRET` before exposing the platform publicly.
- **Passwords** are hashed with PBKDF2-SHA256; **API keys** are stored hashed and
  shown in full only once at creation.
- **JWTs** are HS256-signed; set a strong, unique `JWT_SECRET` in production.
- **RBAC** (Admin/Developer/Viewer) plus organization and project **isolation**.
- **Rate limiting** and **audit logs** for security-relevant actions.
- **Parameterized queries** via SQLAlchemy (no string-built SQL).
- **CORS** is restricted to configured origins (`CORS_ORIGINS`).

### Hardening checklist for production

- [ ] Set `AUTH_ENABLED=true` and a strong random `JWT_SECRET`.
- [ ] Set a strong `SECRET_KEY`.
- [ ] Restrict `CORS_ORIGINS` to your real frontend origin(s).
- [ ] Serve over HTTPS/TLS (terminate at your proxy/load balancer).
- [ ] Use PostgreSQL with least-privilege credentials; keep it off the public
      internet.
- [ ] Keep dependencies patched (Dependabot + CI's `pip-audit`).

## Automated scanning

CI runs **Bandit** (Python SAST), **pip-audit** (dependency CVEs) and **CodeQL**
on every push and pull request, plus a weekly scheduled CodeQL scan.
