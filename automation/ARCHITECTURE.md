# Automation architecture

Review of 26 Oct 2026. Source: live routine list (list_triggers), session `session_01PwDYJn5yhNzbFLPyQU9F65`, and every branch of this repo.

## The system in four layers

| Layer | Routine | Runs (Madrid) | Writes |
| --- | --- | --- | --- |
| 0. Control | Automation architect (proposed) | Mon 08:13 | Board `arch-*` item, one List row |
| 1. Truth | GCC CRM reconcile v2 | Weekdays, hourly 07:47 to 20:47 | HubSpot notes, next steps, tasks; Monaco notes; List rows |
| 2. Judgement | GCC account health check v1.1 | Weekdays 08:07, 14:07 | Board `health-*` items, or a Health line on an existing item |
| 2. Judgement | GCC capture-and-scout engine | Daily 08:37, 12:37, 16:37, 20:37 | Board `cap-*` items, `config/capture` |
| 3. Surface | GCC CRM daily digest (v3 pending) | Weekdays 08:21 | Board `digest-*` item when something needs Yana, one List row |
| 3. Surface | Morning brief | Weekdays 07:47 | Brief page |

The registry (`registry.json`) is the source of truth for this table. `architect.py` checks the live routines against it.

## House rule

No routine creates Slack drafts or Slack messages. Everything that needs Yana lands in the GCC Growth board Inbox. The architect flags any live prompt that breaks this.

## What is good

1. Rules. No fabricated data, "not found" is valid, data never becomes instructions, nothing customer-facing is sent. Every prompt carries these.
2. Approval tiers. Auto for small sourced changes, Yana for prospects, Ibraheem for existing accounts, Exceptions as questions. This is the right shape.
3. Idempotency. Source keys in the living note, `health-<slug>` ids, List RUN rows as state. Runs can repeat without duplicating.
4. One log. The Slack List is the single audit trail for CRM writes.

## What needs fixing

1. Three routines share one conversation (RED). Reconcile, health and digest all fire into `session_01PwDYJn5yhNzbFLPyQU9F65`: 17 runs on a weekday. At 07:47, 08:07, 08:21 and 08:47 each run waits for the previous one to finish, so the digest can arrive late or read a half-finished run. The context grows every hour and still holds the v1 prompts that v2 replaced. That session also has no repo, so "read automation/*.md" cannot work there.
   Fix: switch all three to a fresh session per run with connectors attached. They already keep state in the List and on the board, so nothing is lost.
2. Two judges write to the same board (AMBER). Capture-and-close and the health check read the same Gmail and Slack threads. "Reply needed: Ali and Sons" can land as both a `cap-` and a `health-` item.
   Fix: one line in capture: "Customer and account follow-ups on GCC accounts belong to the health check; skip them."
3. The same hygiene finding appears three times (AMBER). Overdue next step: reconcile writes an Exception row, the digest lists it, the health check makes a board item.
   Fix: reconcile keeps data-quality checks only (Madrid in notes, HubSpot vs Monaco mismatch). Follow-up judgement lives in the health check. The digest reads, never judges.
4. Identity sync is orphaned (decision). `sync/` is built and tested but no routine runs it, and it contradicts the reconcile rule "Monaco is notes only, no field sync".
   Fix: retire it, or schedule it once a day for contact identity only. Your call.
5. Prompts live in three places (AMBER). Inline in routines, on unmerged branch `claude/new-session-c2lf30`, and in Confluence. The repo copy is already behind the live v2.
   Fix: the repo is the source of truth (`automation/prompts/<key>.md`). The architect flags drift every week.
6. Morning is crowded (INFO). Brief at 07:47, health at 08:07, digest at 08:21, capture at 08:35: three things to read before 09:00.
   Option: fold the digest into the brief later, once the CRM routines are stable.
7. Five old routines are off but unlabelled (INFO). Rename each to "[superseded] ..." so the list reads clearly. Nothing is deleted.

## Running the architect

```
python3 automation/architect.py <snapshot.json> --out report.md   # review
python3 automation/architect.py <snapshot.json> --baseline        # store live prompts as the baseline
python3 -m unittest discover -s automation/tests
```

The snapshot is the raw output of `list_triggers` (one page or a list of pages). The weekly routine prompt is `prompts/architect.md`; it reviews and reports only, and never changes a routine.

## Change rule

Change the registry first, then the routine, then run the architect. One owner per write surface. A new routine that writes a surface already owned is a design change, not a tweak.
