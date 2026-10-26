# GCC operating system

Draft, 26 Oct 2026. Evidence: GCC Growth board database (266 items, read 26 Oct), ADIPEC Card Leads tracker
(22 leads), live routines, artifact gallery (56 artifacts).

## Principle

Every kind of thing has one home. Everything else links to it.

| Thing | Home (system of record) | Written by | Read by |
| --- | --- | --- | --- |
| Accounts, contacts, deals, customer facts, CRM tasks | HubSpot (Monaco mirrors notes) | Reconcile agent, people | Health, watchdog, digest |
| Outreach conversations (one sheet per lead, per campaign) | Campaign tracker in the Card Leads format | Outreach agent drafts, people send | Watchdog, RAM |
| Yana's work: plan, internal actions, decisions | GCC Growth board | Scout (`cap-`), health (`health-`), watchdog (`watch-`), Yana | Yana, Sari agenda |
| Audit trail of automated CRM writes and approvals | Slack List "GCC CRM sync log" | Reconcile, health | Watchdog |
| How the automations work | This repo (`automation/`) | Changes reviewed here first | Watchdog (drift check) |

## Agents

| Agent | Job | Writes to | Cadence (Madrid) |
| --- | --- | --- | --- |
| Reconcile | Keep HubSpot true to the sources | HubSpot, Monaco notes, sync log | Hourly 07:47 to 20:47, weekdays |
| Health | One action per account that needs it | Board `health-*` | 08:17, 14:17 weekdays |
| Scout | Capture asks, close what is done, first-pass research | Board `cap-*` | 08:37, 12:37, 16:37, 20:37 daily |
| Outreach (next) | Draft sheets for each campaign lead | Campaign tracker | On demand per campaign |
| Watchdog | Check every agent, surface decisions, push | Board `watch-*`, phone | 08:43 daily |
| Morning brief | Day view | Brief page | 07:47 weekdays |

## What the board shows today (26 Oct)

1. 144 open items, 139 owned by Yana.
2. 109 open items (76%) have no due date; 6 are overdue; 2 carry a Must-Move week.
3. 47 open items are outreach rows (`out-adipec-*` 22, `out-wetex-*` 24, other 1). The 22 ADIPEC rows repeat the Card
   Leads tracker (17 match by company) and the 19 HubSpot tasks: one lead, three places.
4. Items carry fields from three generations (`deskId`, `bet`, `workstream`, `timing` on 157 imported items).

## Proposed moves

1. Outreach leaves the board. Each campaign gets a tracker in the Card Leads format. The board keeps one item per
   campaign ("ADIPEC card outreach: 22 leads, 0 sent") linking to its tracker. The 22 `out-adipec-*` items move to
   status Moved with a note pointing to the tracker; the 24 `out-wetex-*` items become the WETEX tracker. Open items
   fall from 144 to about 100.
2. HubSpot keeps the follow-up tasks; the tracker keeps the conversation; the board keeps the plan.
3. The watchdog flags the 10 oldest undated items each Monday, so the Unscheduled list shrinks every week.
4. RAM reads stage dates from the trackers (sent, replied, meeting set, met) and from HubSpot (deal stages), one set
   of numbers.
