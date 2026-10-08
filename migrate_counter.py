"""Explicit, additive migration. Dry-run is the default; no creation-date guessing."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from core import Settings
from daily_counter import NotionSession, api, ensure_schema, query_all
from pipeline import DAILY_COUNTER_PAGE_ID, _resolve_stage_property_id
from qualification import (COMPLETED_STAGES, fields_valid, fingerprint, new_receipt,
                           receipt, receipt_properties, stage, utc_time)


def backfill_properties(page, approval, cutoff):
    """Accept explicit audited approval evidence, never a stage/score heuristic."""
    if (approval.get("fingerprint") != fingerprint(page)
            or approval.get("eligible") is not True
            or approval.get("evidence_sufficient") is not True
            or not isinstance(approval.get("evidence_reference"), str)
            or not approval["evidence_reference"].strip()):
        raise ValueError(f"Missing audited approval or prospect changed: {page['id']}")
    at = approval.get("qualified_at")
    if at is not None and utc_time(at) >= cutoff:
        raise ValueError("Historical backfill timestamp must be before the migration cutoff")
    proof = new_receipt(page, at, legacy=at is None)
    return receipt_properties(proof)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply-schema", action="store_true")
    parser.add_argument("--export", type=Path, help="Export fingerprint inventory for approval audit (no writes)")
    parser.add_argument("--manifest", type=Path, help="Reviewed approval manifest, with cutoff and pages")
    parser.add_argument("--apply", action="store_true", help="Apply reviewed backfill; default is preview")
    args = parser.parse_args()
    settings = Settings.from_env(require_openai=False)
    session = NotionSession()
    print("Missing metadata properties:", ensure_schema(session, settings, apply=args.apply_schema))
    if not args.export and not args.manifest:
        return
    stage_id = _resolve_stage_property_id(session, settings)
    pages = query_all(session, settings)
    pages = [p for p in pages if p["id"].replace("-", "") != DAILY_COUNTER_PAGE_ID.replace("-", "")]
    if args.export:
        inventory = {"cutoff": datetime.now(timezone.utc).isoformat(), "pages": {}}
        for page in pages:
            if stage(page, stage_id) in COMPLETED_STAGES and fields_valid(page) and not receipt(page):
                inventory["pages"][page["id"]] = {
                    "fingerprint": fingerprint(page), "eligible": False, "evidence_sufficient": False,
                    "evidence_reference": "", "qualified_at": None,
                }
        args.export.write_text(json.dumps(inventory, indent=2))
        args.export.chmod(0o600)
        print(f"Exported {len(inventory['pages'])} potential legacy rows; none auto-approved")
    if args.manifest:
        if ensure_schema(session, settings):
            raise RuntimeError("Apply schema before backfilling")
        manifest = json.loads(args.manifest.read_text())
        cutoff = utc_time(manifest["cutoff"])
        if cutoff > datetime.now(timezone.utc):
            raise ValueError("Migration cutoff cannot be in the future")
        by_id = {p["id"]: p for p in pages}
        # Validate the entire batch before performing a single write.
        changes = []
        for id_, approval in manifest["pages"].items():
            page = by_id[id_]
            if receipt(page):
                continue  # Safe repeated migration; do not erase newer qualification.
            if stage(page, stage_id) not in COMPLETED_STAGES:
                raise ValueError(f"Stage has regressed since inventory: {id_}")
            changes.append((id_, backfill_properties(page, approval, cutoff)))
        for id_, properties in changes:
            # Recheck immediately before each write; restart safely after partial failure.
            current = api(session, settings, "get", f"pages/{id_}")
            if receipt(current):
                continue
            if stage(current, stage_id) not in COMPLETED_STAGES or current.get("archived") or current.get("in_trash"):
                raise ValueError(f"Prospect no longer eligible for migration: {id_}")
            properties = backfill_properties(current, manifest["pages"][id_], cutoff)
            if args.apply and not settings.dry_run:
                api(session, settings, "patch", f"pages/{id_}", json={"properties": properties})
        print(f"{'Applied' if args.apply and not settings.dry_run else 'Previewed'} {len(changes)} historical approvals")


if __name__ == "__main__":
    main()
