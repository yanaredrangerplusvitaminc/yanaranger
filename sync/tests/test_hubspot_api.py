import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hubspot_api  # noqa: E402


class FakeHubSpot:
    """Records calls and answers like the HubSpot API for the handful of endpoints the sync uses."""

    def __init__(self, existing_contacts=(), existing_companies=()):
        self.calls = []
        self.contacts = list(existing_contacts)
        self.companies = list(existing_companies)
        self.next_id = 1000

    def __call__(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path.endswith("/search"):
            pool = self.contacts if "/contacts/" in path else self.companies
            hits = []
            for g in body["filterGroups"]:
                f = g["filters"][0]
                for r in pool:
                    v = (r["properties"].get(f["propertyName"]) or "").lower()
                    if (f["operator"] == "EQ" and v == f["value"].lower()) or \
                            (f["operator"] == "CONTAINS_TOKEN" and f["value"].lower() in v):
                        hits.append(r)
            return {"results": hits}
        if method == "POST" and path in ("/crm/v3/objects/contacts", "/crm/v3/objects/companies", "/crm/v3/objects/notes"):
            self.next_id += 1
            return {"id": str(self.next_id), "properties": body["properties"]}
        return {}


def run_apply(fake, hubspot_plan):
    work = Path(tempfile.mkdtemp())
    empty = {"company_creates": [], "contact_creates": [], "contact_updates": [], "associations": [], "notes": []}
    (work / "plan.json").write_text(json.dumps({"hubspot": {**empty, **hubspot_plan}}))
    hubspot_api.cmd_apply(hubspot_api.HubSpot("t", request=fake), work)
    return json.loads((work / "hubspot_results.json").read_text())


class Apply(unittest.TestCase):
    def test_creates_company_then_contact_then_links_and_notes(self):
        fake = FakeHubSpot()
        res = run_apply(fake, {
            "company_creates": [{"key": "co1", "properties": {"name": "Enerflex", "domain": "enerflex.com"}}],
            "contact_creates": [{"key": "p1", "properties": {"email": "m@enerflex.com", "firstname": "Mo"}}],
            "associations": [{"contact": {"key": "p1"}, "company": {"key": "co1"}}],
            "notes": [{"contact": {"key": "p1"}, "note_id": None, "chat_id": "c1", "timestamp": "2026-10-12T15:50:00Z",
                       "owner_id": "168888360", "body": "x monaco-chat: c1"}],
        })
        self.assertEqual(len(res["created"]), 2)
        self.assertEqual(res["associated"], 1)
        self.assertEqual(res["notes"], 1)
        put = [c for c in fake.calls if c[0] == "PUT"][0]
        self.assertEqual(put[1], f"/crm/v4/objects/contact/{res['ids']['p1']}/associations/default/company/{res['ids']['co1']}")
        note = [c for c in fake.calls if c[1] == "/crm/v3/objects/notes"][0][2]
        self.assertEqual(note["associations"][0]["types"][0]["associationTypeId"], 202)

    def test_reuses_contact_created_since_fetch_instead_of_duplicating(self):
        fake = FakeHubSpot(existing_contacts=[{"id": "77", "properties": {
            "hs_linkedin_url": "https://www.linkedin.com/in/mohammad-oweis/"}}])
        res = run_apply(fake, {"contact_creates": [{"key": "p1", "properties": {
            "hs_linkedin_url": "https://www.linkedin.com/in/mohammad-oweis/"}}]})
        self.assertEqual(res["created"], [])
        self.assertEqual(res["ids"]["p1"], "77")
        self.assertFalse(any(c[1] == "/crm/v3/objects/contacts" for c in fake.calls))

    def test_fuzzy_linkedin_hit_is_not_treated_as_match(self):
        fake = FakeHubSpot(existing_contacts=[{"id": "77", "properties": {
            "hs_linkedin_url": "https://www.linkedin.com/in/mohammad-oweis-2/"}}])
        res = run_apply(fake, {"contact_creates": [{"key": "p1", "properties": {
            "hs_linkedin_url": "https://www.linkedin.com/in/mohammad-oweis/"}}]})
        self.assertEqual(len(res["created"]), 1)

    def test_reuses_company_by_domain(self):
        fake = FakeHubSpot(existing_companies=[{"id": "5", "properties": {"domain": "enerflex.com", "name": "Enerflex Ltd."}}])
        res = run_apply(fake, {"company_creates": [{"key": "co1", "properties": {"name": "Enerflex", "domain": "enerflex.com"}}]})
        self.assertEqual(res["ids"]["co1"], "5")
        self.assertEqual(res["created"], [])

    def test_failure_is_logged_and_run_continues(self):
        fake = FakeHubSpot()
        original = fake.__call__

        def flaky(method, path, body=None):
            if path == "/crm/v3/objects/companies":
                raise RuntimeError("boom")
            return original(method, path, body)
        res = run_apply(flaky, {
            "company_creates": [{"key": "co1", "properties": {"name": "X"}}],
            "contact_creates": [{"key": "p1", "properties": {"email": "a@b.com"}}],
        })
        self.assertEqual(len(res["failed"]), 1)
        self.assertEqual(len(res["created"]), 1)


if __name__ == "__main__":
    unittest.main()
