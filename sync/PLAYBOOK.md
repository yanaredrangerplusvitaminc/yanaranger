# HubSpot <-> Monaco daily sync: run playbook

The daily run follows these steps exactly. It uses the HubSpot and Monaco connectors (no API keys) and
`sync/planner.py` for every decision, so each run is consistent and reviewable.

Scope: contacts and companies of **Yana Rova** and **Sari Saadi** (IDs in `sync/config.json`).

## Modes

- `full`: first run, or when asked. Looks at every in-scope record.
- `incremental` (default, daily): only records changed in the last `lookback_hours` (26h, so runs overlap
  and nothing is missed if one is late).

Work in a scratch directory, `WORK=$(mktemp -d)`. Never commit snapshot files: they hold personal data.

## 1. Fetch HubSpot

1. `hubspot_contacts.json`: `search_crm_objects` on CONTACT, `hubspot_owner_id IN [168888360, 96079443]`
   (incremental: add `lastmodifieddate GTE <since>`), page with `offset` until `total` is reached.
   Properties: `firstname, lastname, email, phone, jobtitle, company, hs_linkedin_url, lifecyclestage,
   hs_lead_status, hubspot_owner_id, associatedcompanyid`. Save each as
   `{"id", "properties", "company_id": associatedcompanyid or null}`.
2. `hubspot_companies.json`: same on COMPANY with `name, domain, lifecyclestage, hubspot_owner_id,
   linkedin_company_page` (incremental: `hs_lastmodifieddate GTE <since>`), plus any company referenced
   by a contact's `company_id`.

## 2. Fetch Monaco

1. `monaco_contacts.json`: `list_contacts` with `connected_to is "Yana Rova"`, then again with
   `"Sari Saadi"`, `page_size` 500, all pages. Incremental: keep rows whose `updated_at` or
   `last_activity_at` is after `<since>`. Merge by `id`, recording `"_connected_to": [names]`.
2. `monaco_accounts.json`: `list_accounts` with `owner is <monaco_user_id>` for both owners, plus
   `get_account` for every `account_id` referenced by a fetched contact.
3. `monaco_conversations.json`: for each fetched contact whose last inbound or outbound type is a
   LinkedIn message: `get_messages(contact_id, channels=["linkedin"])`, then `get_conversation` for each
   `conversation_id` (all pages). Save as
   `{contact_id: [{"chat_id", "owner_name", "messages": [{"timestamp", "direction", "sender", "text"}]}]}`.
   `owner_name` is whichever of Yana Rova / Sari Saadi sent the outbound messages.

## 3. Cross-lookups (prevents duplicates)

- `monaco_lookup_contacts.json`: for each HubSpot contact not found in `monaco_contacts.json`, look it
  up in Monaco with `list_contacts` (`email equals`, else `linkedin_url contains <slug>`).
  For those with no email and no company domain, also find their company in Monaco
  (`list_accounts`, name contains) and add the account to `monaco_accounts.json`.
- `hubspot_lookup_contacts.json`: for each Monaco contact with a LinkedIn conversation not found in
  `hubspot_contacts.json`, search all of HubSpot (any owner) by email, else `hs_linkedin_url
  CONTAINS_TOKEN <slug>`. Include `company_id` as above.
- `hubspot_lookup_companies.json`: HubSpot companies matching the domains / names of those contacts'
  Monaco accounts.
- `hubspot_notes.json`: NOTE objects associated with every matched HubSpot contact whose body contains
  `monaco-chat:`. Save as `{"id", "contact_id", "body": hs_note_body}`.

## 4. Plan

```
python3 sync/planner.py "$WORK"
```

Read `$WORK/plan.json`. Safety stop: on an incremental run, if `hubspot.contact_creates` +
`monaco.contact_creates` is above 60, do not write anything. Report the counts and stop.

## 5. Execute

Run in this order. One failure never stops the run: log it and continue.

Duplicate guard: immediately before every create (either system), search once more by email, then by
LinkedIn URL (HubSpot: any owner). If the record now exists, update it instead of creating. This covers
anything created by a person between the fetch and the write.

Monaco:
1. `contact_creates`: `upsert_contact(payload)`, then add `tag` with `modify_entity_tags`
   (create the tag inline if it does not exist).
2. `contact_updates`: `upsert_contact(payload)`. A 409 goes to the conflicts list.
3. `contact_notes`: `act_on_entities` `update_contacts`, field `notes`, one contact per call.
4. `contact_tags`: `modify_entity_tags` add `add`, remove each of `remove`.
5. `account_upserts`: `upsert_account(payload)`.

HubSpot (`manage_crm_objects`, max 10 objects per call, confirmation pre-approved by the owner for
this routine):
1. `company_creates`, then `contact_creates`, keeping a map of `key` -> new id.
2. `contact_updates`.
3. `associations`: contact to company, resolving `key` through the map.
4. `notes`: create a NOTE (`hs_note_body` = `body`, `hs_timestamp` = `timestamp`,
   `hubspot_owner_id` = `owner_id`) associated to the contact, or update `note_id` if set.
   If NOTE writing is unavailable, skip and report "notes blocked: HubSpot connector needs
   reconnecting".

## 6. Report

End the run with a short summary: counts per action, skipped (with reasons), conflicts (with record
links), the `review` list (possible duplicates and replies on closed statuses, each with both record
links), failures. Times in Madrid and Gulf time.

## Rules the planner enforces

| What | Direction | Rule |
|---|---|---|
| Lifecycle stage, lead status, owner | HubSpot -> Monaco | Shown in a managed `[HubSpot sync]` block in contact notes, plus one `HS <lead status>` tag. Text outside the block is never touched. |
| Company lifecycle | HubSpot -> Monaco | Sets account status (lead/MQL -> Prospecting, SQL/opportunity -> Opportunity, customer -> Customer, other -> Nurture). |
| Company owner | HubSpot -> Monaco | Set only when the Monaco account has no owner, otherwise logged as a conflict. |
| LinkedIn conversations | Monaco -> HubSpot | One HubSpot note per LinkedIn thread, updated when new messages arrive. |
| Lead status | Monaco -> HubSpot | Follows the conversation (LinkedIn or email): we messaged, no reply -> In Progress; they replied or the conversation is live -> Connected. Moves forward only (New/Open/Attempted -> In Progress -> Connected). Never changes Open Deal, Unqualified, Bad Timing or No Show; a fresh reply on one of those goes to review. The new status reaches the Monaco tag and notes in the same run. |
| Name, email, title, phone, LinkedIn | both | Fill blanks only. Never overwrite. Differing emails logged. |
| New records | HubSpot -> Monaco | Every owned HubSpot contact with an email (or LinkedIn plus company domain). |
| New records | Monaco -> HubSpot | Only people with a LinkedIn conversation, not every connection. Owner = who ran the conversation. |
| Duplicates | both | Match on email, then LinkedIn URL. One create per person and per company per run, even when the person sits on two records. Same name + same company with no shared email/LinkedIn is never created: it goes to review. Final re-check right before each create. |
| Deletes | never | |
