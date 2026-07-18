# Discovered Schulmanager `api/calls` Endpoints

`moduleName / endpointName` observed from real network captures (`tools/capture-api.js`).
Field details (parameters/response) will be added once a v2 capture (fully expanded) is available.

## Already used in the wrapper
| Module | Endpoint | Purpose |
|---|---|---|
| `schedules` | `get-actual-lessons` | Timetable (incl. substitutions) |
| `schedules` | `get-class-hours` | Lesson times |
| `classbook` | `get-homework` | Homework |
| `exams` | `get-exams` | Exams |
| `exams` | `poqa` | Calendar events (legacy path) |
| `grades` | `get-grading-information-for-student` | Grades |
| `letters` | `get-letters` | Parent letters |
| `messenger` | `get-subscriptions` | Message threads |

## Newly discovered (capture 2026-07-18)
| Module | Endpoint | Presumed purpose | Value |
|---|---|---|---|
| `classbook` | `get-statistics` | **Absence statistics** (route `classbook.reports2.student.statistics`, params `{studentId, start, end}`) | high |
| `classbook` | `poqa` | **Absence entries** (ORM findAll on the reports2 route) | high |
| `classbook` | `get-topics` | Lesson topics (class register) | medium |
| `classbook` | `get-tiles` | Class register tiles | low |
| `classbook` | `get-upcoming-conferences` | Upcoming conferences/meetings | medium |
| `calendar` | `get-events-for-user` | **Appointments** — clean endpoint instead of the `exams/poqa` hack | high |
| `schedules` | `get-substitution-texts-for-widget` | Substitution texts (free text) | medium |
| `schedules` | `get-occurrences-of-current-term` | School days/appointment structure of the term | medium |
| `invoicing` | `poqa` | **Payments/invoices** | high |
| `detention` | `poqa` | Detention | low |
| `documents` | `documents-visible` | Documents module visible? | low |
| `messenger` | `count-new-messages` | Number of new messages (badge) | medium |
| `letters` | `get-current-term`, `poqa`, `user-can-see-setting-for-letter-mailing` | Parent letter metadata | low |
| `null` | `get-current-next-or-previous-term` | Current/next term | medium |

## Confirmed & implemented (v2 capture 2026-07-18)
| Feature | Endpoint | Params | Response (core) |
|---|---|---|---|
| **Absences** | `classbook/get-history-absences-list` | `{term:{start,end,id}, student:{…,class:{…}}}` | `[{date, from, until, excused, comment, sickNote, exemptionRequest:{comment,isInternal}}]` |
| (accompanying period) | `classbook/get-current-next-or-previous-term` | `{}` | `{start, end, id, preventAsCurrentTerm}` |
| **Appointments** | `calendar/get-events-for-user` | `{start, end, includeHolidays}` | `{nonRecurringEvents:[{summary,start,end,location,description,allDay,categoryId}], recurringEvents}` |
| **Grades** (+ individual grades) | `grades/get-grading-information-for-student` | `{studentId, termId, start, end, gradingPeriodType:"entireYear"}` | `{courses, gradingEvents[].grades[].value, indiviualGrades[…], typePresets, finalGrades}` |
| **Homework** | `classbook/get-homework` | `{student:{id}}` | `[{date, subject, homework}]` — **no ID** → content-hash ID |
| **Messages** | `messenger/get-subscriptions` | `{all:false, includeArchived:false, reason:"whenLoadedSubscriptions"}` | `[{id, unreadCount, thread:{subject, senderString, lastMessageTimestamp}}]` |
| Thread | `messenger/get-messages-by-subscription` | `{subscriptionId, loadAll:false}` | `{messages:[{text, createdAt, sender:{firstname,lastname}, attachments}], hasMoreMessages}` |
| **Parent letters** | `letters/get-letters` | `{}` | `[{title, id, sentDate, studentStatuses:[{readTimestamp, studentId}]}]` |
| **Timetable** | `schedules/get-actual-lessons` | `{student:{…}, start, end}` | `[{date, classHour:{number}, type, isCancelled, originalLessons:[{subject,teachers,room}]}]` |

## Not yet integrated (candidates for new features)
- **Payments** (`invoicing/poqa`, model `modules/invoicing/general-invoice`): `studentInvoices[].{sum, paidSum, paid, sentTimestamp}`, `items[].studentItems[].{amount, paid}`, `dueDate`, `bankAccount`.
- **Learning** (`learning/get-learning-courses`, `get-course-units`, `get-learning-unit`): assignments/materials with `studentStatuses[].{seen, done}`.
- **Class register topics** (`classbook/get-topics`): `[{date, subject, topic}]` (182 entries in the sample).
- **Detention** (`detention/poqa`, model `modules/detention/detention-event-attendance`).
- **Holidays/school days** (`schedules/get-occurrences-of-current-term`): `[{name, dates:[…]}]` — usable to mark non-school days in the timetable.
