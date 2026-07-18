# Schulmanager API

> Self-hosted REST backend for Schulmanager — with FastAPI, JWT, SQLite, webhooks, and Prometheus.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)
![License](https://img.shields.io/badge/License-MIT-green)

---

> **Discord bot:** Want to use the API directly through Discord?
> Check out the companion bot: **[schulmanager-discord-bot →](https://github.com/leoapplecool/schulmanager-discord-bot)**

---

## Features

- **FastAPI backend** with interactive Swagger documentation at `/docs`
- **JWT authentication** (access token, refresh token, token rotation, roles: `parent`, `viewer`, `admin`)
- **Per-student data retrieval**: timetable, homework, exams, grades + statistics, events, absences, messages (messenger), parent letters, payments, learning, ICS calendar export
- **Provider system**: `mock` (test data without a Schulmanager login) and `selenium` (real login via the private `api/calls` interface over HTTP; browser check optional)
- **Persistent caching** (SQLite or in-memory, configurable TTL per endpoint)
- **Webhook subsystem** for real-time notifications on data changes
- **Rate limiting** (120 req/min, configurable)
- **Prometheus metrics** at `/metrics`

---

## Quick Start

### Docker (recommended)

```bash
git clone https://github.com/leoapplecool/schulmanager-api.git
cd schulmanager-api

cp .env.example .env
# open .env and set at least SM_JWT_SECRET
docker compose up --build
```

The API is then reachable at:
- **Swagger Docs:** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/health`
- **Metrics:** `http://localhost:8000/metrics`

### Local development

```bash
pip install -e ".[dev]"
uvicorn schulmanager_api.main:app --reload --host 127.0.0.1 --port 8000
```

---

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `SM_BACKEND` | Data provider: `mock` or `selenium` | `mock` |
| `SM_JWT_SECRET` | Secret key for JWT signing | *(must be set)* |
| `SM_ACCESS_TOKEN_TTL_MINUTES` | Access token validity in minutes | `30` |
| `SM_REFRESH_TOKEN_TTL_DAYS` | Refresh token validity in days | `14` |
| `SM_ADMIN_EMAILS_CSV` | Comma-separated admin email addresses | *(empty)* |
| `SM_CACHE_ENABLED` | Enable caching | `true` |
| `SM_CACHE_BACKEND` | Cache backend: `sqlite` or `memory` | `sqlite` |
| `SM_RATE_LIMIT_ENABLED` | Enable rate limiting | `true` |
| `SM_RATE_LIMIT_REQUESTS` | Max. requests per time window | `120` |
| `SM_RATE_LIMIT_WINDOW_SECONDS` | Time window in seconds | `60` |
| `SM_WEBHOOKS_ENABLED` | Enable webhook subsystem | `true` |
| `SM_WEBHOOK_HMAC_SECRET` | HMAC secret for webhook signatures | *(must be set)* |
| `SM_METRICS_REQUIRE_AUTH` | Protect `/metrics` behind JWT | `false` |
| `SM_LOG_LEVEL` | Log level (`INFO`, `DEBUG`, ...) | `INFO` |

Full list: `.env.example`

---

## API endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/auth/login` | Login → access + refresh token |
| `POST` | `/auth/refresh` | Renew access token |
| `POST` | `/auth/logout` | Invalidate session |
| `GET` | `/auth/me` | Own account info |
| `GET` | `/students` | List of all students in the account |
| `GET` | `/students/{id}/schedule` | Timetable |
| `GET` | `/students/{id}/homework` | Homework |
| `PATCH` | `/students/{id}/homework/{hw_id}` | Mark homework as done |
| `GET` | `/students/{id}/exams` | Exams / tests |
| `GET` | `/students/{id}/grades` | Grades |
| `GET` | `/students/{id}/grades/stats` | Grade statistics with trend |
| `GET` | `/students/{id}/events` | School events |
| `GET` | `/students/{id}/absences` | Absences |
| `GET` | `/students/{id}/messages` | Messages / chat threads (messenger) |
| `GET` | `/students/{id}/messages/{subscription_id}` | Single message thread |
| `GET` | `/students/{id}/letters` | Parent letters (with read status) |
| `GET` | `/students/{id}/payments` | Payments / invoices (paid/outstanding) |
| `GET` | `/students/{id}/learning` | Learning: tasks & material (seen/done) |
| `GET` | `/students/{id}/calendar.ics` | ICS calendar export |
| `POST` | `/webhooks` | Register webhook |
| `GET` | `/webhooks` | List own webhooks |
| `DELETE` | `/webhooks/{id}` | Delete webhook |
| `POST` | `/webhooks/test` | Send test event to webhook |
| `POST` | `/sync/refresh` | Manual full sync |
| `GET` | `/cache/stats` | Cache statistics *(Admin)* |
| `DELETE` | `/cache` | Clear cache *(Admin)* |
| `GET` | `/metrics` | Prometheus metrics |

Interactive documentation with try-it-out: `http://localhost:8000/docs`

---

## Webhook events

The webhook dispatcher sends HTTP POST requests to registered URLs on the following events:

| Event | Trigger |
|---|---|
| `homework.new` | New homework detected |
| `grade.new` | New grade recorded |
| `absences.new` | New absence recorded |
| `message.new` | New school message |
| `letter.new` | New parent letter |
| `schedule.change` | Timetable change (cancellation, substitution, room change) |
| `sync.completed` | `/sync/refresh` completed (with summary) |

> On the **first** observation of a data type (or after a restart), existing entries are
> silently "primed" and trigger **no** events — only genuinely new entries fire afterwards.

All requests are signed with an HMAC-SHA256 header (`X-Signature`) (`SM_WEBHOOK_HMAC_SECRET`).

---

## The real Schulmanager API

The `selenium` provider talks to the private Schulmanager API directly over HTTP
(`POST /api/calls` with `{moduleName, endpointName, parameters}` and a Bearer JWT). Login runs through
`/api/get-salt` + `/api/login` (PBKDF2-HMAC-SHA512, 99999 iterations). Confirmed endpoints:

| Feature | `moduleName` / `endpointName` |
|---|---|
| Timetable | `schedules` / `get-actual-lessons` |
| Class hours | `schedules` / `get-class-hours` |
| Homework | `classbook` / `get-homework` |
| Exams | `exams` / `get-exams` |
| Events (calendar) | `calendar` / `get-events-for-user` |
| Grades (incl. individual grades) | `grades` / `get-grading-information-for-student` |
| Absences | `classbook` / `get-history-absences-list` |
| Messages (threads) | `messenger` / `get-subscriptions`, `messenger` / `get-messages-by-subscription` |
| Parent letters | `letters` / `get-letters` |

> **Analyze your own account:** paste `tools/capture-api.js` into the browser console (F12) and
> click through the modules — it shows `moduleName`/`endpointName`, `parameters`, and the response **structure**
> (without contents, without auth token). Ideal for confirming school-specific endpoints.

### Roadmap – what else could be scraped

Read-capable modules that are not (yet) covered, by usefulness:

- **Payments** (outstanding/paid items), **digital class register** (remarks, topics),
  **learning** (tasks/material), **sick notes** (history) — high value.
- **Parent-teacher day / office hours** (slots + own bookings), **surveys**, **documents**,
  **notice board**, **teacher list** — medium value.

> ⚠️ Which modules are available depends on the respective school — new endpoints must
> return "empty instead of error" when a module is not enabled (see `soft` mode in `_api_call`).

Full endpoint list including confirmed parameter/response structures and modules not yet
built in (payments, learning): **`docs/discovered-endpoints.md`**.

---

## Architecture

```
src/schulmanager_api/
├── main.py              # FastAPI app, router registration, middleware
├── config.py            # Settings via pydantic-settings (SM_ prefix, .env)
├── dependencies.py      # Dependency injection (auth, provider, cache)
├── models/
│   └── schemas.py       # Pydantic models for all requests & responses
├── providers/
│   ├── base.py          # Abstract provider interface
│   ├── mock.py          # Static test data (no login required)
│   ├── selenium.py      # Real Schulmanager login via the private api/calls
│   └── factory.py       # Selects the provider based on SM_BACKEND
├── routers/
│   ├── auth.py          # Login, refresh, logout, /me
│   ├── students.py      # All student-data endpoints
│   ├── webhooks.py      # Webhook registration & dispatch
│   ├── sync.py          # Manual sync trigger
│   ├── cache.py         # Cache stats & clear (admin)
│   ├── health.py        # Health check
│   └── metrics.py       # Prometheus export
└── services/
    ├── security.py      # JWT generation & validation
    ├── auth_store.py    # Session persistence (SQLite)
    ├── cache.py         # Cache abstraction & TTL logic
    ├── sqlite_cache.py  # SQLite cache implementation
    ├── webhooks.py      # Webhook event publishing (async)
    ├── grade_stats.py   # Grade statistics & trend calculation
    ├── ical.py          # ICS calendar export generation
    ├── rate_limiter.py  # Rate-limiting middleware
    └── metrics_store.py # Prometheus counters & histograms
```

**Tech stack:** Python 3.11+, FastAPI, PyJWT, SQLite, aiosqlite, Prometheus, Selenium (optional), Docker Compose

---

## Tests

```bash
pip install -e ".[dev]"
pytest
```

---

## License

MIT
