# Outreach standard (RAM)

Every outreach campaign runs in the format of the ADIPEC Card Leads tracker
(https://claude.ai/artifact/8k4VjuNRRzFL62k9uqwAHv, 26 Oct 2026): a list of leads, one working sheet per lead,
saved in the page's shared database (collection `leads`). Future outreach automation writes to this format and
nothing else. Messages are drafted by automation and sent by a person.

## Lead sheet (one document per lead)

| Field | Meaning |
| --- | --- |
| order | Position in the send sequence |
| name, title, company | As on the card or the CRM, never inferred |
| met | Where and when we met them, with the source |
| angle | Why this lead, what we lead with |
| email, linkedin, hubspot | Contact routes and the HubSpot record URL; `crmNote` for gaps |
| channel | LinkedIn, Email, "LinkedIn, then email", WhatsApp, In person |
| invite | LinkedIn invite note, max 300 characters (LinkedIn leads only) |
| subject, message | Email subject (email only) and the message draft |
| fallback | Second route if the first fails |
| sendAt | Planned send, in their working hours, with both time zones |
| status | Need details, To send, Sent, Replied, Meeting set, Met, Nurture, Closed |
| sentOn, reply, nextStep, notes | What happened and what comes next |
| updatedAt | ISO time of the last change |

## Sending rules (Sari, Slack DM)

1. Their working hours. Gulf leads 08:00 to 09:00 Gulf (05:00 to 06:00 Spain). Never at night.
2. In-person meetings 11:00 to 15:00 Gulf.
3. No client names: "global EPCs and OEMs, including established international pump manufacturers".
4. Email carries the Ranger Intro Lean PDF. LinkedIn first touches carry no attachment.
5. Senior leads: ask for a mobile number so Sari can call or WhatsApp on the day.
6. Confirmed = they know who we are, where, and date and time. Then it is logged in HubSpot.

## Fields to add for RAM (proposed, not yet in the tracker)

RAM needs every stage to carry a number. The tracker has `sentOn` only.

| Field | Why |
| --- | --- |
| campaign | e.g. "ADIPEC 2026 cards", so channels and campaigns can be compared |
| tier | Named-account tier (1, 2, 3) |
| repliedOn, meetingOn, metOn | Stage dates: reply rate, time to reply, meeting rate per campaign and channel |
| touch | 1, 2, 3: which follow-up this is |

Status to HubSpot lead status: Sent -> In Progress, Replied / Meeting set / Met -> Connected (same rule as
`sync/planner.py`). Board items stay the plan; HubSpot keeps the tasks; the tracker keeps the conversation.
