#!/usr/bin/env python3
"""Refresh grandfathered, receipt-free Ready to Send DMs without requalification.

Preview by default. Writes ONLY Draft DM when --apply is passed.
Never modifies Stage, qualification receipt/date, priority score or AI qualification.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI
from core import Settings, _plain_text, _rich_text_value, candidate_from_page, fight_date_issue, AI_INSTRUCTIONS
from daily_counter import NotionSession
from pipeline import _patch_page, _query_stage_filter, _resolve_stage_property_id, _retrieve_target_page, _stage_value
from qualification import RECEIPT, grandfathered_without_receipt, receipt

# Reuse the live production drafting instructions rather than a second style prompt.
# No qualification instructions or re-qualification output for legacy pages.
PROMPT = (
    "Rewrite this already-approved unsent draft for copy only. Do not make a "
    "qualification decision, change their status, or request more research. "
    "Only use evidenced facts from the candidate research and old draft. "
    "Never position weigh-ins, weight cutting or refuelling as the Unlxck benefit. "
    "If a safe personalised draft cannot be produced, return an empty string.\n\n"
    + "Do not invent fight dates, titles, results, injuries, gyms, camps or athlete pain points. "
    + "Keep the original supported M1 hook if possible. "
    + "Use a past event as past; never claim an expired fight is upcoming.\n\n"
    + "VOICE AND STYLE\n"
    + AI_INSTRUCTIONS.split("VOICE AND STYLE\n", 1)[1].split("\nIf evidence is insufficient,", 1)[0]
)


def text_of(page, name):
    return _plain_text(page["properties"].get(name))

def eligible(page, stage_id):
    return (
        _stage_value(page, stage_id) == "Ready to Send"
        and not page.get("archived") and not page.get("in_trash")
        and receipt(page) is None
        and not text_of(page, RECEIPT).strip()
        and grandfathered_without_receipt(page)
        and bool(text_of(page, "Draft DM").strip())
        and "M3: Want the details?" not in text_of(page, "Draft DM")
    )

def dm_ok(dm):
    lines = [line.strip() for line in dm.splitlines() if line.strip()]
    if len(lines) != 3:
        return False
    if not lines[0].startswith("M1: Yo ") or not lines[1].startswith("M2: "):
        return False
    if lines[2] != "M3: Want the details?":
        return False
    if "early access to Unlxck" not in lines[1]:
        return False
    if any(term in dm.lower() for term in ("weigh-in", "weigh in", "weight cut", "refuelling", "refueling")):
        return False
    total = sum(len(line.split()) - 1 for line in lines)
    return 23 <= total <= 45

def unchanged(original, live, stage_id):
    if not eligible(live, stage_id):
        return False
    return (
        original.get("last_edited_time") == live.get("last_edited_time")
        and original["properties"] == live["properties"]
        and original.get("created_time") == live.get("created_time")
    )

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--page-id", default="")
    parser.add_argument("--backup-dir", default="/opt/unlxck/outreach-worker/state")
    args = parser.parse_args()
    if not 1 <= args.limit <= 300:
        parser.error("--limit must be 1 to 300")

    settings = Settings.from_env()
    if args.apply and settings.dry_run:
        raise RuntimeError("DRY_RUN=true: cannot apply")
    session = NotionSession()
    stage_id = _resolve_stage_property_id(session, settings)
    if args.page_id:
        rows = [_retrieve_target_page(session, settings, args.page_id)]
    else:
        rows = _query_stage_filter(
            session, settings, stage_property_id=stage_id,
            select_filter={"equals": "Ready to Send"},
            limit=1000, sort_direction="descending")
    client = OpenAI(api_key=settings.openai_api_key)
    updated = skipped = failed = 0
    backup = None
    try:
        for page in rows:
            if updated >= args.limit:
                break
            if not eligible(page, stage_id):
                skipped += 1
                continue
            cand = candidate_from_page(page)
            label = cand["candidate"] or page["id"]
            if not cand["candidate"].strip() or not cand["personalised_dm_angle"].strip():
                print(f"KEPT ORIGINAL {label}: insufficient research")
                skipped += 1
                continue
            try:
                result = client.responses.create(
                    model=settings.openai_model,
                    instructions=PROMPT,
                    input=json.dumps({"candidate": cand, "old_draft": text_of(page, "Draft DM")},
                                     ensure_ascii=False),
                    text={"format": {"type": "json_schema", "name": "draft_only",
                                     "strict": True,
                                     "schema": {"type": "object",
                                                "properties": {"draft_dm": {"type": "string"}},
                                                "required": ["draft_dm"], "additionalProperties": False}}},
                    max_output_tokens=600,
                    store=False,
                )
                dm = json.loads(result.output_text)["draft_dm"].strip()
                if not dm_ok(dm):
                    print(f"KEPT ORIGINAL {label}: invalid or incomplete rewrite")
                    skipped += 1
                    continue
                approach = (page["properties"].get("Outreach Approach") or {}).get("select") or {}
                if fight_date_issue(cand, draft=dm, approach=approach.get("name", "A")):
                    print(f"KEPT ORIGINAL {label}: fight-date verification failed")
                    skipped += 1
                    continue
                live = _retrieve_target_page(session, settings, page["id"])
                if not unchanged(page, live, stage_id):
                    print(f"KEPT ORIGINAL {label}: record changed during generation")
                    skipped += 1
                    continue
                if not args.apply:
                    print(f"PREVIEW {label}:\n{dm}\n")
                    updated += 1
                    continue
                if backup is None:
                    directory = Path(args.backup_dir)
                    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                    filename = "legacy-dm-refresh-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl"
                    fd = os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                    backup = os.fdopen(fd, "w", encoding="utf-8")
                    print(f"Backup: {directory / filename}")
                backup.write(json.dumps({"page_id": page["id"], "candidate": label,
                                         "before": live["properties"], "edited_at": live["last_edited_time"]},
                                        ensure_ascii=False) + "\n")
                backup.flush()
                os.fsync(backup.fileno())
                _patch_page(session, settings, page["id"],
                            {"Draft DM": {"rich_text": _rich_text_value(dm)}})
                after = _retrieve_target_page(session, settings, page["id"])
                if (not _stage_value(after, stage_id) == "Ready to Send"
                        or text_of(after, "Draft DM") != dm
                        or text_of(after, RECEIPT).strip()
                        or after["properties"].get("Qualified At") != live["properties"].get("Qualified At")
                        or after["properties"].get("Priority Score") != live["properties"].get("Priority Score")):
                    raise RuntimeError("Post-write audit failed; review backup and stop")
                print(f"UPDATED {label}: Draft DM only; stage and qualification unchanged")
                updated += 1
            except Exception as exc:
                print(f"ERROR {label}: {exc}")
                failed += 1
                if "Post-write audit failed" in str(exc):
                    raise
    finally:
        if backup:
            backup.close()
    print(f"Legacy refresh complete: {'applied' if args.apply else 'previewed'}={updated}, skipped={skipped}, failed={failed}")
    if failed:
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
