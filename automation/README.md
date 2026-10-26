# GCC CRM automation

Keeps HubSpot (primary) and Monaco (mirror) current from Gmail, Slack, Granola, Calendar and Monaco LinkedIn, and flags anything unclear to Yana once a day.

## Architecture

| Layer | What | When | Writes |
| --- | --- | --- | --- |
| 1. Reconcile agent | `reconcile_prompt.md` | Hourly, weekdays 07:47 to 20:47 Madrid | HubSpot deal notes, next steps, tasks, contact fields; Monaco opportunity notes; Slack List log |
| 2. Daily digest | `digest_prompt.md` | Weekdays 08:21 Madrid | Slack draft in Yana's DM, one List row, push notification |
| 3. Identity sync | `../sync/PLAYBOOK.md` | Existing, separate | Contact and company identity fields |
| Log and flags | Slack List "GCC CRM sync log" (F0C9J845HQW) | Every run | Update, Exception, Critical change, Failed write, RUN rows |

## Principles
- Auto-apply safe, sourced updates. Flag anything ambiguous as an Exception row phrased as a question.
- Never write stage, amount, owner, close date or probability. Critical changes go to Ibraheem as List rows.
- One living "Status, " note per deal: Status / Next step / Context / History / Sources. Sources keys make runs idempotent.
- Gulf time only in CRM notes.
- Nothing customer-facing is ever sent.

## Requirement
Monaco and Apollo connector tools must be set to "Always allow" at claude.ai/customize/connectors, or unattended Monaco writes fail and are logged as Failed write.
