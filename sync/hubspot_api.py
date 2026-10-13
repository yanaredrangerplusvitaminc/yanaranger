"""HubSpot side of the sync over the HubSpot API (token in env HUBSPOT_TOKEN).

Commands, all working in the same work directory the planner uses:

  fetch  WORK [--since ISO]   owned contacts and companies -> hubspot_contacts.json, hubspot_companies.json
  lookup WORK                 for monaco_contacts.json: find people/companies anywhere in HubSpot and their
                              Monaco-sync notes -> hubspot_lookup_contacts.json, hubspot_lookup_companies.json,
                              hubspot_notes.json
  apply  WORK                 execute plan.json's "hubspot" section -> hubspot_results.json

Never deletes. Every create is preceded by a fresh search, so a record added since the fetch is reused.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from planner import mo_email, mo_li, norm_domain, norm_linkedin, norm_name  # noqa: E402

BASE = "https://api.hubapi.com"
CONTACT_PROPS = ["firstname", "lastname", "email", "phone", "jobtitle", "company", "hs_linkedin_url",
                 "lifecyclestage", "hs_lead_status", "hubspot_owner_id", "associatedcompanyid"]
COMPANY_PROPS = ["name", "domain", "lifecyclestage", "hubspot_owner_id", "linkedin_company_page"]
NOTE_TO_CONTACT = 202  # HubSpot-defined association type: note -> contact


class HubSpot:
    def __init__(self, token: str, request=None):
        self.token = token
        self._request = request or self._http

    def _http(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(BASE + path, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}

    def call(self, method, path, body=None):
        for attempt in range(5):
            try:
                return self._request(method, path, body)
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 504) and attempt < 4:
                    time.sleep(2 ** attempt)
                    continue
                detail = e.read().decode(errors="replace") if hasattr(e, "read") else ""
                raise RuntimeError(f"HubSpot {method} {path} -> {e.code}: {detail[:300]}") from None

    # ---------------------------------------------------------------- reads

    def search(self, obj, filter_groups, properties):
        out, after = [], None
        while True:
            body = {"filterGroups": filter_groups, "properties": properties, "limit": 100}
            if after:
                body["after"] = after
            page = self.call("POST", f"/crm/v3/objects/{obj}/search", body)
            out += page.get("results", [])
            after = (page.get("paging") or {}).get("next", {}).get("after")
            if not after:
                return out

    def batch_read(self, obj, ids, properties, id_property=None):
        out = []
        for i in range(0, len(ids), 100):
            body = {"properties": properties, "inputs": [{"id": str(x)} for x in ids[i:i + 100]]}
            if id_property:
                body["idProperty"] = id_property
            out += self.call("POST", f"/crm/v3/objects/{obj}/batch/read", body).get("results", [])
        return out

    def find_contact(self, email, linkedin):
        groups = []
        if email:
            groups.append({"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]})
        if linkedin:
            slug = linkedin.rsplit("/", 1)[-1]
            groups.append({"filters": [{"propertyName": "hs_linkedin_url", "operator": "CONTAINS_TOKEN", "value": slug}]})
        if not groups:
            return None
        hits = self.call("POST", "/crm/v3/objects/contacts/search",
                         {"filterGroups": groups, "properties": CONTACT_PROPS, "limit": 10}).get("results", [])
        for h in hits:  # CONTAINS_TOKEN is fuzzy: confirm the exact match
            p = h["properties"]
            if (email and (p.get("email") or "").lower() == email) or \
                    (linkedin and norm_linkedin(p.get("hs_linkedin_url")) == linkedin):
                return h
        return None

    def find_company(self, domain, name):
        for prop, value in (("domain", domain), ("name", name)):
            if not value:
                continue
            hits = self.call("POST", "/crm/v3/objects/companies/search", {
                "filterGroups": [{"filters": [{"propertyName": prop, "operator": "EQ", "value": value}]}],
                "properties": COMPANY_PROPS, "limit": 5}).get("results", [])
            if hits:
                return hits[0]
        return None


def as_record(obj, with_company=False):
    rec = {"id": str(obj["id"]), "properties": obj.get("properties", {})}
    if with_company:
        rec["company_id"] = rec["properties"].get("associatedcompanyid")
    return rec


# ---------------------------------------------------------------- commands

def cmd_fetch(hs: HubSpot, work: Path, cfg: dict, since: str | None):
    owners = [o["hubspot_owner_id"] for o in cfg["owners"]]

    def groups(modified_prop):
        f = [{"propertyName": "hubspot_owner_id", "operator": "IN", "values": owners}]
        if since:
            f.append({"propertyName": modified_prop, "operator": "GTE", "value": since})
        return [{"filters": f}]

    contacts = [as_record(c, True) for c in hs.search("contacts", groups("lastmodifieddate"), CONTACT_PROPS)]
    companies = {str(c["id"]): as_record(c) for c in hs.search("companies", groups("hs_lastmodifieddate"), COMPANY_PROPS)}
    missing = sorted({c["company_id"] for c in contacts if c["company_id"]} - set(companies))
    for c in hs.batch_read("companies", missing, COMPANY_PROPS):
        companies[str(c["id"])] = as_record(c)
    (work / "hubspot_contacts.json").write_text(json.dumps(contacts))
    (work / "hubspot_companies.json").write_text(json.dumps(list(companies.values())))
    print(json.dumps({"hubspot_contacts": len(contacts), "hubspot_companies": len(companies)}))


def cmd_lookup(hs: HubSpot, work: Path):
    load = lambda n, d: json.loads((work / n).read_text()) if (work / n).exists() else d  # noqa: E731
    known = {c["id"]: c for c in load("hubspot_contacts.json", [])}
    known_emails = {(c["properties"].get("email") or "").lower() for c in known.values()}
    known_li = {norm_linkedin(c["properties"].get("hs_linkedin_url")) for c in known.values()}
    found = {}
    for mc in load("monaco_contacts.json", []):
        email, li = mo_email(mc), mo_li(mc)
        if (email and email in known_emails) or (li and li in known_li):
            continue
        hit = hs.find_contact(email, li)
        if hit:
            found[str(hit["id"])] = as_record(hit, True)

    accounts = {a["id"]: a for a in load("monaco_accounts.json", [])}
    companies, asked = {}, set()
    for mc in load("monaco_contacts.json", []):
        acct = accounts.get(mc.get("account_id")) or {}
        domain = next((norm_domain(d) for d in acct.get("domains") or [] if norm_domain(d)), None)
        key = domain or norm_name(mc.get("account_name"))
        if not key or key in asked:
            continue
        asked.add(key)
        hit = hs.find_company(domain, mc.get("account_name"))
        if hit:
            companies[str(hit["id"])] = as_record(hit)

    contact_ids = list(known) + list(found)
    notes = []
    for i in range(0, len(contact_ids), 100):
        assoc = hs.call("POST", "/crm/v4/associations/contacts/notes/batch/read",
                        {"inputs": [{"id": x} for x in contact_ids[i:i + 100]]}).get("results", [])
        pairs = [(str(r["from"]["id"]), str(t["toObjectId"])) for r in assoc for t in r.get("to", [])]
        bodies = {str(n["id"]): n["properties"].get("hs_note_body") or ""
                  for n in hs.batch_read("notes", [n for _, n in pairs], ["hs_note_body"])}
        notes += [{"id": n, "contact_id": c, "body": bodies.get(n, "")} for c, n in pairs
                  if "monaco-chat:" in bodies.get(n, "")]

    (work / "hubspot_lookup_contacts.json").write_text(json.dumps(list(found.values())))
    (work / "hubspot_lookup_companies.json").write_text(json.dumps(list(companies.values())))
    (work / "hubspot_notes.json").write_text(json.dumps(notes))
    print(json.dumps({"lookup_contacts": len(found), "lookup_companies": len(companies), "sync_notes": len(notes)}))


def cmd_apply(hs: HubSpot, work: Path):
    plan = json.loads((work / "plan.json").read_text())["hubspot"]
    ids, log = {}, {"created": [], "reused": [], "updated": 0, "associated": 0, "notes": 0, "failed": []}

    def attempt(label, fn):
        try:
            return fn()
        except Exception as e:  # one failure never stops the run
            log["failed"].append({"step": label, "error": str(e)})
            return None

    for c in plan["company_creates"]:
        p = c["properties"]
        existing = attempt(f"find company {p.get('name')}", lambda: hs.find_company(norm_domain(p.get("domain")), p.get("name")))
        if existing:
            ids[c["key"]] = str(existing["id"])
            log["reused"].append({"key": c["key"], "id": ids[c["key"]]})
            continue
        made = attempt(f"create company {p.get('name')}", lambda: hs.call("POST", "/crm/v3/objects/companies", {"properties": p}))
        if made:
            ids[c["key"]] = str(made["id"])
            log["created"].append({"key": c["key"], "id": ids[c["key"]], "type": "company"})

    for c in plan["contact_creates"]:
        p = c["properties"]
        existing = attempt(f"find contact {c['key']}", lambda: hs.find_contact(
            (p.get("email") or "").lower() or None, norm_linkedin(p.get("hs_linkedin_url"))))
        if existing:
            ids[c["key"]] = str(existing["id"])
            log["reused"].append({"key": c["key"], "id": ids[c["key"]]})
            continue
        made = attempt(f"create contact {c['key']}", lambda: hs.call("POST", "/crm/v3/objects/contacts", {"properties": p}))
        if made:
            ids[c["key"]] = str(made["id"])
            log["created"].append({"key": c["key"], "id": ids[c["key"]], "type": "contact"})

    updates = plan["contact_updates"]
    for i in range(0, len(updates), 100):
        chunk = updates[i:i + 100]
        if attempt("update contacts", lambda: hs.call("POST", "/crm/v3/objects/contacts/batch/update", {
                "inputs": [{"id": u["id"], "properties": u["properties"]} for u in chunk]})) is not None:
            log["updated"] += len(chunk)

    ref = lambda r: r.get("id") or ids.get(r.get("key"))  # noqa: E731
    for a in plan["associations"]:
        contact, company = ref(a["contact"]), ref(a["company"])
        if contact and company and attempt(f"associate {contact}->{company}", lambda: hs.call(
                "PUT", f"/crm/v4/objects/contact/{contact}/associations/default/company/{company}")) is not None:
            log["associated"] += 1

    for n in plan["notes"]:
        contact = ref(n["contact"])
        props = {"hs_note_body": n["body"], "hs_timestamp": n["timestamp"], "hubspot_owner_id": n["owner_id"]}
        if n.get("note_id"):
            done = attempt(f"update note {n['note_id']}", lambda: hs.call("PATCH", f"/crm/v3/objects/notes/{n['note_id']}",
                                                                           {"properties": props}))
        elif contact:
            done = attempt(f"create note {n['chat_id']}", lambda: hs.call("POST", "/crm/v3/objects/notes", {
                "properties": props, "associations": [{"to": {"id": contact}, "types": [
                    {"associationCategory": "HUBSPOT_DEFINED", "associationTypeId": NOTE_TO_CONTACT}]}]}))
        else:
            done = None
        if done is not None:
            log["notes"] += 1

    (work / "hubspot_results.json").write_text(json.dumps({"ids": ids, **log}, indent=2))
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in log.items()}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["fetch", "lookup", "apply"])
    ap.add_argument("work_dir")
    ap.add_argument("--since")
    ap.add_argument("--config", default=str(Path(__file__).with_name("config.json")))
    args = ap.parse_args()
    token = os.environ.get("HUBSPOT_TOKEN")
    if not token:
        sys.exit("HUBSPOT_TOKEN is not set")
    hs, work = HubSpot(token), Path(args.work_dir)
    if args.command == "fetch":
        cmd_fetch(hs, work, json.loads(Path(args.config).read_text()), args.since)
    elif args.command == "lookup":
        cmd_lookup(hs, work)
    else:
        cmd_apply(hs, work)


if __name__ == "__main__":
    main()
