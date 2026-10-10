import copy
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

from core import Settings, candidate_from_page
from daily_counter import NotionSession, apply_properties, ensure_schema, query_all, sync_counter
from migrate_counter import backfill_properties
from pipeline import _ready_row_needs_repair, query_ai_queue, run_outreach, update_ai_result
from qualification import (COMPLETED_STAGES, QUALIFIED_AT, RECEIPT, count_today,
                           fingerprint, new_receipt, receipt, receipt_properties,
                           reconcile, today_bounds, grandfathered_without_receipt)

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
SETTINGS = Settings("unused", "unused", "source", "unused", 100, False)


def text(value, type_="rich_text"):
    return {"type": type_, type_: [{"plain_text": value}] if value else []}


def prospect(id_="p1", handle=None, at=NOW, qualified=True, stage="Ready to Send"):
    handle = handle or id_
    page = {"id": id_, "created_time": "2026-10-05T10:00:00+00:00",
            "last_edited_time": NOW.isoformat(), "parent": {"data_source_id": "source"},
            "archived": False, "in_trash": False, "properties": {
                "Candidate": text("Fighter " + id_, "title"),
                "Verified Profile URL": {"type": "url", "url": f"https://www.instagram.com/{handle}/"},
                "Instagram Handle": text(handle), "Personalised DM Angle": text("Recent boxing training"),
                "Sport": {"type": "select", "select": {"name": "Boxing"}},
                "stage": {"type": "select", "id": "stage", "select": {"name": stage}},
                "Draft DM": text("Yo, saw your training."), "AI Qualification Reason": text("Eligible and sufficient"),
                "Outreach Approach": {"type": "select", "select": {"name": "A"}},
                "Priority Score": {"type": "number", "number": 45},
            }}
    if qualified:
        page = apply_properties(page, receipt_properties(new_receipt(page, at.isoformat() if at else None, legacy=at is None)))
    return page


def transition(page, name, now=NOW):
    page = copy.deepcopy(page)
    page["properties"]["stage"]["select"] = {"name": name}
    page["last_edited_time"] = now.isoformat()
    return apply_properties(page, reconcile(page, "stage", now))


class QualificationTests(unittest.TestCase):
    def test_live_worker_refuses_missing_or_invalid_cutover(self):
        with patch("pipeline.Settings.from_env", return_value=SETTINGS), patch.dict("os.environ", {"COUNTER_ONLY": "true", "OUTREACH_COUNTER_CUTOVER_AT": ""}):
            with self.assertRaisesRegex(RuntimeError, "OUTREACH_COUNTER_CUTOVER_AT"):
                run_outreach()
        with patch("pipeline.Settings.from_env", return_value=SETTINGS), patch.dict("os.environ", {"COUNTER_ONLY": "true", "OUTREACH_COUNTER_CUTOVER_AT": "not-a-date"}):
            with self.assertRaises(ValueError):
                run_outreach()

    def test_forward_cutover_preserves_legacy_ready_without_credit(self):
        old = prospect("legacy", qualified=False)
        fresh = prospect("new", qualified=False)
        fresh["created_time"] = "2026-10-08T12:01:00+00:00"
        with patch.dict("os.environ", {"OUTREACH_COUNTER_CUTOVER_AT": NOW.isoformat()}):
            self.assertTrue(grandfathered_without_receipt(old))
            self.assertFalse(grandfathered_without_receipt(fresh))
            self.assertEqual(reconcile(old, "stage", NOW), {})
            self.assertFalse(_ready_row_needs_repair(old, now=NOW))
            self.assertEqual(count_today([old], "stage", NOW), 0)
            self.assertEqual(reconcile(fresh, "stage", NOW)["stage"]["select"]["name"], "Needs Research")
            self.assertTrue(_ready_row_needs_repair(fresh, now=NOW))

    def test_explicit_new_ai_approval_of_old_page_counts_from_today(self):
        old = prospect("legacy", qualified=False)
        with patch.dict("os.environ", {"OUTREACH_COUNTER_CUTOVER_AT": NOW.isoformat()}):
            self.assertEqual(reconcile(old, "stage", NOW), {})
            approved = apply_properties(old, receipt_properties(new_receipt(old, NOW.isoformat())))
            self.assertFalse(grandfathered_without_receipt(approved))
            self.assertEqual(count_today([approved], "stage", NOW), 1)

    def test_legacy_cutover_requires_parseable_created_time(self):
        old = prospect("legacy", qualified=False)
        del old["created_time"]
        with patch.dict("os.environ", {"OUTREACH_COUNTER_CUTOVER_AT": NOW.isoformat()}):
            with self.assertRaises(ValueError):
                reconcile(old, "stage", NOW)

    def test_22_to_21_to_22_and_repeated_updates(self):
        pages = [prospect(f"p{i}") for i in range(22)]
        self.assertEqual(count_today(pages, "stage", NOW), 22)
        pages[0] = transition(pages[0], "Needs Research")
        self.assertIsNone(receipt(pages[0])["at"])
        self.assertEqual(count_today(pages, "stage", NOW), 21)
        pages[0] = transition(pages[0], "Ready to Send")
        self.assertEqual(count_today(pages, "stage", NOW), 21)
        self.assertEqual(pages[0]["properties"]["stage"]["select"]["name"], "Needs Research")
        pages[0] = apply_properties(pages[0], receipt_properties(new_receipt(pages[0], NOW.isoformat())))
        pages[0] = transition(pages[0], "Ready to Send")
        self.assertEqual(count_today(pages, "stage", NOW), 22)
        pages[0] = transition(pages[0], "Ready to Send")
        self.assertEqual(count_today(pages, "stage", NOW), 22)
        self.assertEqual(reconcile(pages[0], "stage", NOW), {})

    def test_follow_up_fields_preserve_approval_in_every_completed_stage(self):
        updates = {
            "Notes": text("Spoke to athlete; follow up next week"),
            "Location": text("Updated location"), "City": text("London"),
            "Gym": text("Updated gym"), "Source Detail": text("Updated referral notes"),
            "Source": {"type": "select", "select": {"name": "Athlete referral"}},
            "Experience": {"type": "select", "select": {"name": "Professional"}},
            "Date Contacted": {"type": "date", "date": {"start": "2026-10-08"}},
            "Follow-Up Count": {"type": "number", "number": 2},
        }
        for completed_stage in COMPLETED_STAGES:
            with self.subTest(stage=completed_stage):
                page = prospect(stage=completed_stage)
                before = receipt(page)
                page["properties"].update(copy.deepcopy(updates))
                self.assertEqual(reconcile(page, "stage", NOW), {})
                self.assertEqual(receipt(page), before)
                self.assertEqual(count_today([page], "stage", NOW), 1)
                self.assertFalse(_ready_row_needs_repair(page, now=NOW))

    def test_critical_evidence_edit_revokes_and_routes_ready_for_review(self):
        page = prospect()
        page["properties"]["Personalised DM Angle"] = text("Changed personalisation evidence")
        self.assertTrue(_ready_row_needs_repair(page, now=NOW))
        page = apply_properties(page, reconcile(page, "stage", NOW))
        self.assertEqual(page["properties"]["stage"]["select"]["name"], "Needs Research")
        self.assertFalse(receipt(page)["active"])
        self.assertIsNone(receipt(page)["at"])
        self.assertEqual(count_today([page], "stage", NOW), 0)

    def test_restoring_original_evidence_cannot_reactivate_revoked_approval(self):
        page = prospect()
        original = copy.deepcopy(page["properties"]["Personalised DM Angle"])
        page["properties"]["Personalised DM Angle"] = text("Changed research")
        page = apply_properties(page, reconcile(page, "stage", NOW))
        page["properties"]["Personalised DM Angle"] = original
        page = transition(page, "Ready to Send")
        self.assertFalse(receipt(page)["active"])
        self.assertIsNone(receipt(page)["at"])
        self.assertEqual(count_today([page], "stage", NOW), 0)

    def test_manual_stage_restore_cannot_reactivate_any_completed_stage(self):
        for completed_stage in COMPLETED_STAGES:
            with self.subTest(stage=completed_stage):
                page = transition(prospect(), "Needs Research")
                page = transition(page, completed_stage)
                self.assertFalse(receipt(page)["active"])
                self.assertIsNone(receipt(page)["at"])
                self.assertIsNone(page["properties"][QUALIFIED_AT]["date"])
                self.assertEqual(count_today([page], "stage", NOW), 0)
                self.assertEqual(reconcile(page, "stage", NOW), {})

    def test_receipt_v1_requires_review_instead_of_silent_scope_conversion(self):
        page = prospect()
        old = dict(receipt(page), version=1)
        page = apply_properties(page, receipt_properties(old))
        self.assertIsNone(receipt(page))
        page = apply_properties(page, reconcile(page, "stage", NOW))
        self.assertEqual(page["properties"]["stage"]["select"]["name"], "Needs Research")
        self.assertEqual(count_today([page], "stage", NOW), 0)

    def test_ready_fight_expiry_requires_review_but_sent_approval_survives(self):
        page = prospect(at=datetime(2026, 10, 7, 12, tzinfo=timezone.utc))
        page["properties"]["Personalised DM Angle"] = text("Upcoming fight on 7 October 2026")
        page["properties"]["Draft DM"] = text("Saw your fight on 7 October 2026 coming up")
        page = apply_properties(page, receipt_properties(new_receipt(page, "2026-10-07T12:00:00Z")))
        self.assertTrue(_ready_row_needs_repair(page, now=NOW))
        ready = apply_properties(page, reconcile(page, "stage", NOW))
        self.assertEqual(ready["properties"]["stage"]["select"]["name"], "Needs Research")
        contacted = transition(page, "Contacted")
        self.assertTrue(receipt(contacted)["active"])
        self.assertEqual(receipt(contacted)["at"], "2026-10-07T12:00:00.000+00:00")

    def test_monday_created_tuesday_qualified(self):
        tuesday = datetime(2026, 10, 6, 10, tzinfo=timezone.utc)
        page = prospect(at=tuesday)
        self.assertEqual(count_today([page], "stage", tuesday), 1)
        self.assertEqual(count_today([page], "stage", tuesday - timedelta(days=1)), 0)

    def test_progression_preserves_timestamp_once(self):
        page = prospect()
        at = receipt(page)["at"]
        for name in ("Contacted", "Replied", "Applied", "Accepted", "Reserve", "Activated"):
            page = transition(page, name)
            self.assertEqual(receipt(page)["at"], at)
            self.assertEqual(count_today([page], "stage", NOW), 1)

    def test_every_excluded_stage_revokes(self):
        for name in ("", "AI Queue", "Needs Research", "Rejected", "Inactive", "Invented"):
            with self.subTest(stage=name):
                page = transition(prospect(), name)
                self.assertEqual(count_today([page], "stage", NOW), 0)
                self.assertIsNone(page["properties"][QUALIFIED_AT]["date"])

    def test_duplicates_different_names_tracking_case_hosts(self):
        a, b = prospect("a", "Fighter"), prospect("b", "fighter")
        b["properties"]["Verified Profile URL"]["url"] = "https://m.instagram.com/fighter/?igsh=123&utm_source=x"
        self.assertEqual(count_today([a, b, a], "stage", NOW), 1)

    def test_historical_duplicate_does_not_earn_new_credit(self):
        a = prospect("a", "fighter", NOW - timedelta(days=1))
        b = prospect("b", "fighter")
        self.assertEqual(count_today([a, b], "stage", NOW), 0)
        a = transition(a, "Rejected")
        self.assertEqual(count_today([a, b], "stage", NOW), 1)

    def test_invalid_fields_and_missing_outputs_in_all_valid_stages(self):
        for name in COMPLETED_STAGES:
            for field, value in (("Candidate", text("", "title")),
                                 ("Personalised DM Angle", text("")),
                                 ("Verified Profile URL", {"type": "url", "url": "https://instagram.com/p/abc/"}),
                                 ("Instagram Handle", text("wrong")),
                                 ("Instagram Handle", text("")),
                                 ("Draft DM", text("")), ("AI Qualification Reason", text("")),
                                 ("Outreach Approach", {"type": "select", "select": None})):
                with self.subTest(stage=name, field=field):
                    page = prospect(stage=name)
                    page["properties"][field] = value
                    self.assertEqual(count_today([page], "stage", NOW), 0)
                    page = apply_properties(page, reconcile(page, "stage", NOW))
                    self.assertIsNone(receipt(page)["at"])

    def test_manual_advance_never_approved(self):
        for name in COMPLETED_STAGES:
            self.assertEqual(count_today([prospect(qualified=False, stage=name)], "stage", NOW), 0)

    def test_missing_malformed_or_copied_receipt(self):
        for proof in ("", "{broken", json.dumps({"eligible": True}),
                      json.dumps(dict(receipt(prospect()), page_id="other"))):
            page = prospect()
            page["properties"][RECEIPT] = text(proof)
            page = apply_properties(page, reconcile(page, "stage", NOW))
            self.assertEqual(count_today([page], "stage", NOW), 0)
            self.assertIsNone(page["properties"][QUALIFIED_AT]["date"])

    def test_new_research_requires_new_ai_not_manual_advance(self):
        page = transition(prospect(), "Needs Research")
        page["properties"]["Personalised DM Angle"] = text("Different training detail")
        page = transition(page, "Ready to Send")
        self.assertEqual(count_today([page], "stage", NOW), 0)

    def test_score_is_not_approval_threshold(self):
        page = prospect()
        page["properties"]["Priority Score"]["number"] = 0
        self.assertEqual(count_today([page], "stage", NOW), 1)

    def test_archived_and_trashed_excluded(self):
        for field in ("archived", "in_trash"):
            page = prospect()
            page[field] = True
            self.assertEqual(count_today([page], "stage", NOW), 0)

    def test_midnight_and_weekends(self):
        before = datetime(2026, 10, 9, 22, 59, 59, tzinfo=timezone.utc)
        page = prospect(at=before)
        self.assertEqual(count_today([page], "stage", before), 1)
        self.assertEqual(count_today([page], "stage", before + timedelta(seconds=1)), 0)
        saturday = before + timedelta(minutes=1)
        self.assertEqual(count_today([prospect(at=saturday)], "stage", saturday), 1)

    def test_dst_days_and_repeated_hour(self):
        for month, day, hours in ((3, 29, 23), (10, 25, 25)):
            now = datetime(2026, month, day, 12, tzinfo=timezone.utc)
            start, end = today_bounds(now)
            self.assertEqual((end-start).total_seconds(), hours * 3600)
            self.assertEqual(count_today([prospect(at=start)], "stage", now), 1)
            self.assertEqual(count_today([prospect(at=end)], "stage", now), 0)
        fall = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
        self.assertEqual(count_today([prospect("a", at=fall.replace(hour=0, minute=30)),
                                      prospect("b", at=fall.replace(hour=1, minute=30))], "stage", fall), 2)

    def test_receipt_recovers_date_after_partial_manual_edit(self):
        page = prospect()
        page["properties"][QUALIFIED_AT] = {"type": "date", "date": None}
        repaired = apply_properties(page, reconcile(page, "stage", NOW + timedelta(days=1)))
        self.assertEqual(receipt(repaired)["at"], NOW.isoformat(timespec="milliseconds"))
        self.assertEqual(count_today([repaired], "stage", NOW + timedelta(days=1)), 0)

    def test_notion_date_serialization_does_not_trigger_duplicate_patches(self):
        page = prospect(at=NOW.replace(microsecond=123456))
        self.assertEqual(receipt(page)["at"], "2026-10-08T12:00:00.123+00:00")
        page["properties"][QUALIFIED_AT]["date"]["start"] = "2026-10-08T12:00:00.123Z"
        self.assertEqual(reconcile(page, "stage", NOW + timedelta(seconds=1)), {})

    def test_migration_preserves_legacy_without_crediting_today(self):
        page = prospect(qualified=False)
        approval = {"fingerprint": fingerprint(page), "eligible": True, "evidence_sufficient": True,
                    "evidence_reference": "Reviewed original structured AI approval log", "qualified_at": None}
        page = apply_properties(page, backfill_properties(page, approval, NOW))
        self.assertTrue(receipt(page)["active"])
        self.assertTrue(receipt(page)["legacy"])
        self.assertEqual(reconcile(page, "stage", NOW), {})
        self.assertEqual(count_today([page], "stage", NOW), 0)
        page = transition(transition(page, "Needs Research"), "Ready to Send")
        self.assertEqual(count_today([page], "stage", NOW), 0)
        self.assertFalse(receipt(page)["active"])
        page = apply_properties(page, receipt_properties(new_receipt(page, NOW.isoformat())))
        page = transition(page, "Ready to Send")
        self.assertEqual(count_today([page], "stage", NOW), 1)

    def test_migration_rejects_heuristics_stale_data_today_and_naive_dates(self):
        page = prospect(qualified=False)
        good = {"fingerprint": fingerprint(page), "eligible": True, "evidence_sufficient": True,
                "evidence_reference": "Original AI response", "qualified_at": None}
        for edit in ({"eligible": False}, {"fingerprint": "stale"}, {"evidence_reference": ""},
                     {"qualified_at": NOW.isoformat()}, {"qualified_at": "2026-10-07"}):
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                backfill_properties(page, dict(good, **edit), NOW)
        historical = NOW - timedelta(days=1)
        migrated = apply_properties(page, backfill_properties(page, dict(good, qualified_at=historical.isoformat()), NOW))
        self.assertEqual(count_today([migrated], "stage", historical), 1)


class Response:
    def __init__(self, body=None, status=200, headers=None):
        self.body, self.status_code, self.headers = body or {}, status, headers or {}
        self.ok = status < 400
        self.text = "test response"

    def json(self):
        return copy.deepcopy(self.body)

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(f"status {self.status_code}")


class FakeNotion:
    def __init__(self, pages):
        self.pages = {p["id"]: copy.deepcopy(p) for p in pages}
        self.writes, self.queries = [], []
        self.counter = None
        self.fail_query = False
        self.fail_get = False
        self.fail_counter = False
        self.invalid_pagination = False
        self.schema = {QUALIFIED_AT: {"type": "date"}, RECEIPT: {"type": "rich_text"}}

    def get(self, url, **kwargs):
        if "/data_sources/" in url:
            return Response({"properties": self.schema})
        if self.fail_get:
            return Response(status=404)
        return Response(self.pages[url.rsplit("/", 1)[-1]])

    def post(self, url, json, **kwargs):
        self.queries.append(json)
        if self.fail_query:
            return Response(status=503)
        if self.invalid_pagination:
            return Response({"results": [], "has_more": True, "next_cursor": None})
        pages = [p for p in self.pages.values() if not p.get("archived") and not p.get("in_trash")]
        if "filter" in json:
            filter_ = json["filter"]
            if "last_edited_time" in filter_:
                since = filter_["last_edited_time"]["on_or_after"]
                pages = [p for p in pages if p["last_edited_time"] >= since]
            elif "and" in filter_:
                start = filter_["and"][0]["date"]["on_or_after"]
                end = filter_["and"][1]["date"]["before"]
                pages = [p for p in pages if (p["properties"].get(QUALIFIED_AT) or {}).get("date")
                         and start <= p["properties"][QUALIFIED_AT]["date"]["start"] < end]
            elif "or" in filter_:
                handles = {f["rich_text"]["equals"] for f in filter_["or"]}
                pages = [p for p in pages if candidate_from_page(p)["instagram_handle"] in handles]
        # Deliberately use tiny pages to exercise pagination.
        start = int(json.get("start_cursor", 0))
        end = start + 2
        return Response({"results": pages[start:end], "has_more": end < len(pages),
                         "next_cursor": str(end) if end < len(pages) else None})

    def patch(self, url, json, **kwargs):
        id_ = url.rsplit("/", 1)[-1]
        if id_ == "counter" and self.fail_counter:
            return Response(status=503)
        self.writes.append((id_, json))
        if id_ == "counter":
            self.counter = json["properties"]["Priority Score"]["number"]
        elif "/data_sources/" in url:
            self.schema.update({k: {"type": next(iter(v))} for k, v in json["properties"].items()})
        else:
            self.pages[id_] = apply_properties(self.pages[id_], json["properties"])
        return Response(self.pages.get(id_, {}))


class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "state.sqlite3")
        self.notion = FakeNotion([prospect(f"p{i}") for i in range(22)])

    def requalify(self, id_, now=NOW):
        page = self.notion.pages[id_]
        page["properties"]["stage"]["select"]["name"] = "AI Queue"
        result = {"eligible": True, "evidence_sufficient": True, "priority_score": 45,
                  "qualification_reason": "Eligible and sufficient", "outreach_approach": "A",
                  "draft_dm": "Yo, saw your training."}
        with patch("pipeline.datetime") as clock:
            clock.now.return_value = now
            update_ai_result(self.notion, SETTINGS, candidate_from_page(page), result, stage_property_id="stage")

    def sync(self, now=NOW, settings=SETTINGS):
        return sync_counter(self.notion, settings, "stage", "counter", now=now, state_path=self.path)

    def test_forward_cutover_keeps_legacy_in_notion_and_starts_at_zero(self):
        old = prospect("oldready", qualified=False)
        self.notion = FakeNotion([old])
        with patch.dict("os.environ", {"OUTREACH_COUNTER_CUTOVER_AT": NOW.isoformat()}):
            self.assertEqual(self.sync(), 0)
            self.assertEqual(self.notion.pages["oldready"]["properties"]["stage"]["select"]["name"], "Ready to Send")
            self.assertFalse(any(id_ == "oldready" for id_, _ in self.notion.writes))
            self.notion.pages["oldready"]["properties"]["stage"]["select"]["name"] = "AI Queue"
            self.requalify("oldready")
            self.assertEqual(self.sync(), 1)
            self.assertEqual(self.sync(), 1)

    def test_incremental_22_21_22_idempotent_and_paginated(self):
        self.assertEqual(self.sync(), 22)
        self.notion.pages["p0"] = transition(self.notion.pages["p0"], "Needs Research")
        self.assertEqual(self.sync(), 21)
        self.notion.pages["p0"] = transition(self.notion.pages["p0"], "Ready to Send")
        self.assertEqual(self.sync(), 21)
        self.requalify("p0")
        self.assertEqual(self.sync(), 22)
        self.assertEqual(self.sync(), 22)
        self.assertTrue(any("last_edited_time" in q.get("filter", {}) for q in self.notion.queries))

    def test_counter_follow_up_edits_preserve_22_and_original_timestamp(self):
        self.sync()
        page = self.notion.pages["p0"]
        page["properties"]["stage"]["select"]["name"] = "Contacted"
        before = receipt(page)["at"]
        page["properties"].update({"Notes": text("Follow-up note"), "Location": text("London"),
                                   "Gym": text("New gym")})
        page["last_edited_time"] = (NOW + timedelta(minutes=2)).isoformat()
        self.assertEqual(self.sync(NOW + timedelta(minutes=2)), 22)
        self.assertEqual(receipt(self.notion.pages["p0"])["at"], before)

    def test_contacted_transition_automatically_stamps_date_without_changing_ig_url(self):
        self.sync()
        original_url = self.notion.pages["p0"]["properties"]["Verified Profile URL"]["url"]
        self.notion.pages["p0"] = transition(
            self.notion.pages["p0"], "Contacted", now=NOW + timedelta(minutes=2))
        self.assertEqual(self.sync(NOW + timedelta(minutes=4)), 22)
        props = self.notion.pages["p0"]["properties"]
        self.assertEqual(props["Date Contacted"]["date"]["start"], "2026-10-08")
        self.assertEqual(props["Verified Profile URL"]["url"], original_url)
        date_writes = [body["properties"]["Date Contacted"] for id_, body in self.notion.writes
                       if id_ == "p0" and "Date Contacted" in body["properties"]]
        self.assertEqual(len(date_writes), 1)
        self.assertEqual(self.sync(NOW + timedelta(minutes=6)), 22)
        date_writes = [body for id_, body in self.notion.writes
                       if id_ == "p0" and "Date Contacted" in body["properties"]]
        self.assertEqual(len(date_writes), 1)

    def test_london_midnight_uses_stage_edit_date_not_worker_run_date(self):
        # BST 23:59 Friday is UTC 22:59; worker runs after local midnight.
        baseline = datetime(2026, 10, 9, 22, 56, tzinfo=timezone.utc)
        edited = datetime(2026, 10, 9, 22, 59, tzinfo=timezone.utc)
        self.sync(baseline)
        self.notion.pages["p0"] = transition(self.notion.pages["p0"], "Contacted", now=edited)
        self.sync(datetime(2026, 10, 9, 23, 1, tzinfo=timezone.utc))
        self.assertEqual(self.notion.pages["p0"]["properties"]["Date Contacted"]["date"]["start"], "2026-10-09")

    def test_gmt_midnight_uses_uk_day_and_preserves_existing_contact_date(self):
        start = datetime(2026, 11, 5, 23, 56, tzinfo=timezone.utc)
        self.sync(start)
        self.notion.pages["p0"] = transition(self.notion.pages["p0"], "Contacted",
                                               now=datetime(2026, 11, 5, 23, 59, tzinfo=timezone.utc))
        self.sync(datetime(2026, 11, 6, 0, 1, tzinfo=timezone.utc))
        self.assertEqual(self.notion.pages["p0"]["properties"]["Date Contacted"]["date"]["start"], "2026-11-05")
        self.notion.pages["p0"] = transition(self.notion.pages["p0"], "Replied",
                                               now=datetime(2026, 11, 6, 0, 2, tzinfo=timezone.utc))
        self.sync(datetime(2026, 11, 6, 0, 3, tzinfo=timezone.utc))
        self.assertEqual(self.notion.pages["p0"]["properties"]["Date Contacted"]["date"]["start"], "2026-11-05")

    def test_existing_contact_date_is_never_overwritten(self):
        self.sync()
        page = transition(self.notion.pages["p0"], "Contacted", now=NOW + timedelta(minutes=2))
        page["properties"]["Date Contacted"] = {"type": "date", "date": {"start": "2026-10-07"}}
        self.notion.pages["p0"] = page
        self.sync(NOW + timedelta(minutes=4))
        self.assertEqual(self.notion.pages["p0"]["properties"]["Date Contacted"]["date"]["start"], "2026-10-07")
        self.assertFalse(any(id_ == "p0" and "Date Contacted" in body["properties"]
                             for id_, body in self.notion.writes))

    def test_preexisting_contacted_record_is_not_backdated_on_first_sync(self):
        p = prospect("legacy_contact", stage="Contacted")
        self.notion = FakeNotion([p])
        self.sync()
        self.assertNotIn("Date Contacted", self.notion.pages["legacy_contact"]["properties"])
        self.assertFalse(any(id_ == "legacy_contact" and "Date Contacted" in body["properties"]
                             for id_, body in self.notion.writes))

    def test_concurrent_stage_change_skips_contact_stamp(self):
        self.sync()
        self.notion.pages["p0"] = transition(self.notion.pages["p0"], "Contacted",
                                             now=NOW + timedelta(minutes=2))
        prior_get = self.notion.get

        def moved_to_replied_before_get(url, **kwargs):
            if url.endswith("/pages/p0"):
                self.notion.pages["p0"]["properties"]["stage"]["select"]["name"] = "Replied"
            return prior_get(url, **kwargs)

        self.notion.get = moved_to_replied_before_get
        self.sync(NOW + timedelta(minutes=3))
        self.assertNotIn("Date Contacted", self.notion.pages["p0"]["properties"])
        self.assertFalse(any(id_ == "p0" and "Date Contacted" in body["properties"]
                             for id_, body in self.notion.writes))

    def test_counter_routes_old_ready_beyond_worker_batch_limit(self):
        self.sync()
        page = self.notion.pages["p0"]
        page["created_time"] = "2020-01-01T12:00:00Z"
        page["properties"]["Personalised DM Angle"] = text("New evidence")
        page["last_edited_time"] = (NOW + timedelta(minutes=2)).isoformat()
        self.assertEqual(self.sync(NOW + timedelta(minutes=2)), 21)
        self.assertEqual(self.notion.pages["p0"]["properties"]["stage"]["select"]["name"], "Needs Research")
        self.assertEqual(self.sync(NOW + timedelta(minutes=4)), 21)

    def test_counter_missing_receipt_moves_ready_to_research_without_changing_data(self):
        page = prospect(qualified=False)
        self.notion.pages = {page["id"]: page}
        before = copy.deepcopy(page["properties"])
        self.assertEqual(self.sync(), 0)
        actual = self.notion.pages[page["id"]]["properties"]
        self.assertEqual(actual["stage"]["select"]["name"], "Needs Research")
        for name in before:
            if name != "stage":
                self.assertEqual(actual[name], before[name])

    def test_routing_by_stage_id_preserves_live_property_label(self):
        page = prospect()
        page["properties"]["Stage (AI Fills First)"] = page["properties"].pop("stage")
        page["properties"]["Personalised DM Angle"] = text("Changed evidence")
        self.notion.pages = {page["id"]: page}
        self.assertEqual(self.sync(), 0)
        actual = self.notion.pages[page["id"]]["properties"]
        self.assertNotIn("stage", actual)
        self.assertEqual(actual["Stage (AI Fills First)"]["id"], "stage")
        self.assertEqual(actual["Stage (AI Fills First)"]["select"]["name"], "Needs Research")

    def test_routing_rechecks_contacted_edit_before_patching_stage(self):
        page = prospect(qualified=False)
        self.notion.pages = {page["id"]: page}
        original_get = self.notion.get
        def contacted_before_get(url, **kwargs):
            if "/pages/" in url:
                self.notion.pages[page["id"]]["properties"]["stage"]["select"]["name"] = "Contacted"
            return original_get(url, **kwargs)
        self.notion.get = contacted_before_get
        self.assertEqual(self.sync(), 0)
        self.assertEqual(self.notion.pages[page["id"]]["properties"]["stage"]["select"]["name"], "Contacted")
        self.assertFalse(any("stage" in body["properties"] for _, body in self.notion.writes))

    def test_queue_detects_receipt_problems_even_with_complete_ai_outputs(self):
        valid = prospect("valid")
        missing = prospect("missing", qualified=False)
        changed = prospect("changed")
        changed["properties"]["Personalised DM Angle"] = text("Changed evidence")
        inactive = transition(prospect("inactive"), "Needs Research")
        inactive["properties"]["stage"]["select"]["name"] = "Ready to Send"
        with patch("pipeline._query_stage_filter", side_effect=[[valid, missing, changed, inactive], [], []]):
            pages = query_ai_queue(self.notion, SETTINGS, "stage")
        self.assertEqual([page["id"] for page in pages], ["missing", "changed", "inactive"])

    def test_worker_routes_invalid_ready_without_automatic_ai_approval(self):
        for problem in ("missing", "malformed", "changed", "inactive"):
            with self.subTest(problem=problem):
                page = prospect()
                if problem == "missing":
                    del page["properties"][RECEIPT]
                elif problem == "malformed":
                    page["properties"][RECEIPT] = text("{broken")
                elif problem == "changed":
                    page["properties"]["Personalised DM Angle"] = text("New evidence")
                else:
                    page = transition(page, "Needs Research")
                    page["properties"]["stage"]["select"]["name"] = "Ready to Send"
                if problem in {"missing", "malformed"}:
                    # Newly created Ready rows must be routed, unlike legacy rows.
                    page["created_time"] = "2026-10-08T12:01:00+00:00"
                self.notion = FakeNotion([page])
                with patch("pipeline.Settings.from_env", return_value=SETTINGS), \
                     patch("pipeline.NotionSession", return_value=self.notion), \
                     patch("pipeline._resolve_stage_property_id", return_value="stage"), \
                     patch("pipeline.query_ai_queue", return_value=[page]), \
                     patch("pipeline.OpenAI"), patch("pipeline.qualify_and_draft") as ai, \
                     patch.dict("os.environ", {"OUTREACH_EXTERNAL_COUNTER": "true", "COUNTER_ONLY": "false", "OUTREACH_COUNTER_CUTOVER_AT": NOW.isoformat()}):
                    self.assertEqual(run_outreach(), 0)
                    ai.assert_not_called()
                self.assertEqual(self.notion.pages[page["id"]]["properties"]["stage"]["select"]["name"], "Needs Research")
                self.assertEqual(self.notion.pages[page["id"]]["properties"]["Draft DM"], page["properties"]["Draft DM"])

    def test_fresh_ai_requalification_gets_new_date_then_retries_stay_once(self):
        self.sync()
        old_at = receipt(self.notion.pages["p0"])["at"]
        self.notion.pages["p0"] = transition(self.notion.pages["p0"], "Needs Research")
        self.assertEqual(self.sync(), 21)
        tomorrow = NOW + timedelta(days=1)
        self.requalify("p0", now=tomorrow)
        self.assertEqual(self.sync(tomorrow), 1)
        new_at = receipt(self.notion.pages["p0"])["at"]
        self.assertNotEqual(new_at, old_at)
        self.assertEqual(self.sync(tomorrow + timedelta(minutes=2)), 1)
        self.assertEqual(receipt(self.notion.pages["p0"])["at"], new_at)

    def test_archive_disappears_from_delta_but_counter_decreases(self):
        self.sync()
        self.notion.pages["p0"]["archived"] = True
        self.assertEqual(self.sync(), 21)

    def test_historical_duplicate_archive_and_requalification_owner_refresh(self):
        old = prospect("old", "same", at=NOW - timedelta(days=1))
        current = prospect("new", "same")
        self.notion.pages = {"old": old, "new": current}
        self.assertEqual(self.sync(), 0)
        self.notion.pages["old"]["archived"] = True
        self.assertEqual(self.sync(NOW + timedelta(minutes=10)), 1)
        # A manual Stage restore cannot reactivate approval or award credit.
        self.notion.pages["old"]["archived"] = False
        current = transition(current, "Needs Research")
        current["properties"]["stage"]["select"]["name"] = "Ready to Send"
        self.notion.pages["new"] = current
        self.assertEqual(self.sync(NOW + timedelta(minutes=12)), 0)

    def test_api_failure_on_second_page_keeps_previous_counter(self):
        self.sync()
        original = self.notion.post
        calls = 0
        def fail_later(*args, **kwargs):
            nonlocal calls
            calls += 1
            return Response(status=503) if calls == 2 else original(*args, **kwargs)
        self.notion.post = fail_later
        with self.assertRaises(requests.HTTPError):
            self.sync()
        self.assertEqual(self.notion.counter, 22)

    def test_query_failure_keeps_counter_and_checkpoint(self):
        self.sync()
        with sqlite3.connect(self.path) as db:
            checkpoint = db.execute("SELECT value FROM metadata WHERE key='checkpoint'").fetchone()
        self.notion.fail_query = True
        with self.assertRaises(requests.HTTPError):
            self.sync(NOW + timedelta(minutes=2))
        self.assertEqual(self.notion.counter, 22)
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='checkpoint'").fetchone(), checkpoint)

    def test_deleted_page_disappears_from_membership_and_is_excluded(self):
        self.sync()
        del self.notion.pages["p0"]
        self.assertEqual(self.sync(NOW + timedelta(minutes=10)), 21)

    def test_bad_pagination_never_publishes_zero(self):
        self.sync()
        self.notion.invalid_pagination = True
        with self.assertRaises(RuntimeError):
            self.sync()
        self.assertEqual(self.notion.counter, 22)

    def test_crash_after_metadata_write_replays_without_double_credit(self):
        self.sync()
        self.notion.pages["p0"]["properties"]["stage"]["select"]["name"] = "Needs Research"
        self.notion.fail_counter = True
        with self.assertRaises(requests.HTTPError):
            self.sync()
        self.assertFalse(receipt(self.notion.pages["p0"])["active"])
        self.assertEqual(self.notion.counter, 22)
        self.notion.fail_counter = False
        self.assertEqual(self.sync(), 21)
        self.notion.pages["p0"]["properties"]["stage"]["select"]["name"] = "Ready to Send"
        self.assertEqual(self.sync(), 21)
        self.requalify("p0")
        self.notion.fail_counter = True
        with self.assertRaises(requests.HTTPError):
            self.sync()
        at = receipt(self.notion.pages["p0"])["at"]
        self.notion.fail_counter = False
        self.assertEqual(self.sync(), 22)
        self.assertEqual(receipt(self.notion.pages["p0"])["at"], at)

    def test_dry_run_no_writes_or_checkpoint(self):
        dry = Settings("", "unused", "source", "unused", 100, True)
        self.assertEqual(self.sync(settings=dry), 22)
        self.assertEqual(self.notion.writes, [])
        with sqlite3.connect(self.path) as db:
            self.assertEqual(db.execute("SELECT * FROM metadata").fetchall(), [])

    def test_schema_additions_idempotent_no_formulas_or_views_changed(self):
        self.notion.schema = {"Profile URL": {"type": "formula"}}
        self.assertEqual(set(ensure_schema(self.notion, SETTINGS)), {QUALIFIED_AT, RECEIPT})
        self.assertEqual(self.notion.writes, [])
        ensure_schema(self.notion, SETTINGS, apply=True)
        self.assertEqual(ensure_schema(self.notion, SETTINGS, apply=True), {})
        self.assertEqual(self.notion.schema["Profile URL"], {"type": "formula"})
        self.notion.schema[QUALIFIED_AT] = {"type": "number"}
        with self.assertRaises(RuntimeError):
            ensure_schema(self.notion, SETTINGS, apply=True)

    def test_cache_loss_recovers_from_notion_timestamps(self):
        self.sync()
        Path(self.path).unlink()
        self.assertEqual(self.sync(), 22)

    def test_midnight_with_failed_query_keeps_previous_display(self):
        self.sync()
        self.notion.fail_query = True
        with self.assertRaises(requests.HTTPError):
            self.sync(NOW + timedelta(days=1))
        self.assertEqual(self.notion.counter, 22)
        self.notion.fail_query = False
        self.assertEqual(self.sync(NOW + timedelta(days=1)), 0)

    def test_worker_atomic_qualification_and_failure_clear(self):
        page = prospect(qualified=False, stage="AI Queue")
        self.notion.pages = {page["id"]: page}
        candidate = candidate_from_page(page)
        result = {"eligible": True, "evidence_sufficient": True, "priority_score": 45,
                  "qualification_reason": "Qualified", "outreach_approach": "A", "draft_dm": "Yo, saw the training."}
        self.assertEqual(update_ai_result(self.notion, SETTINGS, candidate, result, stage_property_id="stage"), "Ready to Send")
        properties = self.notion.writes[-1][1]["properties"]
        self.assertIn(QUALIFIED_AT, properties)
        self.assertIn(RECEIPT, properties)
        self.assertIsNotNone(receipt(self.notion.pages[page["id"]]))
        result.update(eligible=False, draft_dm="")
        self.assertEqual(update_ai_result(self.notion, SETTINGS, candidate, result, stage_property_id="stage"), "Rejected")
        self.assertIsNone(receipt(self.notion.pages[page["id"]]))

    def test_identical_ai_retry_preserves_timestamp_and_queue_recheck_replaces_it(self):
        page = prospect()
        self.notion.pages = {page["id"]: page}
        result = {"eligible": True, "evidence_sufficient": True, "priority_score": 45,
                  "qualification_reason": "Eligible and sufficient", "outreach_approach": "A", "draft_dm": "Yo, saw your training."}
        at = receipt(page)["at"]
        update_ai_result(self.notion, SETTINGS, candidate_from_page(page), result, stage_property_id="stage")
        self.assertEqual(receipt(self.notion.pages[page["id"]])["at"], at)
        self.notion.pages[page["id"]]["properties"]["stage"]["select"]["name"] = "AI Queue"
        update_ai_result(self.notion, SETTINGS, candidate_from_page(page), result, stage_property_id="stage")
        self.assertNotEqual(receipt(self.notion.pages[page["id"]])["at"], at)

    def test_dry_run_can_preview_missing_handle_and_default_sport(self):
        page = prospect(qualified=False, stage="AI Queue")
        page["properties"]["Instagram Handle"] = text("")
        page["properties"]["Sport"] = {"type": "select", "select": None}
        self.notion.pages = {page["id"]: page}
        candidate = candidate_from_page(page)
        candidate.update(instagram_handle="p1", sport="Boxing")
        result = {"eligible": True, "evidence_sufficient": True, "priority_score": 45,
                  "qualification_reason": "Qualified", "outreach_approach": "A", "draft_dm": "Yo"}
        dry = Settings("", "unused", "source", "unused", 100, True)
        self.assertEqual(update_ai_result(self.notion, dry, candidate, result, stage_property_id="stage"), "Ready to Send")
        self.assertEqual(self.notion.writes, [])

    def test_derived_formula_update_during_ai_does_not_bill_a_second_run(self):
        page = prospect(qualified=False, stage="AI Queue")
        candidate = candidate_from_page(page)
        page["properties"]["Profile URL"] = {"type": "formula", "formula": {"type": "string", "string": "https://instagram.com/p1/"}}
        self.notion.pages = {page["id"]: page}
        result = {"eligible": True, "evidence_sufficient": True, "priority_score": 45,
                  "qualification_reason": "Qualified", "outreach_approach": "A", "draft_dm": "Yo"}
        self.assertEqual(update_ai_result(self.notion, SETTINGS, candidate, result, stage_property_id="stage"), "Ready to Send")

    def test_worker_does_not_overwrite_concurrent_human_change(self):
        page = prospect(qualified=False, stage="Contacted")
        self.notion.pages = {page["id"]: page}
        with self.assertRaises(RuntimeError):
            update_ai_result(self.notion, SETTINGS, candidate_from_page(page),
                             {"eligible": True, "evidence_sufficient": True, "priority_score": 45,
                              "qualification_reason": "Qualified", "outreach_approach": "A", "draft_dm": "Yo"},
                             stage_property_id="stage")
        self.assertEqual(self.notion.writes, [])

    @patch("pipeline.OpenAI")
    @patch("pipeline._resolve_stage_property_id", return_value="stage")
    @patch("pipeline.NotionSession")
    @patch("pipeline.Settings.from_env")
    def test_counter_only_has_no_openai_calls_and_reports_failure(self, settings, session, stage, openai):
        settings.return_value = SETTINGS
        session.return_value = self.notion
        with patch.dict("os.environ", {"COUNTER_ONLY": "true", "OUTREACH_COUNTER_STATE": self.path, "OUTREACH_COUNTER_CUTOVER_AT": NOW.isoformat(),
                                       "NOTION_DAILY_COUNTER_PAGE_ID": "counter"}):
            with patch("pipeline.DAILY_COUNTER_PAGE_ID", "counter"):
                self.assertEqual(run_outreach(), 0)
                self.notion.fail_query = True
                self.assertEqual(run_outreach(), 1)
        openai.assert_not_called()
        settings.assert_called_with(require_openai=False)

    def test_state_for_other_source_refuses_publication(self):
        self.sync()
        other = Settings("", "unused", "different", "unused", 100, False)
        with self.assertRaises(RuntimeError):
            self.sync(settings=other)
        self.assertEqual(self.notion.counter, 22)

    @patch("daily_counter.time.sleep")
    @patch("requests.Session.request")
    def test_rate_limit_and_transient_retries(self, request, sleep):
        request.side_effect = [Response(status=429, headers={"Retry-After": "1"}),
                               Response(status=503), Response({"results": []})]
        response = NotionSession().post("https://api.notion.com/test")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(request.call_count, 3)
        self.assertIn(unittest.mock.call(1.0), sleep.call_args_list)

    @patch("daily_counter.time.sleep")
    @patch("requests.Session.request")
    def test_network_failure_retry_budget(self, request, sleep):
        request.side_effect = requests.Timeout("test")
        with self.assertRaises(requests.Timeout):
            NotionSession().get("https://api.notion.com/test")
        self.assertEqual(request.call_count, 5)


if __name__ == "__main__":
    unittest.main()
