# Schulmanager API

> Selbst gehostetes Backend + Discord-Bot für Schulmanager — mit FastAPI, JWT, SQLite, Prometheus und Discord.py.

![Python](https://img.shields.io/badge/Python-3.11%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.110%2B-009688?logo=fastapi)
![Discord.py](https://img.shields.io/badge/discord.py-2.x-5865F2?logo=discord)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker)
![License](https://img.shields.io/badge/Lizenz-MIT-green)

---

## Features

- **FastAPI-Backend** mit Swagger-Dokumentation unter `/docs`
- **JWT-Authentifizierung** (Access-Token, Refresh-Token, Token-Rotation, Rollen: `parent`, `viewer`, `admin`)
- **Datenabruf pro Schüler**: Stundenplan, Hausaufgaben, Klausuren, Noten + Statistiken, Termine, Fehlzeiten, Nachrichten, ICS-Kalenderexport
- **Provider-System**: `mock` (Testdaten) und `selenium` (echter Login-Flow)
- **Persistentes Caching** (SQLite oder In-Memory, TTL pro Endpoint)
- **Webhook-Subsystem** für Echtzeit-Benachrichtigungen (homework.new, grade.new, absences.new, message.new, schedule.change)
- **Prometheus-Metriken** unter `/metrics`
- **Discord-Bot** mit privaten Kanälen pro Nutzer, automatischem Sync, Hausaufgaben-Reaktionen (✅), Erinnerungen und Tages-Digest

---

## Screenshots / Demo

> _Platzhalter – Screenshots hier einfügen._

---

## Quick Start

### Docker (empfohlen)

```bash
# 1. Repository klonen
git clone https://github.com/dein-user/schulmanager-api.git
cd schulmanager-api

# 2. Umgebungsvariablen konfigurieren
cp .env.example .env
# .env öffnen und SM_JWT_SECRET, SM_DISCORD_BOT_TOKEN etc. setzen

# 3. Starten
docker compose up --build
```

Oder mit dem mitgelieferten Skript:

```bash
./start.sh          # Linux/Mac
start.bat           # Windows
```

### Lokale Entwicklung

```bash
# Abhängigkeiten installieren
pip install -e ".[dev]"

# API starten
uvicorn schulmanager_api.main:app --reload --host 127.0.0.1 --port 8000

# Discord-Bot starten (separates Terminal)
python -m schulmanager_api.discord_bot
```

---

## Umgebungsvariablen

| Variable | Beschreibung | Beispiel |
|---|---|---|
| `SM_JWT_SECRET` | Geheimschlüssel für JWT-Signierung | `mein-geheimes-passwort` |
| `SM_DISCORD_BOT_TOKEN` | Discord-Bot-Token | `MTI3...` |
| `SM_DISCORD_API_BASE_URL` | URL der eigenen API-Instanz | `http://api:8000` |
| `SM_DISCORD_GUILD_ID` | Discord-Server-ID (optional, für schnelleres Sync) | `123456789` |
| `SM_DISCORD_TIMEZONE` | Zeitzone für Anzeigen | `Europe/Berlin` |
| `SM_DISCORD_SYNC_INTERVAL_SECONDS` | Sync-Intervall in Sekunden | `300` |
| `SM_DISCORD_DIGEST_ENABLED` | Tages-Digest aktivieren | `true` |
| `SM_DISCORD_DIGEST_TIME` | Uhrzeit für Digest (HH:MM) | `07:00` |
| `SM_DISCORD_CATEGORY_PREFIX` | Präfix für private Kategorien | `sm` |
| `SM_PROVIDER` | Datenprovider (`mock` oder `selenium`) | `mock` |
| `SM_DB_PATH` | Pfad zur SQLite-Datenbank | `data/db.sqlite` |
| `SM_DISCORD_DB_PATH` | Pfad zur Discord-Bot-Datenbank | `data/discord.sqlite` |

Eine vollständige Liste befindet sich in `.env.example`.

---

## API-Übersicht

| Methode | Endpunkt | Beschreibung |
|---|---|---|
| `GET` | `/health` | Health-Check |
| `POST` | `/auth/login` | Login, gibt Access- und Refresh-Token zurück |
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
| `GET` | `/cache/stats` | Cache-Statistiken (Admin) |
| `DELETE` | `/cache` | Cache leeren (Admin) |
| `GET` | `/metrics` | Prometheus-Metriken |

Vollständige Dokumentation: `http://localhost:8000/docs`

---

## Discord-Bot — Slash-Befehle

| Befehl | Beschreibung |
|---|---|
| `/login email password [student_id]` | Schulmanager-Login und private Kanäle erstellen |
| `/logout [delete_category]` | Bot-Zugang entfernen |
| `/sync` | Manuelle Synchronisierung |
| `/status` | Bot-Status für den eigenen Account |
| `/calendar` | ICS-Kalender als DM senden |
| `/digest` | Tages-Digest sofort anzeigen |
| `/info` | Allgemeine Bot-Informationen |
| `/channels` | Eigene Schulmanager-Kanäle anzeigen |
| `/remind exams <hours>` | Prüfungs-Erinnerung X Stunden vorher |
| `/remind homework <hours>` | Hausaufgaben-Erinnerung X Stunden vorher |
| `/remind off <type>` | Erinnerung deaktivieren |
| `/notify schedule-changes <on/off>` | DM bei Stundenplan-Änderungen |
| `/notify digest <on/off>` | Tages-Digest aktivieren/deaktivieren |
| `/notify status` | Benachrichtigungs-Einstellungen anzeigen |
| `/debug-state` | Debug-Infos für den eigenen Account |
| `/debug-webhook` | Test-Nachricht in den Webhook-Kanal |
| `/admin-users` | Alle Bot-Nutzer im Server _(Admin)_ |
| `/admin-sync-all` | Sync für alle aktiven Nutzer _(Admin)_ |
| `/admin-user-active` | Nutzer aktiv/inaktiv setzen _(Admin)_ |
| `/admin-errors` | Letzte Sync-Fehler aller Nutzer _(Admin)_ |
| `/admin-stats` | Bot-Statistiken _(Admin)_ |
| `/admin-purge` | Nutzer-Workspace vollständig löschen _(Admin)_ |
| `/admin-flush-cache` | API-Cache leeren _(Admin)_ |

---

## Discord-Kanal-Layout

Pro Nutzer wird automatisch eine private Kategorie mit folgenden Kanälen erstellt:

| Kanal | Inhalt |
|---|---|
| `00-status` | Sync-Status-Embed + Tages-Digest + 🔄-Sync-Button |
| `01-schedule-feed` | Nächste Stunden (automatisch aktualisiert) |
| `02-schedule-week` | Wochenübersicht (ein Embed pro Tag) |
| `03-homework` | Eine Nachricht pro Hausaufgabe + ✅-Reaktion zum Abhaken |
| `04-grades` | Noten je Fach + Notenstatistik |
| `05-events` | Schultermine + „Nächstes Event"-Panel |
| `06-webhooks` | Änderungslog nach jedem Sync |
| `07-absences` | Fehlzeiten-Übersicht |
| `08-messages` | Schulnachrichten / Posteingang |

---

## Webhook-Events

| Event | Beschreibung |
|---|---|
| `homework.new` | Neue Hausaufgabe erkannt |
| `grade.new` | Neue Note eingetragen |
| `absences.new` | Neue Fehlzeit eingetragen |
| `message.new` | Neue Schulnachricht |
| `schedule.change` | Stundenplan-Änderung (Ausfall, Vertretung, Raumwechsel) |

---

## Architektur

```
schulmanager_api/
├── main.py              # FastAPI-App, Router-Registrierung
├── config.py            # Settings via pydantic-settings
├── auth.py              # JWT-Logik, Token-Rotation
├── cache.py             # SQLite/In-Memory-Cache mit TTL
├── webhooks.py          # Webhook-Registrierung und Event-Dispatch
├── providers/
│   ├── mock.py          # Testdaten-Provider
│   └── selenium_provider.py  # Echter Schulmanager-Login via Selenium
├── routers/             # FastAPI-Router (students, auth, webhooks, ...)
└── discord_bot/
    ├── bot.py           # Discord-Cog, Slash-Befehle, Sync-Loop
    ├── embeds.py        # Embed-Rendering, Fingerprinting, Deduplication
    ├── api_client.py    # HTTP-Client für die eigene API
    ├── storage.py       # SQLite-Persistenz für Bot-Zustand
    └── models.py        # Datenmodelle (UserWorkspaceState, ReminderRule, ...)
```

**Tech-Stack:** Python 3.11+, FastAPI, JWT, SQLite, Prometheus, discord.py 2.x, Selenium (optional), Docker Compose

---

## Entwicklung & Tests

```bash
# Abhängigkeiten installieren
pip install -e ".[dev]"

# Tests ausführen
pytest

# Linting
ruff check src/ tests/

# Mit Makefile
make test
make lint
make install
```

---

## Lizenz

MIT — siehe `LICENSE`.
