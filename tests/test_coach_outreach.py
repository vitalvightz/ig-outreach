import copy
from contextlib import ExitStack
from dataclasses import replace
import fcntl
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import coach_outreach as coach
from core import Settings, _plain_text
from daily_counter import apply_properties


def text(value, kind="rich_text"):
    return {"type": kind, kind: [{"plain_text": value, "text": {"content": value}}]}


class CoachTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "drafts.json"
        env = patch.dict(os.environ, {"OUTREACH_COACH_STATE": str(self.path),
                                     "NOTION_COACHES_DATA_SOURCE_ID": coach.COACH_SOURCE})
        env.start()
        self.addCleanup(env.stop)
        self.settings = Settings("unused", "unused", "athletes", "existing-model", 100, False)
        self.page = {"id": "coach", "properties": {
            "Coach / Gym": text("Wayne Smith", "title"),
            "Personalised DM Angle": text("runs good sessions"),
            "Draft DM": text(""),
            "Status": {"type": "select", "select": {"name": "To Contact"}},
            "Last Contacted": {"date": None},
        }}
        self.schema = {name: {"type": "rich_text"} for name in ("Personalised DM Angle", "Draft DM")}
        self.client = Mock()
        self.client.responses.create.return_value = SimpleNamespace(
            status="completed", output_text=json.dumps({
                "greeting_name": "Wayne", "observation": "saw you run good sessions"}))
        self.writes = []
        api = patch("coach_outreach.api", side_effect=self.api)
        api.start()
        self.addCleanup(api.stop)
        query = patch("coach_outreach.query_all", side_effect=lambda *args: [copy.deepcopy(self.page)])
        query.start()
        self.addCleanup(query.stop)

    def api(self, session, settings, method, path, **kwargs):
        self.assertEqual(settings.notion_data_source_id, coach.COACH_SOURCE)
        if path.startswith("data_sources/"):
            if method == "patch":
                self.schema.update({name: {"type": "rich_text"} for name in kwargs["json"]["properties"]})
            return {"properties": self.schema}
        if method == "get":
            return copy.deepcopy(self.page)
        props = kwargs["json"]["properties"]
        self.assertEqual(set(props), {"Draft DM"})
        self.writes.append(props)
        self.page = apply_properties(self.page, props)
        return self.page

    def run_sync(self):
        return coach.sync_coaches(None, self.settings, self.client)

    def draft(self):
        return _plain_text(self.page["properties"]["Draft DM"])

    def test_generate_once_then_regenerate_changed_angle_without_qualification(self):
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.draft(), f"Hey Wayne, saw you run good sessions. {coach.INTRO}")
        self.run_sync()
        self.page["properties"]["Notes"] = text("unrelated change")
        self.run_sync()
        self.assertEqual(self.client.responses.create.call_count, 1)
        self.page["properties"]["Personalised DM Angle"] = text("nice gym")
        self.run_sync()
        self.assertEqual(self.client.responses.create.call_count, 2)
        args = self.client.responses.create.call_args.kwargs
        self.assertEqual(json.loads(args["input"]), {"coach_name": "Wayne Smith", "personalisation": "nice gym"})
        self.assertEqual(args["model"], "existing-model")
        self.assertFalse(args["store"])

    def test_existing_manual_draft_and_later_edits_or_clearing_are_preserved(self):
        for manual in ("A manually edited DM", ""):
            with self.subTest(manual=manual):
                if self.path.exists():
                    self.path.unlink()
                self.page["properties"]["Draft DM"] = text("")
                self.run_sync()
                self.page["properties"]["Draft DM"] = text(manual)
                self.run_sync()
                self.page["properties"]["Personalised DM Angle"] = text("new angle")
                count = self.client.responses.create.call_count
                self.run_sync()
                self.assertEqual(self.client.responses.create.call_count, count)
                self.assertEqual(self.draft(), manual)
        self.path.unlink()
        self.page["properties"]["Draft DM"] = text("Existing message before deployment")
        count = self.client.responses.create.call_count
        self.run_sync()
        self.assertEqual(self.client.responses.create.call_count, count)

    def test_contacted_and_later_statuses_or_contact_date_never_generate(self):
        for status in ("Contacted", "Replied", "Demo Booked", "Pilot Agreed", "Not Interested", ""):
            self.page["properties"]["Status"]["select"]["name"] = status
            self.run_sync()
        self.page["properties"]["Status"]["select"]["name"] = "To Contact"
        self.page["properties"]["Last Contacted"]["date"] = {"start": "2026-11-17"}
        self.run_sync()
        self.client.responses.create.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_during_ai_manual_edit_contact_or_angle_change_prevents_write(self):
        for field, value in (("Draft DM", text("human edit")),
                             ("Status", {"select": {"name": "Contacted"}}),
                             ("Personalised DM Angle", text("changed during AI"))):
            with self.subTest(field=field):
                original = copy.deepcopy(self.page)
                if self.path.exists():
                    self.path.unlink()
                def change(**kwargs):
                    self.page["properties"][field] = value
                    return SimpleNamespace(status="completed", output_text=json.dumps({
                        "greeting_name": "Wayne", "observation": "saw you run good sessions"}))
                self.client.responses.create.side_effect = change
                self.run_sync()
                self.assertEqual(self.writes, [])
                self.page = original

    def test_failed_patch_reuses_saved_generation_in_next_process(self):
        original_api = self.api
        def fail(session, settings, method, path, **kwargs):
            if method == "patch" and path.startswith("pages/"):
                raise RuntimeError("write unavailable")
            return original_api(session, settings, method, path, **kwargs)
        with patch("coach_outreach.api", side_effect=fail):
            self.assertEqual(self.run_sync(), 1)
        self.assertEqual(self.draft(), "")
        self.assertEqual(self.run_sync(), 0)
        self.assertEqual(self.client.responses.create.call_count, 1)
        self.assertTrue(self.draft())

    def test_lost_patch_response_recovers_without_ai_or_duplicate_write(self):
        original_api = self.api
        def lost(session, settings, method, path, **kwargs):
            result = original_api(session, settings, method, path, **kwargs)
            if method == "patch":
                raise RuntimeError("response lost after write")
            return result
        with patch("coach_outreach.api", side_effect=lost):
            self.assertEqual(self.run_sync(), 1)
        self.run_sync()
        self.assertEqual(self.client.responses.create.call_count, 1)
        self.assertEqual(len(self.writes), 1)

    def test_preview_empty_angle_and_overlapping_poll_have_no_ai_calls(self):
        self.settings = replace(self.settings, dry_run=True)
        self.run_sync()
        self.assertFalse(self.path.exists())
        self.settings = replace(self.settings, dry_run=False)
        self.page["properties"]["Personalised DM Angle"] = text("   ")
        self.run_sync()
        self.page["properties"]["Personalised DM Angle"] = text("nice gym")
        with self.path.with_suffix(".lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_sync()
        self.client.responses.create.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_schema_is_additive_and_wrong_type_fails_before_ai(self):
        self.schema.pop("Draft DM")
        self.schema["Unrelated"] = {"type": "formula"}
        self.run_sync()
        self.assertEqual(self.schema["Unrelated"], {"type": "formula"})
        self.schema["Draft DM"] = {"type": "formula"}
        with self.assertRaises(RuntimeError):
            self.run_sync()

    def test_corrupt_state_fails_before_ai_or_writes(self):
        self.path.write_text("{invalid")
        with self.assertRaises(ValueError):
            self.run_sync()
        self.client.responses.create.assert_not_called()
        self.assertEqual(self.writes, [])

    def test_robotic_opening_retries_once_then_saves_natural_opening(self):
        good = self.client.responses.create.return_value
        bad = SimpleNamespace(status="completed", output_text=json.dumps({
            "greeting_name": "Wayne Smith", "observation": "you are associated with Golden Gloves ABC"}))
        self.client.responses.create.side_effect = [bad, good]
        self.run_sync()
        self.assertEqual(self.client.responses.create.call_count, 2)
        self.assertEqual(self.draft(), f"Hey Wayne, saw you run good sessions. {coach.INTRO}")
        self.run_sync()
        self.assertEqual(self.client.responses.create.call_count, 2)

    def test_invalid_opening_never_written_and_retry_is_bounded(self):
        for observation in ("nice gym", "saw you are affiliated with Golden Gloves ABC",
                            "I noticed your association with Golden Gloves ABC",
                            "one two three four five six seven eight nine ten eleven twelve thirteen"):
            self.client.responses.create.reset_mock()
            self.client.responses.create.return_value = SimpleNamespace(
                status="completed", output_text=json.dumps({"greeting_name": "Wayne", "observation": observation}))
            self.assertEqual(self.run_sync(), 1)
            self.assertEqual(self.client.responses.create.call_count, 2)
            self.assertEqual(self.writes, [])

    def test_organisation_uses_neutral_greeting_with_fixed_offer(self):
        self.client.responses.create.return_value = SimpleNamespace(
            status="completed", output_text=json.dumps({
                "greeting_name": "there", "observation": "came across your gym in Liverpool"}))
        draft = coach.draft_dm(self.client, self.settings, "Golden Gloves ABC", "Gym in Liverpool")
        self.assertEqual(draft, f"Hey there, came across your gym in Liverpool. {coach.INTRO}")
        args = self.client.responses.create.call_args.kwargs
        self.assertEqual(args["text"]["format"]["type"], "json_schema")
        self.assertNotIn(coach.INTRO, args["input"])

    def test_event_details_and_repeated_names_retry_to_simple_first_name_opening(self):
        for greeting, observation in (
            ("Wayne Smith", "saw you were at the boxing show"),
            ("Wayne", "saw Wayne Smith at the boxing show"),
            ("Wayne", "saw your boxing show live on DAZN"),
            ("Wayne", "saw your show at the leisure centre"),
            ("Wayne", "saw you at the Top Tier Boxing Grand Finale live on DAZN"),
        ):
            with self.subTest(greeting=greeting, observation=observation):
                self.client.responses.create.side_effect = [
                    SimpleNamespace(status="completed", output_text=json.dumps({
                        "greeting_name": greeting, "observation": observation})),
                    SimpleNamespace(status="completed", output_text=json.dumps({
                        "greeting_name": "Wayne", "observation": "saw you were at the boxing show"})),
                ]
                self.client.responses.create.reset_mock()
                draft = coach.draft_dm(self.client, self.settings, "Wayne Smith",
                                       "Attended the Top Tier Boxing Grand Finale at X Leisure Centre, live on DAZN")
                self.assertEqual(draft, f"Hey Wayne, saw you were at the boxing show. {coach.INTRO}")
                self.assertEqual(self.client.responses.create.call_count, 2)

    def test_short_natural_observation_is_not_padded(self):
        self.client.responses.create.return_value = SimpleNamespace(
            status="completed", output_text=json.dumps({
                "greeting_name": "Wayne", "observation": "saw your coaching clips"}))
        draft = coach.draft_dm(self.client, self.settings, "Wayne Smith", "Posted coaching clips")
        self.assertEqual(draft, f"Hey Wayne, saw your coaching clips. {coach.INTRO}")
        self.client.responses.create.assert_called_once()

    def test_prompt_change_refreshes_worker_owned_draft_once_preserving_manual_copy(self):
        self.run_sync()
        with patch("coach_outreach.INTRO", coach.INTRO + " Updated offer."):
            self.run_sync()
            self.run_sync()
            self.assertEqual(self.client.responses.create.call_count, 2)
            self.assertTrue(self.draft().endswith(" Updated offer."))
            self.page["properties"]["Draft DM"] = text("My hand-edited message")
            self.run_sync()
        self.run_sync()
        self.assertEqual(self.draft(), "My hand-edited message")
        self.assertEqual(self.client.responses.create.call_count, 2)


class WorkerRoutingTests(unittest.TestCase):
    def test_coaches_use_normal_poll_and_do_not_run_in_counter_or_target_mode(self):
        from pipeline import run_outreach
        settings = Settings("unused", "unused", "athletes", "existing-model", 100, True)
        for counter, target in ((False, None), (True, None), (False, [])):
            with self.subTest(counter=counter, target=target), ExitStack() as stack:
                stack.enter_context(patch.dict(os.environ, {"COUNTER_ONLY": str(counter).lower(),
                                                           "OUTREACH_EXTERNAL_COUNTER": "true"}))
                for name, value in (("Settings.from_env", settings), ("NotionSession", Mock()),
                                    ("_resolve_stage_property_id", "stage"), ("ensure_schema", {}),
                                    ("OpenAI", Mock()), ("_target_page_if_requested", target),
                                    ("query_ai_queue", []), ("query_all", [])):
                    stack.enter_context(patch(f"pipeline.{name}", return_value=value))
                coaches = stack.enter_context(patch("pipeline.sync_coaches", return_value=0))
                counter_sync = stack.enter_context(patch("pipeline._update_daily_progress_counter"))
                self.assertEqual(run_outreach(), 0)
                self.assertEqual(coaches.call_count, int(not counter and target is None))
                self.assertEqual(counter_sync.call_count, int(counter))

    def test_coach_failure_still_allows_athlete_counter_to_complete(self):
        from pipeline import run_outreach
        settings = Settings("unused", "unused", "athletes", "existing-model", 100, True)
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {"COUNTER_ONLY": "false", "OUTREACH_EXTERNAL_COUNTER": "false"}))
            for name, value in (("Settings.from_env", settings), ("NotionSession", Mock()),
                                ("_resolve_stage_property_id", "stage"), ("ensure_schema", {}),
                                ("OpenAI", Mock()), ("_target_page_if_requested", None),
                                ("query_ai_queue", []), ("query_all", [])):
                stack.enter_context(patch(f"pipeline.{name}", return_value=value))
            stack.enter_context(patch("pipeline.sync_coaches", side_effect=RuntimeError("coaches unavailable")))
            counter = stack.enter_context(patch("pipeline._update_daily_progress_counter"))
            self.assertEqual(run_outreach(), 1)
            counter.assert_called_once()
