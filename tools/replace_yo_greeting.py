#!/usr/bin/env python3
"""Replace the opening greeting in existing unsent Ready to Send DMs.

Preview by default; --apply only with deployment lock. No OpenAI calls.
Never changes stage, approach, qualification time, scoring, or contacted records.
Valid receipts must be re-fingerprinted atomically alongside Draft DM.
"""
from __future__ import annotations
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from core import Settings, _plain_text, _rich_text_value
from daily_counter import NotionSession, apply_properties
from pipeline import _patch_page, _query_stage_filter, _resolve_stage_property_id, _retrieve_target_page, _stage_value
from qualification import RECEIPT, QUALIFIED_AT, approval_valid, grandfathered_without_receipt, new_receipt, receipt, receipt_properties, fingerprint


def replacement(old):
    # Only alter the opening greeting; retain every other word.
    if old.startswith("M1: Yo "):
        return "M1: Hey " + old[len("M1: Yo "):]
    if old.startswith("Yo "):
        return "Hey " + old[len("Yo "):]
    return old


def dm(page):
    return _plain_text(page["properties"].get("Draft DM")).strip()


def valid_target(page, stage_id):
    if _stage_value(page, stage_id) != "Ready to Send" or page.get("archived") or page.get("in_trash"):
        return False
    old = dm(page)
    return bool(old) and replacement(old) != old


def proposal(page, stage_id):
    if not valid_target(page, stage_id):
        return None
    old_proof = receipt(page)
    raw = _plain_text(page["properties"].get(RECEIPT)).strip()
    props = {"Draft DM": {"rich_text": _rich_text_value(replacement(dm(page)))}}
    if old_proof is not None:
        if not old_proof["active"] or not approval_valid(page, datetime.now(timezone.utc), unsent=True):
            return None
        updated = apply_properties(page, props)
        new_proof = new_receipt(updated, old_proof.get("at"), legacy=old_proof["legacy"])
        props[RECEIPT] = receipt_properties(new_proof)[RECEIPT]
        verified = apply_properties(page, props)
        if not approval_valid(verified, datetime.now(timezone.utc), unsent=True):
            return None
    elif raw or not grandfathered_without_receipt(page):
        # Never manufacture approval, or overwrite a malformed receipt.
        return None
    return props


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--limit", type=int, default=300)
    p.add_argument("--page-id", default="")
    p.add_argument("--backup-dir", default="/opt/unlxck/outreach-worker/state")
    args = p.parse_args()
    if not 1 <= args.limit <= 1000:
        p.error("--limit must be 1 to 1000")
    settings = Settings.from_env(require_openai=False)
    if args.apply and settings.dry_run:
        raise RuntimeError("DRY_RUN=true: refusing changes")
    session = NotionSession()
    stage_id = _resolve_stage_property_id(session, settings)
    if args.page_id:
        pages = [_retrieve_target_page(session, settings, args.page_id)]
    else:
        pages = _query_stage_filter(session, settings, stage_property_id=stage_id,
                                    select_filter={"equals": "Ready to Send"},
                                    limit=1000, sort_direction="descending")
    done = skipped = 0
    backup = None
    try:
        for original in pages:
            if done >= args.limit:
                break
            planned = proposal(original, stage_id)
            if planned is None:
                skipped += 1
                continue
            label = _plain_text(original["properties"].get("Candidate")) or original["id"]
            if not args.apply:
                print(f"PREVIEW {label}: {replacement(dm(original))}")
                done += 1
                continue
            current = _retrieve_target_page(session, settings, original["id"])
            # Never overwrite a concurrent edit or any change to qualification/metadata.
            if (original.get("last_edited_time") != current.get("last_edited_time")
                    or original["properties"] != current["properties"]
                    or planned != proposal(current, stage_id)):
                print(f"SKIP {label}: changed since scan")
                skipped += 1
                continue
            if backup is None:
                directory = Path(args.backup_dir)
                directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                filename = "dm-greeting-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".jsonl"
                fd = os.open(directory / filename, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                backup = os.fdopen(fd, "w", encoding="utf-8")
                print("Backup:", directory / filename)
            backup.write(json.dumps({"page_id": current["id"], "before": current["properties"],
                                     "last_edited_time": current.get("last_edited_time")}, ensure_ascii=False) + "\n")
            backup.flush()
            os.fsync(backup.fileno())
            _patch_page(session, settings, current["id"], planned)
            after = _retrieve_target_page(session, settings, current["id"])
            problem = (
                _stage_value(after, stage_id) != "Ready to Send"
                or dm(after) != replacement(dm(original))
                or after["properties"].get(QUALIFIED_AT) != current["properties"].get(QUALIFIED_AT)
                or after["properties"].get("Priority Score") != current["properties"].get("Priority Score")
                or after["properties"].get("Outreach Approach") != current["properties"].get("Outreach Approach")
                or (receipt(current) is not None and (
                    not receipt(after) or receipt(after)["fingerprint"] != fingerprint(after)
                    or not approval_valid(after, datetime.now(timezone.utc), unsent=True)))
                or (receipt(current) is None and _plain_text(after["properties"].get(RECEIPT)).strip())
            )
            if problem:
                # Restore both fields together before the reconciler can see
                # a mismatched approved message. Stop on first failed verification.
                rollback = {
                    "Draft DM": {"rich_text": _rich_text_value(dm(current))},
                    RECEIPT: {"rich_text": _rich_text_value(
                        _plain_text(current["properties"].get(RECEIPT)))},
                }
                _patch_page(session, settings, current["id"], rollback)
                restored = _retrieve_target_page(session, settings, current["id"])
                if (dm(restored) != dm(current)
                        or _plain_text(restored["properties"].get(RECEIPT)) !=
                        _plain_text(current["properties"].get(RECEIPT))
                        or (receipt(current) is not None and
                            not approval_valid(restored, datetime.now(timezone.utc), unsent=True))):
                    raise RuntimeError(f"CRITICAL: rollback verification failed for {label}")
                raise RuntimeError(f"STOP: post-write check failed for {label}; original draft and receipt restored")
            print(f"UPDATED {label}")
            done += 1
    finally:
        if backup:
            backup.close()
    print(f"Greeting replacement complete: {'applied' if args.apply else 'previewed'}={done}, skipped={skipped}")


if __name__ == "__main__":
    main()
