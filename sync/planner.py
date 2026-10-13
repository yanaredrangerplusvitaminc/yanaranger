"""HubSpot <-> Monaco sync planner.

Reads JSON snapshots of both systems from a work directory and writes plan.json:
the exact list of changes to make on each side. It never calls an API. The daily
run (see PLAYBOOK.md) fetches the snapshots, runs this, then executes the plan.

Rules, in short:
- Match people by email, then by normalised LinkedIn URL. Match companies by
  domain, then by name.
- HubSpot owns status: lifecycle stage, lead status, owner, company details.
  These go to Monaco as a managed block in contact notes, an "HS <status>" tag,
  and account status/owner.
- Monaco owns LinkedIn: each LinkedIn thread becomes one HubSpot note, updated
  when new messages arrive.
- Identity fields (name, email, title, phone, LinkedIn) only fill blanks. A
  non-empty value is never overwritten; differing emails are logged as conflicts.
- Nothing is ever deleted.

Usage: python3 sync/planner.py <work_dir> [--config sync/config.json]
"""

from __future__ import annotations

import argparse
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from zoneinfo import ZoneInfo

NOTES_START = "[HubSpot sync]"
NOTES_END = "[/HubSpot sync]"
NOTE_MARKER_RE = re.compile(r"monaco-chat:\s*([^\s|<]+)")
NOTE_LAST_RE = re.compile(r"last:\s*([^\s|<]+)")
LOCAL_TZ = ZoneInfo("Europe/Madrid")
# Monaco account statuses by how far along they are. Nurture, disqualified and churned are
# deliberate human calls, so HubSpot "lead" never overwrites them.
STATUS_RANK = {"NEW": 0, "INBOUND": 1, "PROSPECTING": 1, "NURTURE": 2, "DISQUALIFIED": 2, "OPPORTUNITY": 3,
               "CHURNED": 3, "CUSTOMER": 4}


# ---------------------------------------------------------------- normalising

def norm_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return None
    return value.strip().lower()


def norm_linkedin(value: str | None) -> str | None:
    """Reduce any LinkedIn profile URL to 'linkedin.com/in/<slug>'."""
    if not value:
        return None
    raw = value.strip()
    if "://" not in raw:
        raw = "https://" + raw
    parsed = urlparse(raw)
    host = parsed.netloc.lower()
    if not host.endswith("linkedin.com"):
        return None
    parts = [p for p in unquote(parsed.path).lower().split("/") if p]
    if len(parts) < 2 or parts[0] not in ("in", "pub"):
        return None
    return f"linkedin.com/in/{parts[1]}"


def norm_domain(value: str | None) -> str | None:
    if not value:
        return None
    raw = value.strip().lower()
    if "://" in raw:
        raw = urlparse(raw).netloc
    raw = raw.split("/")[0]
    if raw.startswith("www."):
        raw = raw[4:]
    return raw or None


def norm_name(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^a-z0-9 ]", " ", value.lower())
    cleaned = re.sub(r"\b(inc|ltd|llc|gmbh|ag|sa|plc|co|corp|limited|fze|fzco|llp)\b", " ", cleaned)
    cleaned = " ".join(cleaned.split())
    return cleaned or None


def blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def first_domain(account: dict | None) -> str | None:
    if not account:
        return None
    for d in account.get("domains") or []:
        if norm_domain(d):
            return norm_domain(d)
    return norm_domain((account.get("company") or {}).get("domain"))


# ---------------------------------------------------------------- loading

def load(work: Path, name: str, default):
    path = work / name
    if not path.exists():
        return default
    return json.loads(path.read_text())


class Index:
    """Lookup by email / LinkedIn for a list of person records."""

    def __init__(self, records, email_of, linkedin_of):
        self.by_email: dict[str, dict] = {}
        self.by_li: dict[str, dict] = {}
        for r in records:
            e, li = email_of(r), linkedin_of(r)
            if e:
                self.by_email.setdefault(e, r)
            if li:
                self.by_li.setdefault(li, r)

    def find(self, email, linkedin):
        if email and email in self.by_email:
            return self.by_email[email]
        if linkedin and linkedin in self.by_li:
            return self.by_li[linkedin]
        return None


def hs_email(c):
    return norm_email(c["properties"].get("email"))


def hs_li(c):
    return norm_linkedin(c["properties"].get("hs_linkedin_url"))


def mo_email(c):
    return norm_email(c.get("email"))


def mo_li(c):
    return norm_linkedin(c.get("linkedin_url"))


# ---------------------------------------------------------------- HubSpot -> Monaco

def notes_block(hs_contact, company_name, cfg) -> str:
    p = hs_contact["properties"]
    owner = owner_by_hs_id(cfg, p.get("hubspot_owner_id"))
    lines = [
        NOTES_START,
        " | ".join([
            f"Owner: {owner['name'] if owner else 'Unassigned'}",
            f"Lifecycle: {cfg['lifecycle_labels'].get(p.get('lifecyclestage') or '', p.get('lifecyclestage') or '-')}",
            f"Lead status: {cfg['lead_status_labels'].get(p.get('hs_lead_status') or '', p.get('hs_lead_status') or '-')}",
        ]),
    ]
    if company_name:
        lines.append(f"Company: {company_name}")
    lines.append("HubSpot: " + cfg["hubspot"]["contact_url"].format(id=hs_contact["id"]))
    lines.append(NOTES_END)
    return "\n".join(lines)


def merge_notes(existing: str | None, block: str) -> str:
    """Replace the managed block in Monaco notes, or append it. Other text is untouched."""
    existing = existing or ""
    start, end = existing.find(NOTES_START), existing.find(NOTES_END)
    if start != -1 and end != -1 and end > start:
        return existing[:start] + block + existing[end + len(NOTES_END):]
    if not existing.strip():
        return block
    return existing.rstrip() + "\n\n" + block


def hs_tag(hs_contact, cfg) -> str | None:
    status = hs_contact["properties"].get("hs_lead_status")
    if not status:
        return None
    label = cfg["lead_status_labels"].get(status, status)
    return cfg["monaco_tag_prefix"] + re.sub(r"[^A-Za-z0-9 ]", "", label)


def owner_by_hs_id(cfg, hs_id):
    return next((o for o in cfg["owners"] if o["hubspot_owner_id"] == str(hs_id or "")), None)


def owner_by_name(cfg, name):
    return next((o for o in cfg["owners"] if o["name"] == name), None)


def plan_hubspot_to_monaco(snap, cfg, plan):
    owned_ids = {o["hubspot_owner_id"] for o in cfg["owners"]}
    mo_all = snap["monaco_contacts"] + snap["monaco_lookup_contacts"]
    mo_index = Index(mo_all, mo_email, mo_li)
    companies = {str(c["id"]): c for c in snap["hubspot_companies"]}
    accounts_by_name = {}
    for a in snap["monaco_accounts"]:
        if norm_name(a.get("name")):
            accounts_by_name.setdefault(norm_name(a["name"]), a)
    tag_prefix = cfg["monaco_tag_prefix"]

    for hc in snap["hubspot_contacts"]:
        p = hc["properties"]
        if str(p.get("hubspot_owner_id") or "") not in owned_ids:
            continue
        email, li = hs_email(hc), hs_li(hc)
        company = companies.get(str(hc.get("company_id") or ""))
        company_name = (company or {}).get("properties", {}).get("name") or p.get("company")
        block = notes_block(hc, company_name, cfg)
        tag = hs_tag(hc, cfg)
        mc = mo_index.find(email, li)

        if mc is None:
            if not email and not li:
                plan["skipped"].append({"side": "monaco", "hubspot_id": hc["id"], "reason": "no email or LinkedIn"})
                continue
            domain = norm_domain((company or {}).get("properties", {}).get("domain"))
            account = accounts_by_name.get(norm_name(company_name)) if not domain else None
            if li and not email and not domain and not account:
                plan["skipped"].append({"side": "monaco", "hubspot_id": hc["id"],
                                        "reason": "LinkedIn only, company not found in Monaco"})
                continue
            payload = {k: v for k, v in {
                "email": p.get("email") if email else None,
                "linkedin_url": p.get("hs_linkedin_url") if li else None,
                "first_name": p.get("firstname"),
                "last_name": p.get("lastname"),
                "title": p.get("jobtitle"),
                "phone_number": p.get("phone"),
                "domain": domain,
                "account_id": account["id"] if account else None,
                "notes": block,
            }.items() if not blank(v)}
            plan["monaco"]["contact_creates"].append({"hubspot_id": hc["id"], "payload": payload, "tag": tag})
            continue

        # Fill blanks on the matched Monaco contact.
        fills = {}
        for mo_key, hs_key in (("first_name", "firstname"), ("last_name", "lastname"), ("title", "jobtitle"),
                               ("phone_number", "phone"), ("linkedin_url", "hs_linkedin_url"), ("email", "email")):
            if blank(mc.get(mo_key)) and not blank(p.get(hs_key)):
                fills[mo_key] = p.get(hs_key)
        if "email" in fills:
            holder = mo_index.by_email.get(norm_email(fills["email"]))
            if holder is not None and holder["id"] != mc["id"]:
                fills.pop("email")
                plan["conflicts"].append({"type": "email_on_other_monaco_contact", "hubspot_id": hc["id"],
                                          "monaco_id": mc["id"], "email": p.get("email")})
        elif email and mo_email(mc) and email != mo_email(mc):
            plan["conflicts"].append({"type": "email_differs", "hubspot_id": hc["id"], "monaco_id": mc["id"],
                                      "hubspot_email": p.get("email"), "monaco_email": mc.get("email")})
        if fills:
            # Upsert matches on the Monaco record's own identifiers, so it updates this contact.
            ident = {"email": mc.get("email")} if mo_email(mc) else {"linkedin_url": mc.get("linkedin_url"),
                                                                      "account_id": mc.get("account_id")}
            plan["monaco"]["contact_updates"].append({"monaco_id": mc["id"], "hubspot_id": hc["id"],
                                                      "payload": {**ident, **fills}})

        new_notes = merge_notes(mc.get("notes"), block)
        if new_notes != (mc.get("notes") or ""):
            plan["monaco"]["contact_notes"].append({"monaco_id": mc["id"], "notes": new_notes})

        current = {t.get("name") if isinstance(t, dict) else t for t in mc.get("tags") or []}
        current_hs = {t for t in current if t and t.startswith(tag_prefix)}
        remove = sorted(current_hs - {tag})
        if (tag and tag not in current) or remove:
            plan["monaco"]["contact_tags"].append({"monaco_id": mc["id"], "add": tag if tag not in current else None,
                                                   "remove": remove})


def plan_companies_to_monaco(snap, cfg, plan):
    owned_ids = {o["hubspot_owner_id"] for o in cfg["owners"]}
    by_domain, by_name = {}, {}
    for a in snap["monaco_accounts"]:
        for d in (a.get("domains") or []) + [(a.get("company") or {}).get("domain")]:
            if norm_domain(d):
                by_domain.setdefault(norm_domain(d), a)
        if norm_name(a.get("name")):
            by_name.setdefault(norm_name(a.get("name")), a)

    for co in snap["hubspot_companies"]:
        p = co["properties"]
        if str(p.get("hubspot_owner_id") or "") not in owned_ids:
            continue
        owner = owner_by_hs_id(cfg, p.get("hubspot_owner_id"))
        status = cfg["lifecycle_to_monaco_account_status"].get(p.get("lifecyclestage") or "")
        domain = norm_domain(p.get("domain"))
        acct = (by_domain.get(domain) if domain else None) or by_name.get(norm_name(p.get("name")))

        if acct is None:
            if not domain:
                plan["skipped"].append({"side": "monaco", "hubspot_company_id": co["id"], "reason": "company has no domain and no name match"})
                continue
            payload = {k: v for k, v in {"domain_lookup": domain, "name": p.get("name"), "status": status,
                                         "owner": owner["monaco_user_id"] if owner else None,
                                         "linkedin_url": p.get("linkedin_company_page")}.items() if not blank(v)}
            plan["monaco"]["account_upserts"].append({"hubspot_company_id": co["id"], "payload": payload})
            continue

        payload = {}
        current = (acct.get("status") or "").upper()
        if status and current != status:
            if STATUS_RANK.get(status, 0) > STATUS_RANK.get(current, 0) or current in ("", "NEW"):
                payload["status"] = status
            else:
                # Monaco is further along than HubSpot: HubSpot is likely stale. Flag, don't downgrade.
                plan["conflicts"].append({"type": "account_status_ahead_in_monaco", "hubspot_company_id": co["id"],
                                          "monaco_account_id": acct["id"], "hubspot_lifecycle": p.get("lifecyclestage"),
                                          "monaco_status": acct.get("status")})
        if owner and not (acct.get("owner") or {}).get("id"):
            payload["owner"] = owner["monaco_user_id"]
        elif owner and (acct.get("owner") or {}).get("id") != owner["monaco_user_id"]:
            plan["conflicts"].append({"type": "account_owner_differs", "hubspot_company_id": co["id"],
                                      "monaco_account_id": acct["id"], "hubspot_owner": owner["name"]})
        if payload:
            plan["monaco"]["account_upserts"].append({"hubspot_company_id": co["id"], "payload": {"id": acct["id"], **payload}})


# ---------------------------------------------------------------- Monaco -> HubSpot

def conversation_owner(mc, conv, cfg):
    o = owner_by_name(cfg, conv.get("owner_name") or "")
    if o:
        return o
    for o in cfg["owners"]:
        if o["name"] in (mc.get("_connected_to") or []):
            return o
    return cfg["owners"][0]


def fmt_ts(ts: str) -> str:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.astimezone(LOCAL_TZ).strftime("%d %b %Y %H:%M")


def note_body(mc, conv, owner) -> tuple[str, str]:
    msgs = sorted(conv["messages"], key=lambda m: m["timestamp"])
    last = msgs[-1]["timestamp"]
    name = " ".join(x for x in [mc.get("first_name"), mc.get("last_name")] if x) or "Contact"
    who_out, who_in = owner["name"].split()[0], (mc.get("first_name") or "Contact")
    rows = [f"<p><strong>LinkedIn conversation (from Monaco)</strong> - {html.escape(name)}"
            f"{' / ' + html.escape(mc['account_name']) if mc.get('account_name') else ''}</p>"]
    for m in msgs:
        sender = m.get("sender") or (who_out if m.get("direction") == "outbound" else who_in)
        text = html.escape(m.get("text") or "").replace("\n", "<br>")
        rows.append(f"<p><strong>{fmt_ts(m['timestamp'])} - {html.escape(sender)}:</strong><br>{text}</p>")
    rows.append(f"<p><em>Times in Madrid time. monaco-chat: {conv['chat_id']} | last: {last}</em></p>")
    return "".join(rows), last


def has_linkedin_activity(mc, convs) -> bool:
    if convs:
        return True
    kinds = f"{mc.get('last_inbound_type') or ''} {mc.get('last_outbound_type') or ''}".lower()
    return "linkedin message" in kinds


def plan_monaco_to_hubspot(snap, cfg, plan):
    hs_all = snap["hubspot_contacts"] + snap["hubspot_lookup_contacts"]
    hs_index = Index(hs_all, hs_email, hs_li)
    accounts = {a["id"]: a for a in snap["monaco_accounts"]}
    hs_co_by_domain, hs_co_by_name = {}, {}
    for co in snap["hubspot_companies"] + snap["hubspot_lookup_companies"]:
        if norm_domain(co["properties"].get("domain")):
            hs_co_by_domain.setdefault(norm_domain(co["properties"]["domain"]), co)
        if norm_name(co["properties"].get("name")):
            hs_co_by_name.setdefault(norm_name(co["properties"]["name"]), co)
    notes_by_chat = {}
    for n in snap["hubspot_notes"]:
        m = NOTE_MARKER_RE.search(n.get("body") or "")
        if m:
            last = NOTE_LAST_RE.search(n["body"])
            notes_by_chat[m.group(1)] = {"id": n["id"], "last": last.group(1) if last else None}
    planned_companies = {}

    for mc in snap["monaco_contacts"]:
        convs = [c for c in snap["monaco_conversations"].get(mc["id"], []) if c.get("messages")]
        if not has_linkedin_activity(mc, convs):
            continue
        email, li = mo_email(mc), mo_li(mc)
        if not email and not li:
            continue
        inbound = any(m.get("direction") == "inbound" for c in convs for m in c["messages"]) or \
            "linkedin" in (mc.get("last_inbound_type") or "").lower()
        promoted = "CONNECTED" if inbound else "ATTEMPTED_TO_CONTACT"
        owner = conversation_owner(mc, convs[0] if convs else {}, cfg)
        hc = hs_index.find(email, li)

        if hc is None:
            key = f"monaco:{mc['id']}"
            props = {k: v for k, v in {
                "firstname": mc.get("first_name"), "lastname": mc.get("last_name"), "email": mc.get("email"),
                "jobtitle": mc.get("title"), "phone": mc.get("phone_number"),
                "hs_linkedin_url": "https://www." + li + "/" if li else None,
                "company": mc.get("account_name"), "hubspot_owner_id": owner["hubspot_owner_id"],
                "lifecyclestage": "lead", "hs_lead_status": promoted,
            }.items() if not blank(v)}
            plan["hubspot"]["contact_creates"].append({"key": key, "monaco_id": mc["id"], "properties": props})
            contact_ref = {"key": key}
        else:
            contact_ref = {"id": hc["id"]}
            p, updates = hc["properties"], {}
            for hs_key, value in (("firstname", mc.get("first_name")), ("lastname", mc.get("last_name")),
                                  ("jobtitle", mc.get("title")), ("phone", mc.get("phone_number")),
                                  ("email", mc.get("email")),
                                  ("hs_linkedin_url", "https://www." + li + "/" if li else None)):
                if blank(p.get(hs_key)) and not blank(value):
                    updates[hs_key] = value
            if "email" in updates and norm_email(updates["email"]) in hs_index.by_email:
                updates.pop("email")
                plan["conflicts"].append({"type": "email_on_other_hubspot_contact", "hubspot_id": hc["id"],
                                          "monaco_id": mc["id"], "email": mc.get("email")})
            if (p.get("hs_lead_status") or "NEW") == "NEW" and p.get("hs_lead_status") != promoted:
                updates["hs_lead_status"] = promoted
            if blank(p.get("hubspot_owner_id")):
                updates["hubspot_owner_id"] = owner["hubspot_owner_id"]
            if updates:
                plan["hubspot"]["contact_updates"].append({"id": hc["id"], "monaco_id": mc["id"], "properties": updates})

        # Company association, only when HubSpot has none for this contact.
        if hc is None or ("company_id" in hc and not hc.get("company_id")):
            acct = accounts.get(mc.get("account_id"))
            domain = first_domain(acct)
            co = (hs_co_by_domain.get(domain) if domain else None) or hs_co_by_name.get(norm_name(mc.get("account_name")))
            if co is not None:
                plan["hubspot"]["associations"].append({"contact": contact_ref, "company": {"id": co["id"]}})
            elif mc.get("account_name") or domain:
                ckey = f"monaco-account:{mc.get('account_id') or norm_name(mc.get('account_name'))}"
                if ckey not in planned_companies:
                    props = {k: v for k, v in {
                        "name": mc.get("account_name") or (acct or {}).get("name"), "domain": domain,
                        "hubspot_owner_id": owner["hubspot_owner_id"], "lifecyclestage": "lead",
                        "linkedin_company_page": "https://www." + (acct.get("company") or {}).get("linkedin_url")
                        if acct and (acct.get("company") or {}).get("linkedin_url") else None,
                    }.items() if not blank(v)}
                    planned_companies[ckey] = props
                    plan["hubspot"]["company_creates"].append({"key": ckey, "properties": props})
                plan["hubspot"]["associations"].append({"contact": contact_ref, "company": {"key": ckey}})

        for conv in convs:
            body, last = note_body(mc, conv, owner)
            existing = notes_by_chat.get(conv["chat_id"])
            if existing and existing["last"] and existing["last"] >= last:
                continue
            plan["hubspot"]["notes"].append({
                "contact": contact_ref, "note_id": existing["id"] if existing else None,
                "chat_id": conv["chat_id"], "timestamp": last, "owner_id": owner["hubspot_owner_id"], "body": body,
            })


# ---------------------------------------------------------------- main

def build_plan(snap: dict, cfg: dict) -> dict:
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "monaco": {"contact_creates": [], "contact_updates": [], "contact_notes": [], "contact_tags": [],
                   "account_upserts": []},
        "hubspot": {"contact_creates": [], "contact_updates": [], "company_creates": [], "associations": [],
                    "notes": []},
        "skipped": [], "conflicts": [],
    }
    plan_hubspot_to_monaco(snap, cfg, plan)
    plan_companies_to_monaco(snap, cfg, plan)
    plan_monaco_to_hubspot(snap, cfg, plan)
    plan["stats"] = {f"{side}.{k}": len(v) for side in ("monaco", "hubspot") for k, v in plan[side].items()}
    plan["stats"].update({"skipped": len(plan["skipped"]), "conflicts": len(plan["conflicts"])})
    return plan


def load_snapshot(work: Path) -> dict:
    return {
        "hubspot_contacts": load(work, "hubspot_contacts.json", []),
        "hubspot_lookup_contacts": load(work, "hubspot_lookup_contacts.json", []),
        "hubspot_companies": load(work, "hubspot_companies.json", []),
        "hubspot_lookup_companies": load(work, "hubspot_lookup_companies.json", []),
        "hubspot_notes": load(work, "hubspot_notes.json", []),
        "monaco_contacts": load(work, "monaco_contacts.json", []),
        "monaco_lookup_contacts": load(work, "monaco_lookup_contacts.json", []),
        "monaco_accounts": load(work, "monaco_accounts.json", []),
        "monaco_conversations": load(work, "monaco_conversations.json", {}),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("work_dir")
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    args = ap.parse_args()
    work = Path(args.work_dir)
    plan = build_plan(load_snapshot(work), json.loads(Path(args.config).read_text()))
    (work / "plan.json").write_text(json.dumps(plan, indent=2, ensure_ascii=False))
    print(json.dumps(plan["stats"], indent=2))


if __name__ == "__main__":
    main()
