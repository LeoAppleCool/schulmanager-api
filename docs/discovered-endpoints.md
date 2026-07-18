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

## Bestätigt & umgesetzt (v2-Capture 2026-07-18)
| Feature | Endpoint | Params | Response (Kern) |
|---|---|---|---|
| **Fehlzeiten** | `classbook/get-history-absences-list` | `{term:{start,end,id}, student:{…,class:{…}}}` | `[{date, from, until, excused, comment, sickNote, exemptionRequest:{comment,isInternal}}]` |
| (Zeitraum dazu) | `classbook/get-current-next-or-previous-term` | `{}` | `{start, end, id, preventAsCurrentTerm}` |
| **Termine** | `calendar/get-events-for-user` | `{start, end, includeHolidays}` | `{nonRecurringEvents:[{summary,start,end,location,description,allDay,categoryId}], recurringEvents}` |
| **Noten** (+Einzelnoten) | `grades/get-grading-information-for-student` | `{studentId, termId, start, end, gradingPeriodType:"entireYear"}` | `{courses, gradingEvents[].grades[].value, indiviualGrades[…], typePresets, finalGrades}` |
| **Hausaufgaben** | `classbook/get-homework` | `{student:{id}}` | `[{date, subject, homework}]` — **keine ID** → Content-Hash-ID |
| **Nachrichten** | `messenger/get-subscriptions` | `{all:false, includeArchived:false, reason:"whenLoadedSubscriptions"}` | `[{id, unreadCount, thread:{subject, senderString, lastMessageTimestamp}}]` |
| Thread | `messenger/get-messages-by-subscription` | `{subscriptionId, loadAll:false}` | `{messages:[{text, createdAt, sender:{firstname,lastname}, attachments}], hasMoreMessages}` |
| **Elternbriefe** | `letters/get-letters` | `{}` | `[{title, id, sentDate, studentStatuses:[{readTimestamp, studentId}]}]` |
| **Stundenplan** | `schedules/get-actual-lessons` | `{student:{…}, start, end}` | `[{date, classHour:{number}, type, isCancelled, originalLessons:[{subject,teachers,room}]}]` |

## Noch nicht eingebaut (Kandidaten für neue Features)
- **Zahlungen** (`invoicing/poqa`, model `modules/invoicing/general-invoice`): `studentInvoices[].{sum, paidSum, paid, sentTimestamp}`, `items[].studentItems[].{amount, paid}`, `dueDate`, `bankAccount`.
- **Lernen** (`learning/get-learning-courses`, `get-course-units`, `get-learning-unit`): Aufgaben/Material mit `studentStatuses[].{seen, done}`.
- **Klassenbuch-Themen** (`classbook/get-topics`): `[{date, subject, topic}]` (182 Einträge im Sample).
- **Nachsitzen** (`detention/poqa`, model `modules/detention/detention-event-attendance`).
- **Ferien/Schultage** (`schedules/get-occurrences-of-current-term`): `[{name, dates:[…]}]` — nutzbar, um schulfreie Tage im Stundenplan zu markieren.
