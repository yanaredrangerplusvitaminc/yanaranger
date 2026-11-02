# GCC CRM automation

Keeps HubSpot (primary) and Monaco (mirror) current from Gmail, Slack, Granola, Calendar, Confluence and Monaco LinkedIn, keeps the GCC Growth board honest, and flags anything unclear to Yana once a day.

## Architecture

| Layer | What | When (Madrid) | Writes |
| --- | --- | --- | --- |
| 1. Reconcile | `reconcile_prompt.md` | Hourly at :47, 07 to 20, weekdays | HubSpot deal notes, next steps, tasks, blank contact fields; Monaco opportunity notes; Slack List log |
| 2. Daily digest | `digest_prompt.md` | Weekdays 08:21 | Slack draft in Yana's DM, one List row |
| 3. Account health (GTM) | `health_prompt.md` | Weekdays 08:07 and 14:07 | One `health-<account>` item per account on the GCC Growth board, or a one-line note on the board item that already covers it; one List row |
| 4. Capture and scout | Yana's own routine (not in this repo) | Daily 08:37, 12:37, 16:37, 20:37 | Board items `cap-*`, including "Reply needed" |
| 5. Identity sync | `../sync/PLAYBOOK.md` | Existing, separate | Contact and company identity fields |
| Log and flags | Slack List "GCC CRM sync log" (F0C9J845HQW) | Every run | Update, Exception, Critical change, Failed write, RUN, DIGEST, HEALTH rows |

Layers 1 to 3 run in one persistent session that holds the connectors.

## Principles
- Auto-apply safe, sourced updates. Flag anything ambiguous as an Exception row phrased as a question.
- Important changes need approval as Critical change rows: Yana approves prospects, Ibraheem approves existing accounts.
- One living "Status, " note per deal: Status / Next step / Context / History / Sources. Sources keys make runs idempotent.
- Gulf time only in CRM notes.
- Nothing customer-facing is ever sent.

## Follow-up rules (Sari, team huddle 1 Nov 2026)
- Yana drives follow-up momentum across the GCC pipeline, in sync with Sari. Prospects judge our delivery speed by our follow-up speed, so every open deal keeps a live, dated next step. Yana tracks and nudges follow-ups owned by others (Ibraheem in particular).
- ADIPEC etiquette: no follow-up to ADIPEC leads during ADIPEC (2 to 5 Nov 2026) or the week after (9 to 13 Nov). ADIPEC follow-ups resume Mon 16 Nov 2026. Replies to messages they send us, and logistics for meetings already booked, are fine.

## Requirement
Monaco and Apollo connector tools must be set to "Always allow" at claude.ai/customize/connectors, or unattended Monaco writes fail and are logged as Failed write.
