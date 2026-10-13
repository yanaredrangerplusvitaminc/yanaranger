import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import planner  # noqa: E402

CFG = json.loads((Path(__file__).resolve().parents[1] / "config.json").read_text())
YANA_HS, SARI_HS = "168888360", "96079443"
YANA_MO = "01a0f86a-3f6f-733e-881a-2e503f78fbf1"


def snap(**kw):
    base = {k: [] for k in ("hubspot_contacts", "hubspot_lookup_contacts", "hubspot_companies",
                            "hubspot_lookup_companies", "hubspot_notes", "monaco_contacts",
                            "monaco_lookup_contacts", "monaco_accounts")}
    base["monaco_conversations"] = {}
    base.update(kw)
    return base


def hs_contact(id_, **props):
    return {"id": id_, "properties": {"hubspot_owner_id": YANA_HS, **props}}


def mo_contact(id_, **fields):
    return {"id": id_, "tags": [], "notes": None, "_connected_to": ["Yana Rova"], **fields}


CONV = {"chat_id": "chat1", "messages": [
    {"timestamp": "2026-10-12T15:47:00Z", "direction": "outbound", "text": "Hi Mohammad, attending ADIPEC?"},
    {"timestamp": "2026-10-12T15:50:00Z", "direction": "inbound", "text": "Yes, visit our booth"},
]}


class Normalise(unittest.TestCase):
    def test_linkedin_variants_match(self):
        a = planner.norm_linkedin("linkedin.com/in/mohammad-oweis-pmp-b0945043")
        b = planner.norm_linkedin("https://www.linkedin.com/in/Mohammad-Oweis-PMP-b0945043/?trk=x")
        self.assertEqual(a, b)
        self.assertEqual(a, "linkedin.com/in/mohammad-oweis-pmp-b0945043")

    def test_non_profile_urls_ignored(self):
        self.assertIsNone(planner.norm_linkedin("https://www.linkedin.com/company/81658842/"))
        self.assertIsNone(planner.norm_linkedin("https://example.com/in/x"))

    def test_domain(self):
        self.assertEqual(planner.norm_domain("https://www.AEGps.com/about"), "aegps.com")


class NotesBlock(unittest.TestCase):
    def test_replaces_only_managed_block(self):
        hc = hs_contact("1", lifecyclestage="lead", hs_lead_status="IN_PROGRESS")
        block = planner.notes_block(hc, "Enerflex", CFG)
        original = "Yana's conversation log\n\n[HubSpot sync]\nold\n[/HubSpot sync]\n\nTrailing note"
        merged = planner.merge_notes(original, block)
        self.assertTrue(merged.startswith("Yana's conversation log"))
        self.assertTrue(merged.endswith("Trailing note"))
        self.assertIn("Lead status: In Progress", merged)
        self.assertNotIn("old", merged)
        self.assertEqual(planner.merge_notes(merged, block), merged)

    def test_appends_when_missing(self):
        merged = planner.merge_notes("Existing", "[HubSpot sync]\nx\n[/HubSpot sync]")
        self.assertEqual(merged, "Existing\n\n[HubSpot sync]\nx\n[/HubSpot sync]")


class HubSpotToMonaco(unittest.TestCase):
    def test_match_by_linkedin_fills_blanks_never_overwrites(self):
        hc = hs_contact("566", firstname="Mohammad", email="m.oweis@enerflex.com", jobtitle="Other title",
                        hs_linkedin_url="https://www.linkedin.com/in/mohammad-oweis-pmp-b0945043/",
                        hs_lead_status="IN_PROGRESS", lifecyclestage="lead")
        mc = mo_contact("m1", email=None, title="Projects Development Manager", account_id="a1",
                        linkedin_url="linkedin.com/in/mohammad-oweis-pmp-b0945043", notes="Log")
        plan = planner.build_plan(snap(hubspot_contacts=[hc], monaco_contacts=[mc]), CFG)
        upd = plan["monaco"]["contact_updates"][0]["payload"]
        self.assertEqual(upd["email"], "m.oweis@enerflex.com")
        self.assertNotIn("title", upd)
        self.assertEqual(upd["linkedin_url"], mc["linkedin_url"])
        self.assertTrue(plan["monaco"]["contact_notes"][0]["notes"].startswith("Log"))
        self.assertEqual(plan["monaco"]["contact_tags"][0]["add"], "HS In Progress")
        self.assertEqual(plan["monaco"]["contact_creates"], [])

    def test_status_change_swaps_tag(self):
        hc = hs_contact("1", email="a@x.com", hs_lead_status="CONNECTED")
        mc = mo_contact("m1", email="a@x.com", tags=[{"name": "HS In Progress"}, {"name": "Ranger"}])
        tags = planner.build_plan(snap(hubspot_contacts=[hc], monaco_contacts=[mc]), CFG)["monaco"]["contact_tags"][0]
        self.assertEqual(tags, {"monaco_id": "m1", "add": "HS Connected", "remove": ["HS In Progress"]})

    def test_unowned_hubspot_contacts_ignored(self):
        hc = hs_contact("1", email="a@x.com", hubspot_owner_id="999")
        plan = planner.build_plan(snap(hubspot_contacts=[hc]), CFG)
        self.assertEqual(plan["monaco"]["contact_creates"], [])

    def test_create_missing_in_monaco(self):
        hc = hs_contact("1", email="a@x.com", firstname="A", hs_lead_status="NEW")
        create = planner.build_plan(snap(hubspot_contacts=[hc]), CFG)["monaco"]["contact_creates"][0]
        self.assertEqual(create["payload"]["email"], "a@x.com")
        self.assertIn("[HubSpot sync]", create["payload"]["notes"])
        self.assertEqual(create["tag"], "HS New")

    def test_linkedin_only_without_domain_skipped(self):
        hc = hs_contact("1", hs_linkedin_url="https://www.linkedin.com/in/someone/")
        plan = planner.build_plan(snap(hubspot_contacts=[hc]), CFG)
        self.assertEqual(plan["monaco"]["contact_creates"], [])
        self.assertEqual(plan["skipped"][0]["reason"], "LinkedIn only, company not found in Monaco")

    def test_linkedin_only_resolved_by_monaco_account_name(self):
        hc = hs_contact("1", hs_linkedin_url="https://www.linkedin.com/in/someone/", company="Enerflex Ltd.")
        acct = {"id": "a1", "name": "Enerflex Ltd", "domains": []}
        create = planner.build_plan(snap(hubspot_contacts=[hc], monaco_accounts=[acct]), CFG)["monaco"]["contact_creates"][0]
        self.assertEqual(create["payload"]["account_id"], "a1")

    def test_no_changes_is_empty_plan(self):
        hc = hs_contact("1", email="a@x.com", hs_lead_status="NEW")
        block = planner.notes_block(hc, None, CFG)
        mc = mo_contact("m1", email="a@x.com", notes=block, tags=[{"name": "HS New"}])
        plan = planner.build_plan(snap(hubspot_contacts=[hc], monaco_contacts=[mc]), CFG)
        self.assertEqual(sum(v for k, v in plan["stats"].items() if k.startswith("monaco.")), 0)


class Companies(unittest.TestCase):
    def test_status_from_lifecycle_and_owner_fill(self):
        co = {"id": "c1", "properties": {"name": "AEG Power Solutions", "domain": "aegps.com",
                                         "lifecyclestage": "opportunity", "hubspot_owner_id": YANA_HS}}
        acct = {"id": "a1", "name": "AEG Power Solutions", "status": "Prospecting", "owner": None, "domains": ["aegps.com"]}
        up = planner.build_plan(snap(hubspot_companies=[co], monaco_accounts=[acct]), CFG)["monaco"]["account_upserts"][0]
        self.assertEqual(up["payload"], {"id": "a1", "status": "OPPORTUNITY", "owner": YANA_MO})

    def test_never_downgrades_monaco_status(self):
        co = {"id": "c1", "properties": {"domain": "firedos.com", "lifecyclestage": "lead", "hubspot_owner_id": YANA_HS}}
        for current in ("Opportunity", "Nurture"):
            acct = {"id": "a1", "status": current, "owner": {"id": YANA_MO}, "domains": ["firedos.com"]}
            plan = planner.build_plan(snap(hubspot_companies=[co], monaco_accounts=[acct]), CFG)
            self.assertEqual(plan["monaco"]["account_upserts"], [])
            self.assertEqual(plan["conflicts"][0]["type"], "account_status_ahead_in_monaco")

    def test_same_status_case_insensitive_is_noop(self):
        co = {"id": "c1", "properties": {"domain": "aegps.com", "lifecyclestage": "opportunity", "hubspot_owner_id": YANA_HS}}
        acct = {"id": "a1", "status": "Opportunity", "owner": {"id": YANA_MO}, "domains": ["aegps.com"]}
        plan = planner.build_plan(snap(hubspot_companies=[co], monaco_accounts=[acct]), CFG)
        self.assertEqual(plan["monaco"]["account_upserts"], [])


class MonacoToHubSpot(unittest.TestCase):
    def test_conversation_creates_contact_company_and_note(self):
        mc = mo_contact("m1", first_name="Mohammad", last_name="Oweis", account_id="a1", account_name="Enerflex Ltd.",
                        linkedin_url="linkedin.com/in/mohammad-oweis-pmp-b0945043")
        acct = {"id": "a1", "domains": ["enerflex.com"], "company": {"linkedin_url": "linkedin.com/company/enerflex"}}
        plan = planner.build_plan(snap(monaco_contacts=[mc], monaco_accounts=[acct],
                                       monaco_conversations={"m1": [CONV]}), CFG)
        hs = plan["hubspot"]
        self.assertEqual(hs["contact_creates"][0]["properties"]["hs_lead_status"], "CONNECTED")
        self.assertEqual(hs["contact_creates"][0]["properties"]["hubspot_owner_id"], YANA_HS)
        self.assertEqual(hs["company_creates"][0]["properties"]["domain"], "enerflex.com")
        self.assertEqual(hs["associations"][0]["company"], {"key": "monaco-account:a1"})
        note = hs["notes"][0]
        self.assertIsNone(note["note_id"])
        self.assertIn("monaco-chat: chat1", note["body"])
        self.assertIn("12 Oct 2026 17:47 - Yana", note["body"])

    def test_existing_note_updated_only_when_new_messages(self):
        mc = mo_contact("m1", email="m@enerflex.com")
        hc = hs_contact("566", email="m@enerflex.com", hs_lead_status="IN_PROGRESS")
        fresh = {"id": "n1", "body": "x monaco-chat: chat1 | last: 2026-10-12T15:50:00Z"}
        stale = {"id": "n1", "body": "x monaco-chat: chat1 | last: 2026-10-12T15:47:00Z"}
        base = dict(monaco_contacts=[mc], hubspot_lookup_contacts=[hc], monaco_conversations={"m1": [CONV]})
        self.assertEqual(planner.build_plan(snap(hubspot_notes=[fresh], **base), CFG)["hubspot"]["notes"], [])
        notes = planner.build_plan(snap(hubspot_notes=[stale], **base), CFG)["hubspot"]["notes"]
        self.assertEqual(notes[0]["note_id"], "n1")

    def test_lead_status_promoted_only_from_new_or_empty(self):
        mc = mo_contact("m1", email="m@x.com", last_outbound_type="LinkedIn Message")
        empty = hs_contact("1", email="m@x.com")
        set_ = hs_contact("1", email="m@x.com", hs_lead_status="OPEN_DEAL")
        upd = planner.build_plan(snap(monaco_contacts=[mc], hubspot_lookup_contacts=[empty]), CFG)["hubspot"]["contact_updates"]
        self.assertEqual(upd[0]["properties"]["hs_lead_status"], "ATTEMPTED_TO_CONTACT")
        upd = planner.build_plan(snap(monaco_contacts=[mc], hubspot_lookup_contacts=[set_]), CFG)["hubspot"]["contact_updates"]
        self.assertEqual(upd, [])

    def test_connections_without_conversation_not_pushed(self):
        mc = mo_contact("m1", email="m@x.com")
        plan = planner.build_plan(snap(monaco_contacts=[mc]), CFG)
        self.assertEqual(plan["hubspot"]["contact_creates"], [])


if __name__ == "__main__":
    unittest.main()
