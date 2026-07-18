# Entdeckte Schulmanager `api/calls`-Endpoints

Aus echten Netzwerk-Captures (`tools/capture-api.js`) beobachtete `moduleName / endpointName`.
Feld-Details (Parameter/Response) werden ergänzt, sobald ein v2-Capture (vollständig ausgeklappt) vorliegt.

## Bereits im Wrapper genutzt
| Modul | Endpoint | Zweck |
|---|---|---|
| `schedules` | `get-actual-lessons` | Stundenplan (inkl. Vertretung) |
| `schedules` | `get-class-hours` | Stundenzeiten |
| `classbook` | `get-homework` | Hausaufgaben |
| `exams` | `get-exams` | Klausuren |
| `exams` | `poqa` | Kalender-Events (Alt-Weg) |
| `grades` | `get-grading-information-for-student` | Noten |
| `letters` | `get-letters` | Elternbriefe |
| `messenger` | `get-subscriptions` | Nachrichten-Threads |

## Neu entdeckt (Capture 2026-07-18)
| Modul | Endpoint | Vermuteter Zweck | Wert |
|---|---|---|---|
| `classbook` | `get-statistics` | **Fehlzeiten-Statistik** (Route `classbook.reports2.student.statistics`, Params `{studentId, start, end}`) | hoch |
| `classbook` | `poqa` | **Fehlzeiten-Einträge** (ORM findAll auf der reports2-Route) | hoch |
| `classbook` | `get-topics` | Unterrichtsthemen (Klassenbuch) | mittel |
| `classbook` | `get-tiles` | Klassenbuch-Kacheln | niedrig |
| `classbook` | `get-upcoming-conferences` | Anstehende Konferenzen/Gespräche | mittel |
| `calendar` | `get-events-for-user` | **Termine** — sauberer Endpoint statt `exams/poqa`-Hack | hoch |
| `schedules` | `get-substitution-texts-for-widget` | Vertretungstexte (Freitext) | mittel |
| `schedules` | `get-occurrences-of-current-term` | Schultage/Termin-Struktur des Halbjahres | mittel |
| `invoicing` | `poqa` | **Zahlungen/Rechnungen** | hoch |
| `detention` | `poqa` | Nachsitzen | niedrig |
| `documents` | `documents-visible` | Dokumente-Modul sichtbar? | niedrig |
| `messenger` | `count-new-messages` | Anzahl neuer Nachrichten (Badge) | mittel |
| `letters` | `get-current-term`, `poqa`, `user-can-see-setting-for-letter-mailing` | Elternbrief-Metadaten | niedrig |
| `null` | `get-current-next-or-previous-term` | Aktuelles/nächstes Halbjahr | mittel |

## Offen (braucht v2-Capture für Feld-Details)
- **Fehlzeiten** exakt: `classbook/get-statistics` (Params + Response-Felder) und `classbook/poqa` (ORM-`model` + Response-Felder).
- **Termine** ggf. auf `calendar/get-events-for-user` umstellen (Params + Response).
- **Zahlungen** neu: `invoicing/poqa` (ORM-`model` + Response).
