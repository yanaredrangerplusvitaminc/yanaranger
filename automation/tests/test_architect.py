import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import architect  # noqa: E402

NOW = datetime(2026, 10, 26, 18, 0, tzinfo=timezone.utc)  # Mon 19:00 Madrid
SESSION = "session_shared"


def trig(id_, name, cron, enabled=True, session=None, connectors=True, last_fired="2026-10-26T15:00:00Z",
         status="ROUTINE_RUN_STATUS_SUCCEEDED", prompt="p"):
    t = {"id": id_, "name": name, "cron_expression": cron, "enabled": enabled,
         "created_at": "2026-10-20T10:00:00Z", "last_fired_at": last_fired,
         "mcp_connections": [{"name": "Slack"}] if connectors else [],
         "derived_state": {"prompt": prompt}, "last_run": {"status": status}}
    if session:
        t["persistent_session_id"] = session
    return t


def registry(*routines, superseded=()):
    return {"timezone": "Europe/Madrid", "min_gap_minutes_same_session": 30, "surfaces": {},
            "routines": list(routines), "superseded": list(superseded)}


def routine(key, tid, writes=(), status="live"):
    return {"key": key, "trigger_id": tid, "status": status, "writes": list(writes)}


def messages(result, severity=None):
    return [f"{who}: {msg}" for sev, who, msg in result["findings"] if severity in (None, sev)]


class CronTests(unittest.TestCase):
    def test_weekday_hours_in_madrid(self):
        fires = architect.fire_times("CRON_TZ=Europe/Madrid 47 7-20 * * 1-5", "UTC", NOW, days=7)
        self.assertEqual(len(fires), 14 * 5)
        self.assertEqual(fires[0], datetime(2026, 10, 26, 18, 47, tzinfo=timezone.utc))  # 19:47 CET

    def test_lists_and_weekend(self):
        fires = architect.fire_times("CRON_TZ=Europe/Madrid 37 8,12,16,20 * * *", "UTC", NOW, days=7)
        self.assertEqual(len(fires), 4 * 7)

    def test_step(self):
        self.assertEqual(architect._field("*/15", 0, 59), {0, 15, 30, 45})
        self.assertEqual(architect._field("0", 0, 7), {0})
        self.assertEqual({d % 7 for d in architect._field("7", 0, 7)}, {0})


class AuditTests(unittest.TestCase):
    def run_audit(self, reg, triggers, prompts=None):
        with tempfile.TemporaryDirectory() as d:
            for key, text in (prompts or {}).items():
                Path(d, f"{key}.md").write_text(text)
            return architect.audit(reg, triggers, NOW, Path(d))

    def test_shared_session_collision_is_red(self):
        reg = registry(routine("health", "t1"), routine("digest", "t2"))
        triggers = [trig("t1", "Health", "CRON_TZ=Europe/Madrid 7 8,14 * * 1-5", session=SESSION),
                    trig("t2", "Digest", "CRON_TZ=Europe/Madrid 21 8 * * 1-5", session=SESSION)]
        res = self.run_audit(reg, triggers)
        red = messages(res, "RED")
        self.assertTrue(any("\"Digest\" fires 14 min after \"Health\"" in m for m in red), red)
        self.assertTrue(any("2 routines share one conversation" in m for m in messages(res, "AMBER")))

    def test_same_routine_hourly_is_not_a_collision(self):
        reg = registry(routine("reconcile", "t1"))
        res = self.run_audit(reg, [trig("t1", "Reconcile", "CRON_TZ=Europe/Madrid 47 7-20 * * 1-5", session=SESSION)])
        self.assertEqual(messages(res, "RED"), [])
        self.assertTrue(any("14 runs on its busiest day" in m for m in messages(res, "AMBER")))

    def test_superseded_still_on_is_red(self):
        reg = registry(routine("new", "t1"), superseded=[{"trigger_id": "t0", "name": "Old", "replaced_by": "new"}])
        res = self.run_audit(reg, [trig("t1", "New", "0 9 * * *"), trig("t0", "Old", "0 9 * * *")])
        self.assertTrue(any("superseded by new but still on" in m for m in messages(res, "RED")))

    def test_superseded_off_unlabelled_is_info(self):
        reg = registry(superseded=[{"trigger_id": "t0", "name": "Old", "replaced_by": "new"}])
        res = self.run_audit(reg, [trig("t0", "Old", "0 9 * * *", enabled=False)])
        self.assertTrue(any("not labelled" in m for m in messages(res, "INFO")))
        res = self.run_audit(reg, [trig("t0", "[superseded] Old", "0 9 * * *", enabled=False)])
        self.assertFalse(any("not labelled" in m for m in messages(res)))

    def test_unregistered_and_missing(self):
        reg = registry(routine("gone", "t9"))
        res = self.run_audit(reg, [trig("t1", "Stray", "0 9 * * *")])
        self.assertTrue(any("not found" in m for m in messages(res, "RED")))
        self.assertTrue(any("Stray: on but not in the registry" in m for m in messages(res, "AMBER")))

    def test_two_live_writers_on_one_surface(self):
        reg = registry(routine("a", "t1", ["board:x"]), routine("b", "t2", ["board:x"]),
                       routine("c", None, ["board:x"], status="unscheduled"))
        res = self.run_audit(reg, [trig("t1", "A", "0 9 * * *"), trig("t2", "B", "0 10 * * *")])
        self.assertTrue(any("board:x: written by a, b" in m for m in messages(res, "RED")))

    def test_drift_and_baseline(self):
        reg = registry(routine("a", "t1"))
        triggers = [trig("t1", "A", "0 9 * * *", prompt="Run the thing v2")]
        self.assertTrue(any("no baseline" in m for m in messages(self.run_audit(reg, triggers))))
        same = self.run_audit(reg, triggers, {"a": "Run the thing v2\n"})
        self.assertFalse(any("differs" in m for m in messages(same)))
        drift = self.run_audit(reg, triggers, {"a": "Run the thing v1"})
        self.assertTrue(any("live prompt differs" in m for m in messages(drift, "AMBER")))

    def test_failed_stale_and_no_connectors(self):
        reg = registry(routine("a", "t1"))
        t = trig("t1", "A", "0 9 * * *", connectors=False, last_fired="2026-10-20T08:00:00Z",
                 status="ROUTINE_RUN_STATUS_FAILED")
        found = messages(self.run_audit(reg, [t]))
        self.assertTrue(any("last run failed" in m for m in found))
        self.assertTrue(any("should have fired" in m for m in found))
        self.assertTrue(any("no connectors" in m for m in found))

    def test_timezone_mismatch_is_info(self):
        reg = registry(routine("a", "t1"))
        res = self.run_audit(reg, [trig("t1", "A", "CRON_TZ=Europe/Paris 35 8 * * 1-5")])
        self.assertTrue(any("Europe/Paris" in m for m in messages(res, "INFO")))

    def test_render_and_snapshot_pages(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, "snap.json")
            p.write_text(json.dumps([{"data": [trig("t1", "A", "0 9 * * *")]}, {"data": []}]))
            self.assertEqual(len(architect.load_snapshot(p)), 1)
        out = architect.render(self.run_audit(registry(routine("a", "t1")), [trig("t1", "A", "0 9 * * *")]), NOW)
        self.assertIn("Madrid (22:00 Gulf)", out)

    def test_slack_draft_prompt_is_red(self):
        reg = registry(routine("d", "t1"))
        reg["forbidden_prompt_patterns"] = json.loads(architect.REGISTRY.read_text())["forbidden_prompt_patterns"]
        v2 = trig("t1", "Digest", "0 9 * * *", prompt="a. Create a Slack draft in Yana's own DM (channel_id U0C4NPHS58R)")
        self.assertTrue(any("house rule" in m for m in messages(self.run_audit(reg, [v2]), "RED")))
        v3 = trig("t1", "Digest", "0 9 * * *", prompt="Never create Slack drafts or Slack messages of any kind.")
        self.assertFalse(any("house rule" in m for m in messages(self.run_audit(reg, [v3]))))

    def test_repo_registry_is_valid(self):
        reg = json.loads(architect.REGISTRY.read_text())
        keys = [r["key"] for r in reg["routines"]]
        self.assertEqual(len(keys), len(set(keys)))
        for r in reg["routines"]:
            for s in r["writes"]:
                self.assertIn(s, reg["surfaces"], f"{r['key']} writes undescribed surface {s}")


if __name__ == "__main__":
    unittest.main()
