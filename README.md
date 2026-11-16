# Automated Multi-Platform Posting System

A FastAPI service that publishes one short message (with exactly one CTA link) to **Bluesky, Mastodon, DEV.to, Hashnode and WordPress** with a single request.

> ## ⚠️ Demo Mode does NOT publish anything
> With `POSTING_MODE=demo` (the default) no external API is called, no credentials are used and **no real content is created**. Every platform returns `status: "simulated"`, `posted_url: null`, `public_access: false`. Only `POSTING_MODE=live` publishes for real.

## 1. Overview & 2. Features

- `POST /posting` takes only `{"message": "..."}`; all five platforms are always used (no platform selection).
- **Two modes**: `demo` (offline, no accounts) and `live` (official APIs).
- Pydantic validation: not empty, ≤ 200 chars, exactly one valid `http(s)` URL → otherwise HTTP 422.
- Independent platform classes, run concurrently with `asyncio.gather()`; one failure never stops the others.
- Per-platform timeout, authentication / rate-limit / HTTP-status / network error handling, logging.
- Live mode returns a status of `success` only after the platform confirmed publication; it returns the real URL, the platform's publication time, and `public_access` verified by an **anonymous** fetch of the post.

## 3. Technology stack
Python 3.11+ (tested on 3.13), FastAPI, Uvicorn, Pydantic v2 / pydantic-settings, HTTPX, asyncio; pytest, pytest-asyncio, respx (tests).

## 4. Project structure
```
app/
  main.py                 FastAPI app, lifespan (shared HTTPX client, PostingService)
  config.py               Settings from environment / .env (POSTING_MODE, credentials, timeouts)
  schemas.py              PostRequest (validation) and response models
  exceptions.py           Error vocabulary (auth, rate limit, timeout, connection, config ...)
  dependencies.py         get_posting_service
  api/routes.py           POST /posting, GET /health
  validators/url_validator.py   CTA URL extraction + validation
  services/posting_service.py   Modes, asyncio.gather, per-platform timeout, result mapping
  platforms/
    base.py               BasePlatform (abstract) + shared HTTP / error handling
    bluesky.py mastodon.py devto.py hashnode.py wordpress.py   one class each
    registry.py           Builds the five platforms
tests/                    194 offline tests (HTTP mocked with respx; real network blocked)
docs/samples, docs/logs   Example responses, test and server logs
```

## 5. Installation
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## 6. Environment configuration
`cp .env.example .env` (optional for demo mode). Variables: `POSTING_MODE`, `BLUESKY_HANDLE`, `BLUESKY_APP_PASSWORD`, `MASTODON_INSTANCE`, `MASTODON_ACCESS_TOKEN`, `DEVTO_API_KEY`, `HASHNODE_API_KEY`, `HASHNODE_PUBLICATION_ID`, `WORDPRESS_URL`, `WORDPRESS_USERNAME`, `WORDPRESS_APP_PASSWORD`. Optional tuning: `PLATFORM_TIMEOUT_SECONDS` (30), `HTTP_TIMEOUT_SECONDS` (15), `PUBLIC_CHECK_ATTEMPTS` (3), `PUBLIC_CHECK_DELAY_SECONDS` (1.5).

## 7. Demo mode
```bash
uvicorn app.main:app --host 0.0.0.0 --port 4000
```
Nothing else is needed: no `.env`, no accounts. Open <http://localhost:4000/docs>.

## 8. Live mode
Set `POSTING_MODE=live` and the credentials of the platforms you want (see sections 9–10), restart, and call `POST /posting`. A platform with missing credentials fails with `configuration_error` naming the missing variables; **no request is sent for it** and the other platforms still run.

## 9. Account creation
| Platform | Account |
|---|---|
| Bluesky | Sign up at <https://bsky.app>. |
| Mastodon | Create an account on any instance, e.g. <https://mastodon.social>. |
| DEV.to | Sign up at <https://dev.to>. |
| Hashnode | Sign up at <https://hashnode.com> and create a blog (publication). |
| WordPress | A **self-hosted WordPress** (5.6+) site you administer, served over HTTPS. (WordPress.com sites use OAuth rather than Application Passwords and are not supported by this integration.) |

## 10. API credentials
- **Bluesky** – Settings → Privacy and security → *App Passwords* → create one. `BLUESKY_HANDLE=you.bsky.social`, `BLUESKY_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx`. Never use your main password. Uses `com.atproto.server.createSession` + `com.atproto.repo.createRecord` (`app.bsky.feed.post`, with a link facet), then reads the post back through the public AppView (`app.bsky.feed.getPosts`).
- **Mastodon** – Preferences → Development → *New application*; scope **`write:statuses`**; copy "Your access token". `MASTODON_INSTANCE=https://mastodon.social`. Uses `POST /api/v1/statuses` with `visibility=public`.
- **DEV.to** – Settings → Extensions → *DEV Community API Keys* → generate. Uses `POST /api/articles` (`api-key` header, `published: true`). The message becomes the article body; its title is the message without the URL.
- **Hashnode** – Account settings → Developer → *Personal Access Token*. The Publication ID is in your blog dashboard URL (`hashnode.com/<publicationId>/dashboard`). Uses the GraphQL `publishPost` mutation at `https://gql.hashnode.com` with the token in the raw `Authorization` header.
- **WordPress** – Users → Profile → *Application Passwords* → add one. `WORDPRESS_URL=https://yourblog.com`, `WORDPRESS_USERNAME`, `WORDPRESS_APP_PASSWORD` (spaces are fine). The user needs the `publish_posts` capability (Author or higher). Uses `POST /wp-json/wp/v2/posts` with `status=publish`. Some security plugins or hosts disable Application Passwords or the REST API.

## 11. Swagger testing
1. Start the server (section 7) and open <http://localhost:4000/docs>.
2. Open **POST /posting** → **Try it out**.
3. Enter a message, e.g. `{"message": "Check out our latest business platform https://example.com"}`.
4. **Execute** → results for all five platforms appear. No platform selection exists in the body.

## 12. Sample request
```bash
curl -X POST http://localhost:4000/posting -H "Content-Type: application/json" \
  -d '{"message": "Check out our latest business platform https://example.com"}'
```

## 13. Sample demo response (real output, see `docs/samples/01_demo_success.json`)
```json
{
  "success": true,
  "mode": "demo",
  "notice": "DEMO MODE: nothing was published to any platform. ...",
  "cta_url": "https://example.com",
  "summary": {"total": 5, "succeeded": 0, "simulated": 5, "failed": 0},
  "results": [
    {"platform": "Bluesky", "status": "simulated", "posted_url": null, "public_access": false,
     "date": null, "time": null, "error": null, "error_type": null, "external_id": null,
     "note": "SIMULATED: not published; no external API call was made."}
    // ... Mastodon, DEV.to, Hashnode, WordPress identical in shape
  ]
}
```

## 14. Sample live response — ILLUSTRATIVE ONLY (values are made up)
```json
{
  "success": true,
  "mode": "live",
  "summary": {"total": 5, "succeeded": 4, "simulated": 0, "failed": 1},
  "results": [
    {"platform": "Bluesky", "status": "success", "posted_url": "https://bsky.app/profile/you.bsky.social/post/3kabc...",
     "public_access": true, "date": "2026-11-16", "time": "09:30:05", "error": null},
    {"platform": "Hashnode", "status": "failed", "posted_url": null, "public_access": false,
     "date": null, "time": null, "error_type": "authentication_error",
     "error": "Authentication failed: You must be logged in"}
  ]
}
```
`success` (top level): demo → at least one platform simulated; live → at least one platform confirmed publication. `public_access: false` on a `success` result means it was published but an anonymous fetch did not confirm it (a `note` explains).

## 15. Testing
```bash
python -m pytest -v
```
194 offline tests cover: valid / empty / too-long messages; no, multiple and invalid URLs; demo mode (five `simulated` results, zero HTTP calls); live success; authentication, rate-limit, 5xx, validation (4xx), network and timeout failures for every platform; individual failures; asyncio timeout; true concurrency (barrier test); overall success/failure rules; missing credentials. HTTP is mocked with respx and real network access is blocked, so **tests never create real posts**.

## 16. Troubleshooting
| Symptom | Cause / fix |
|---|---|
| `configuration_error` | Credentials missing for that platform in live mode – set the named variables. |
| `authentication_error` | Wrong/expired key, revoked App Password, missing scope (`write:statuses`), wrong WordPress user. |
| `rate_limit_error` | Platform returned 429 (DEV.to limits article creation); wait (message shows `retry after` when given). No automatic retry, to avoid duplicate posts. |
| `timeout_error` | Platform exceeded `PLATFORM_TIMEOUT_SECONDS` / `HTTP_TIMEOUT_SECONDS`. The post *might* still have been created – check the platform before retrying. |
| `connection_error` | DNS/TLS/network problem or wrong instance/site URL. |
| WordPress 404 on `/wp-json/` | REST API disabled or pretty permalinks off. |
| `public_access: false` on a success | Post is published but not (yet) anonymously reachable (indexing delay, bot protection, restricted visibility). |
| `ValidationError` at startup | `POSTING_MODE` must be `demo` or `live`. |

## 17. Security considerations
- Never commit `.env` (it is git-ignored); `.env.example` has empty values only.
- Use Bluesky **App Passwords**, least-privilege tokens (`write:statuses`), and WordPress Application Passwords you can revoke.
- Credentials are only sent to their platform's own API; they are never logged or returned in responses. HTTPX request logging is disabled so URLs are not written to logs.
- WordPress content is HTML-escaped; message content is validated (length, single public http(s) URL, no localhost/private IPs/credentials in URLs).
- The API has no authentication of its own: put it behind an authenticated gateway before exposing it, because live mode publishes to your accounts.

## Verification Status (Honest Summary)

| Integration | Status |
|---|---|
| Demo mode (all five platforms) | ✅ **Verified:** Tested on the local server through `/docs`. Received HTTP 200 with five `simulated` results. Confirmed that no external API calls or real posts were made. |
| Bluesky (Live) | ✅ **Verified:** Successfully tested using real Bluesky account credentials. Confirmed live authentication and publishing through the API. |
| Mastodon (Live) | ⚠️ **Implemented:** Based on official API documentation and tested against mocked HTTP responses. Real-world publishing is pending. |
| DEV.to (Live) | ⚠️ **Implemented:** Based on official API documentation and tested against mocked HTTP responses. Real-world publishing is pending. |
| Hashnode (Live) | ⚠️ **Implemented:** Based on official API documentation and tested against mocked HTTP responses. Real-world publishing is pending. |
| WordPress (Live) | ⚠️ **Implemented:** Based on official API documentation and tested against mocked HTTP responses. Real-world publishing is pending. |

**Remaining verification:** Mastodon, DEV.to, Hashnode, and WordPress require testing with valid account credentials and real API requests.

**Least certain areas:** Hashnode's `publishPost` response fields (`id`, `slug`, `url`, `publishedAt`) and DEV.to's exact published-article response should be confirmed during real API testing.
