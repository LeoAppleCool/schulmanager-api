# Schulmanager API

> Selbst gehostetes REST-Backend für Schulmanager — mit FastAPI, JWT, SQLite, Webhooks und Prometheus.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)
![License](https://img.shields.io/badge/Lizenz-MIT-green)

---

> **Discord-Bot:** Du willst die API direkt über Discord nutzen?
> Schau dir den zugehörigen Bot an: **[schulmanager-discord-bot →](https://github.com/leoapplecool/schulmanager-discord-bot)**

---

## Features

- **FastAPI-Backend** mit interaktiver Swagger-Dokumentation unter `/docs`
- **JWT-Authentifizierung** (Access-Token, Refresh-Token, Token-Rotation, Rollen: `parent`, `viewer`, `admin`)
- **Datenabruf pro Schüler**: Stundenplan, Hausaufgaben, Klausuren, Noten + Statistiken, Termine, Fehlzeiten, Nachrichten, ICS-Kalenderexport
- **Provider-System**: `mock` (Testdaten ohne Schulmanager-Login) und `selenium` (echter Login-Flow via Browser-Automatisierung)
- **Persistentes Caching** (SQLite oder In-Memory, konfigurierbares TTL pro Endpoint)
- **Webhook-Subsystem** für Echtzeit-Benachrichtigungen bei Datenänderungen
- **Rate-Limiting** (120 Req/min, konfigurierbar)
- **Prometheus-Metriken** unter `/metrics`

---

## Quick Start

### Docker (empfohlen)

```bash
git clone https://github.com/leoapplecool/schulmanager-api.git
cd schulmanager-api

cp .env.example .env
# .env öffnen und mindestens SM_JWT_SECRET setzen

docker compose up --build
```

Die API ist danach erreichbar unter:
- **Swagger Docs:** `http://localhost:8000/docs`
- **Health Check:** `http://localhost:8000/health`
- **Metriken:** `http://localhost:8000/metrics`

### Lokale Entwicklung

```bash
pip install -e ".[dev]"
uvicorn schulmanager_api.main:app --reload --host 127.0.0.1 --port 8000
```

---

## Umgebungsvariablen

| Variable | Beschreibung | Standard |
|---|---|---|
| `SM_BACKEND` | Datenprovider: `mock` oder `selenium` | `mock` |
| `SM_JWT_SECRET` | Geheimschlüssel für JWT-Signierung | *(muss gesetzt werden)* |
| `SM_ACCESS_TOKEN_TTL_MINUTES` | Gültigkeit des Access-Tokens in Minuten | `30` |
| `SM_REFRESH_TOKEN_TTL_DAYS` | Gültigkeit des Refresh-Tokens in Tagen | `14` |
| `SM_ADMIN_EMAILS_CSV` | Komma-getrennte Admin-E-Mail-Adressen | *(leer)* |
| `SM_CACHE_ENABLED` | Caching aktivieren | `true` |
| `SM_CACHE_BACKEND` | Cache-Backend: `sqlite` oder `memory` | `sqlite` |
| `SM_RATE_LIMIT_ENABLED` | Rate-Limiting aktivieren | `true` |
| `SM_RATE_LIMIT_REQUESTS` | Max. Anfragen pro Zeitfenster | `120` |
| `SM_RATE_LIMIT_WINDOW_SECONDS` | Zeitfenster in Sekunden | `60` |
| `SM_WEBHOOKS_ENABLED` | Webhook-Subsystem aktivieren | `true` |
| `SM_WEBHOOK_HMAC_SECRET` | HMAC-Geheimnis für Webhook-Signaturen | *(muss gesetzt werden)* |
| `SM_METRICS_REQUIRE_AUTH` | `/metrics` hinter JWT schützen | `false` |
| `SM_LOG_LEVEL` | Log-Level (`INFO`, `DEBUG`, ...) | `INFO` |

Vollständige Liste: `.env.example`

---

## API-Endpunkte

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/health` | Health-Check |
| `POST` | `/auth/login` | Login → Access- + Refresh-Token |
| `POST` | `/auth/refresh` | Access-Token erneuern |
| `POST` | `/auth/logout` | Session invalidieren |
| `GET` | `/auth/me` | Eigene Account-Infos |
| `GET` | `/students` | Liste aller Schüler im Account |
| `GET` | `/students/{id}/schedule` | Stundenplan |
| `GET` | `/students/{id}/homework` | Hausaufgaben |
| `PATCH` | `/students/{id}/homework/{hw_id}` | Hausaufgabe als erledigt markieren |
| `GET` | `/students/{id}/exams` | Klausuren / Arbeiten |
| `GET` | `/students/{id}/grades` | Noten |
| `GET` | `/students/{id}/grades/stats` | Notenstatistiken mit Trend |
| `GET` | `/students/{id}/events` | Schultermine |
| `GET` | `/students/{id}/absences` | Fehlzeiten |
| `GET` | `/students/{id}/messages` | Nachrichten / Posteingang |
| `GET` | `/students/{id}/calendar.ics` | ICS-Kalenderexport |
| `POST` | `/webhooks` | Webhook registrieren |
| `GET` | `/webhooks` | Eigene Webhooks auflisten |
| `DELETE` | `/webhooks/{id}` | Webhook löschen |
| `POST` | `/webhooks/test` | Test-Event an Webhook senden |
| `POST` | `/sync/refresh` | Manuelles Komplett-Sync |
| `GET` | `/cache/stats` | Cache-Statistiken *(Admin)* |
| `DELETE` | `/cache` | Cache leeren *(Admin)* |
| `GET` | `/metrics` | Prometheus-Metriken |

Interaktive Dokumentation mit Try-it-out: `http://localhost:8000/docs`

---

## Webhook-Events

Der Webhook-Dispatcher sendet bei folgenden Ereignissen HTTP POST-Requests an registrierte URLs:

| Event | Auslöser |
|---|---|
| `homework.new` | Neue Hausaufgabe erkannt |
| `grade.new` | Neue Note eingetragen |
| `absences.new` | Neue Fehlzeit eingetragen |
| `message.new` | Neue Schulnachricht |
| `schedule.change` | Stundenplan-Änderung (Ausfall, Vertretung, Raumwechsel) |

Alle Requests werden mit einem HMAC-SHA256-Header (`X-Signature`) signiert (`SM_WEBHOOK_HMAC_SECRET`).

---

## Architektur

```
src/schulmanager_api/
├── main.py              # FastAPI-App, Router-Registrierung, Middleware
├── config.py            # Settings via pydantic-settings (SM_ prefix, .env)
├── dependencies.py      # Dependency Injection (Auth, Provider, Cache)
├── models/
│   └── schemas.py       # Pydantic-Modelle für alle Requests & Responses
├── providers/
│   ├── base.py          # Abstrakte Provider-Schnittstelle
│   ├── mock.py          # Statische Testdaten (kein Login nötig)
│   ├── selenium.py      # Echter Schulmanager-Login via Selenium
│   └── factory.py       # Wählt Provider anhand SM_BACKEND
├── routers/
│   ├── auth.py          # Login, Refresh, Logout, /me
│   ├── students.py      # Alle Schülerdaten-Endpunkte
│   ├── webhooks.py      # Webhook-Registrierung & Dispatch
│   ├── sync.py          # Manueller Sync-Trigger
│   ├── cache.py         # Cache-Stats & Clear (Admin)
│   ├── health.py        # Health Check
│   └── metrics.py       # Prometheus-Export
└── services/
    ├── security.py      # JWT-Generierung & Validierung
    ├── auth_store.py    # Session-Persistenz (SQLite)
    ├── cache.py         # Cache-Abstraktion & TTL-Logik
    ├── sqlite_cache.py  # SQLite-Cache-Implementierung
    ├── webhooks.py      # Webhook-Event-Publishing (async)
    ├── grade_stats.py   # Notenstatistik & Trend-Berechnung
    ├── ical.py          # ICS-Kalenderexport-Generierung
    ├── rate_limiter.py  # Rate-Limiting-Middleware
    └── metrics_store.py # Prometheus-Counter & Histogramme
```

**Tech-Stack:** Python 3.11+, FastAPI, PyJWT, SQLite, aiosqlite, Prometheus, Selenium (optional), Docker Compose

---

## Tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Lizenz

MIT
