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

## Requirement
Monaco and Apollo connector tools must be set to "Always allow" at claude.ai/customize/connectors, or unattended Monaco writes fail and are logged as Failed write.
