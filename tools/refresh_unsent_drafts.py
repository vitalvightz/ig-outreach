#!/usr/bin/env python3
"""One-off refresh of unsent Unlxck DMs. Preserves stage and qualification time.

Default is preview-only. This script deliberately does NOT move rows to AI Queue,
rerank prospects, or touch Contacted/replied records.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import OpenAI

from core import (
    AI_INSTRUCTIONS, Settings, _plain_text, _rich_text_value, candidate_from_page,
    fight_date_issue, qualify_and_draft,
)
from daily_counter import NotionSession, apply_properties
from pipeline import (
    _patch_page, _query_stage_filter, _resolve_stage_property_id,
    _retrieve_target_page, _stage_value,
)
from qualification import (
    RECEIPT, QUALIFIED_AT, approval_valid, fingerprint, new_receipt,
    receipt, receipt_properties, research_fingerprint, utc_time,
)


def qualified_at(page: dict) -> str | None:
    return ((page["properties"].get(QUALIFIED_AT) or {}).get("date") or {}).get("start")


def safe_unsent(page: dict, stage_id: str) -> bool:
    if _stage_value(page, stage_id) != "Ready to Send":
        return False
    if "M3: Want the details?" in _plain_text(page["properties"].get("Draft DM")):
        return False
    proof = receipt(page)
    if not proof or not proof["active"]:
        return False
    stamp = qualified_at(page)
    if bool(stamp) != bool(proof.get("at")):
        return False
    if stamp and utc_time(stamp) != utc_time(proof["at"]):
        return False
    return approval_valid(page, datetime.now(timezone.utc), unsent=True)


def new_draft_is_valid(text: str) -> bool:
    parts = [line.strip() for line in text.splitlines() if line.strip()]
    if len(parts) != 3 or parts[2] != "M3: Want the details?":
        return False
    if not parts[0].startswith("M1: Yo ") or not parts[1].startswith("M2: "):
        return False
    words_m2 = len(parts[1][4:].split())
    words_total = sum(len(p[4:].split()) for p in parts)
    return 10 <= words_m2 <= 20 and 20 <= words_total <= 48


def unchanged(original: dict, current: dict, stage_id: str) -> bool:
    return (
        safe_unsent(current, stage_id)
        and fingerprint(original) == fingerprint(current)
        and receipt(original) == receipt(current)
        and research_fingerprint(candidate_from_page(original))
        == research_fingerprint(candidate_from_page(current))
        and qualified_at(original) == qualified_at(current)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page-id", default="", help="Test one exact Notion record")
    parser.add_argument("--limit", type=int, default=1, help="Max successful drafts (default 1)")
    parser.add_argument("--apply", action="store_true", help="Write verified drafts to Notion")
    parser.add_argument("--backup-dir", default="/opt/unlxck/outreach-worker/state")
    args = parser.parse_args()
    if not 1 <= args.limit <= 300:
        parser.error("--limit must be between 1 and 300")
    if "M2 EXAMPLES (STYLE REFERENCES" not in AI_INSTRUCTIONS:
        raise RuntimeError("Updated prompt is not installed; refusing refresh")

    settings = Settings.from_env()
    if args.apply and settings.dry_run:
        raise RuntimeError("DRY_RUN=true prevents applying changes")

    session = NotionSession()
    stage_id = _resolve_stage_property_id(session, settings)
    if args.page_id:
        pages = [_retrieve_target_page(session, settings, args.page_id)]
    else:
        pages = _query_stage_filter(
            session, settings, stage_property_id=stage_id,
            select_filter={"equals": "Ready to Send"},
            limit=1000, sort_direction="descending",
        )

    client = OpenAI(api_key=settings.openai_api_key)
    backup_file = None
    done = 0
    skipped = 0
    try:
        for original in pages:
            if done >= args.limit:
                break
            if not safe_unsent(original, stage_id):
                skipped += 1
                continue

            candidate = candidate_from_page(original)
            name = candidate["candidate"] or candidate["page_id"]
            old_approach = (original["properties"].get("Outreach Approach") or {}).get("select") or {}
            old_approach = old_approach.get("name")
            result = qualify_and_draft(client, settings, candidate)
            draft = result["draft_dm"].strip()

            if not (result["eligible"] and result["evidence_sufficient"]
                    and result["outreach_approach"] == old_approach
                    and new_draft_is_valid(draft)
                    and fight_date_issue(candidate, draft=draft, approach=old_approach) is None):
                print(f"SKIP {name}: regenerated draft/approval did not pass safety checks")
                skipped += 1
                continue

            current = _retrieve_target_page(session, settings, candidate["page_id"])
            if not unchanged(original, current, stage_id):
                print(f"SKIP {name}: record changed or lost valid approval")
                skipped += 1
                continue

            old_proof = receipt(current)
            assert old_proof is not None
            new_dm_props = {"Draft DM": {"rich_text": _rich_text_value(draft)}}
            proposed = apply_properties(current, new_dm_props)
            new_proof = new_receipt(proposed, old_proof.get("at"), legacy=old_proof["legacy"])
            props = {**new_dm_props, RECEIPT: receipt_properties(new_proof)[RECEIPT]}

            checked = apply_properties(current, props)
            if not approval_valid(checked, datetime.now(timezone.utc), unsent=True):
                print(f"SKIP {name}: new draft/receipt validation failed")
                skipped += 1
                continue
            if qualified_at(checked) != qualified_at(current):
                raise RuntimeError("Qualified At would change; refusing refresh")

            if not args.apply:
                print(f"PREVIEW {name} ({old_approach}):\n{draft}\n")
                done += 1
                continue

            if backup_file is None:
                directory = Path(args.backup_dir)
                directory.mkdir(mode=0o700, parents=True, exist_ok=True)
                filename = f"draft-refresh-{datetime.now(timezone.utc):%Y%m%dT%H%M%S%fZ}.jsonl"
                descriptor = os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                backup_file = os.fdopen(descriptor, "w", encoding="utf-8")
                print(f"Backup: {directory / filename}")
            backup_file.write(json.dumps({
                "page_id": candidate["page_id"],
                "candidate": name,
                "previous_draft": current["properties"].get("Draft DM"),
                "previous_receipt": current["properties"].get(RECEIPT),
                "previous_qualified_at": current["properties"].get(QUALIFIED_AT),
            }, ensure_ascii=False) + "\n")
            backup_file.flush()
            os.fsync(backup_file.fileno())

            # Both fields are patched together; the original Qualified At is untouched.
            _patch_page(session, settings, candidate["page_id"], props)
            verified = _retrieve_target_page(session, settings, candidate["page_id"])
            if not (_stage_value(verified, stage_id) == "Ready to Send"
                    and _plain_text(verified["properties"].get("Draft DM")) == draft
                    and receipt(verified) == new_proof
                    and qualified_at(verified) == qualified_at(current)
                    and approval_valid(verified, datetime.now(timezone.utc), unsent=True)):
                raise RuntimeError(f"Post-write verification failed for {name}; stop and inspect backup")
            print(f"UPDATED {name}: preserved original qualification timestamp")
            done += 1

    finally:
        if backup_file is not None:
            backup_file.close()

    print(f"Refresh complete: {'applied' if args.apply else 'previewed'}={done}, skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
