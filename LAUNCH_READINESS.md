# CineZone Launch Readiness Checklist

This document summarizes what is implemented in code vs. what still requires external services, configuration, licensed content, or human/legal verification before a **fully operational public launch**.

## Implemented in this repository (code-level)
- Flask app factory, Blueprint routing, env-based config, CSRF, secure session cookie settings (production-aware), security headers, `/health`.
- SQLAlchemy models and Alembic migrations; rights-aware catalog/media access patterns; local private media storage and range streaming; optional S3-compatible adapter scaffolding.
- Core pages/routes: home, movies (paginated search/filter/sort), movie details, watch/stream/trailer/download/poster (gated), genres listing/page, trending, latest, search page, login/register/logout/profile/watchlist, continue-watching page, about/contact/privacy/terms/copyright, admin catalog flows, sitemap.xml, robots.txt.
- Basic admin capabilities: movie create/edit/unpublish/feature (per existing implementation), upload validation hooks, audit logging foundations (per existing implementation), rights/attestation fields.
- Tests: existing automated tests (run `python3 -m unittest discover -s tests -v`). **Re-run after every change.**

## Must be completed/configured before public launch (external or operational)

### Infrastructure & deployment
- [ ] Provision **managed MySQL** (production), set `DATABASE_URL` (`mysql+pymysql://...`), run `flask db upgrade` on a backed-up target, verify connectivity.
- [ ] Provision **object storage/CDN** for posters/backdrops/trailers/videos/subtitles (private, signed/controlled access). Configure `STORAGE_BACKEND=s3` and bucket/region/endpoint/credentials via provider secret store. Do not store large media in DB or `static/`.
- [ ] Deploy backend (Gunicorn/WSGI) and frontend delivery as appropriate, set all env vars/secrets, enable **HTTPS** and custom domain/DNS.
- [ ] Configure logging, monitoring/uptime, error reporting, and storage/bandwidth cost alerts/budgets.
- [ ] Establish and **test** database backup/restore procedures and migration runbooks.

### Content & rights (mandatory)
- [ ] Populate catalog **only** with titles/media you have documented rights/permission to distribute (public domain, licensed, or authorised). Complete rights records (holder, licence ref, territories, dates, stream/download permissions) and verify before publishing.
- [ ] Upload/attach **actual authorised assets** (posters, trailers, videos, subtitles) and confirm only existing qualities/options are shown. Test real playback, seeking, and downloads in staging.
- [ ] Review imported metadata (e.g. TMDB) for accuracy and attribution; metadata does not equal distribution rights.

### Accounts, email, and security
- [ ] Configure transactional email (if enabling verification/reset flows) and complete end-to-end testing.
- [ ] Perform security review: rate limiting, dependency audit, penetration/abuse checks, RBAC verification, upload hardening, secret rotation policy.
- [ ] Complete browser/mobile/responsive and performance QA.

### Legal, SEO, ads, analytics
- [ ] Finalise and legally review **Terms, Privacy, Copyright/takedown, contact, and ad disclosures** for your jurisdictions and actual data practices.
- [ ] Configure **consent/privacy controls** as required before enabling analytics/advertising cookies/identifiers.
- [ ] Apply for/enable **Google AdSense** only if eligible and policy-compliant (no guarantee). Add only approved ad code/config; never fake metrics/clicks.
- [ ] **Uganda payments:** verify current official payout options and account/identity requirements for your chosen provider; keep ad earnings as informational records only (no payment credentials in app).

### Functional completeness to validate
- [ ] End-to-end: search/filter/sort/pagination, details, trailers, authorised streaming/downloads, watchlist/favourites/history/continue-watching (including progress persistence where implemented), admin CMS without code edits.
- [ ] SEO: verify sitemap/robots/canonical/OG/meta per environment and submit sitemap after launch.

## Honest status
A public launch should proceed only when rights, infrastructure, security, legal, and core user flows are verified in a staging/production environment. Revenue/ads depend on third-party approval and compliant traffic.
