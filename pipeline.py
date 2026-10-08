from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

import requests
from openai import OpenAI

from daily_counter import NotionSession, apply_properties, ensure_schema, sync_counter
from qualification import (
    RECEIPT, QUALIFIED_AT, approval_valid, fingerprint, new_receipt, receipt,
    reconcile, receipt_properties, research_fingerprint, today_bounds,
    grandfathered_without_receipt,
)

from core import (
    Settings,
    fight_date_issue,
    _notion_headers,
    _rich_text_value,
    candidate_from_page,
    preflight_reason,
    qualify_and_draft,
    verified_profile_reason,
)

AI_QUEUE = "AI Queue"
NEEDS_RESEARCH = "Needs Research"
READY_TO_SEND = "Ready to Send"
REJECTED = "Rejected"
DEFAULT_SPORT = "Boxing"
STAGE_PROPERTY_LABELS = ("Stage", "Stage (AI Fills First)")
DAILY_TARGET = 50
DAILY_COUNTER_PAGE_ID = os.getenv(
    "NOTION_DAILY_COUNTER_PAGE_ID",
    "3f3d6e71-8d27-8165-b1a2-e5d137d1c172",
)


def _normalize_notion_id(value: str | None) -> str:
    return (value or "").replace("-", "").lower()


def _resolve_stage_property_id(
    session: requests.Session,
    settings: Settings,
) -> str:
    """Resolve the live Stage property ID so labels can change without breaking automation."""
    response = session.get(
        f"https://api.notion.com/v1/data_sources/{settings.notion_data_source_id}",
        headers=_notion_headers(settings.notion_api_key),
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Notion data-source lookup failed ({response.status_code}): {response.text}"
        )

    properties = response.json().get("properties", {})

    for wanted in STAGE_PROPERTY_LABELS:
        for key, metadata in properties.items():
            name = metadata.get("name", key)
            if key == wanted or name == wanted:
                property_id = metadata.get("id")
                if property_id:
                    return property_id

    stage_matches = [
        metadata.get("id")
        for key, metadata in properties.items()
        if metadata.get("name", key).lower().startswith("stage") and metadata.get("id")
    ]
    if len(stage_matches) == 1:
        return stage_matches[0]

    available = sorted(metadata.get("name", key) for key, metadata in properties.items())
    raise RuntimeError(
        "Could not resolve the Notion Stage property. "
        f"Visible properties: {available}"
    )


def _query_stage_filter(
    session: requests.Session,
    settings: Settings,
    *,
    stage_property_id: str,
    select_filter: dict[str, Any],
    limit: int,
    sort_direction: str = "ascending",
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    url = f"https://api.notion.com/v1/data_sources/{settings.notion_data_source_id}/query"
    results: list[dict[str, Any]] = []
    start_cursor: str | None = None

    while len(results) < limit:
        payload: dict[str, Any] = {
            "filter": {"property": stage_property_id, "select": select_filter},
            "sorts": [{"timestamp": "created_time", "direction": sort_direction}],
            "page_size": min(100, limit - len(results)),
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor

        response = session.post(
            url,
            headers=_notion_headers(settings.notion_api_key),
            json=payload,
            timeout=30,
        )
        if not response.ok:
            raise RuntimeError(
                f"Notion queue query failed ({response.status_code}): {response.text}"
            )

        body = response.json()
        results.extend(body.get("results", []))

        if not body.get("has_more"):
            break
        start_cursor = body.get("next_cursor")
        if not start_cursor:
            break

    return results[:limit]


def _today_utc_bounds(now: datetime | None = None) -> tuple[datetime, datetime]:
    return today_bounds(now or datetime.now(timezone.utc))


def _update_daily_progress_counter(session, settings, *, now=None, stage_property_id=None):
    stage_property_id = stage_property_id or _resolve_stage_property_id(session, settings)
    return sync_counter(session, settings, stage_property_id, DAILY_COUNTER_PAGE_ID, now=now)


def _ready_row_needs_repair(page: dict[str, Any], *, now: datetime | None = None) -> bool:
    """A complete-looking draft is unsafe without a current, active AI approval."""
    if grandfathered_without_receipt(page):
        return False
    return not approval_valid(page, now or datetime.now(timezone.utc), unsent=True)


def query_ai_queue(
    session: requests.Session,
    settings: Settings,
    stage_property_id: str | None = None,
) -> list[dict[str, Any]]:
    """Pull explicit AI rechecks first, then new blank-stage prospects."""
    max_results = settings.max_candidates_per_run
    stage_property_id = stage_property_id or _resolve_stage_property_id(session, settings)

    recent_ready = _query_stage_filter(
        session,
        settings,
        stage_property_id=stage_property_id,
        select_filter={"equals": READY_TO_SEND},
        limit=max_results,
        sort_direction="descending",
    )
    repairs = [page for page in recent_ready if _ready_row_needs_repair(page)]

    remaining = max_results - len(repairs)
    rechecks = _query_stage_filter(
        session,
        settings,
        stage_property_id=stage_property_id,
        select_filter={"equals": AI_QUEUE},
        limit=remaining,
    )

    remaining -= len(rechecks)
    new_rows = _query_stage_filter(
        session,
        settings,
        stage_property_id=stage_property_id,
        select_filter={"is_empty": True},
        limit=remaining,
    )

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for page in [*repairs, *rechecks, *new_rows]:
        page_id = page.get("id")
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)
        merged.append(page)

    return merged[:max_results]


def _retrieve_target_page(
    session: requests.Session,
    settings: Settings,
    page_id: str,
) -> dict[str, Any]:
    response = session.get(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=_notion_headers(settings.notion_api_key),
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Notion target-page lookup failed ({response.status_code}): {response.text}"
        )

    page = response.json()
    parent = page.get("parent", {})
    parent_id = parent.get("data_source_id") or parent.get("database_id") or ""
    if _normalize_notion_id(parent_id) != _normalize_notion_id(settings.notion_data_source_id):
        raise RuntimeError("Target page does not belong to the UNLXCK Beta Candidate Pipeline.")
    return page


def _stage_value(page: dict[str, Any], stage_property_id: str) -> str:
    for prop in page.get("properties", {}).values():
        if prop.get("id") != stage_property_id:
            continue
        if prop.get("type") != "select" or not prop.get("select"):
            return ""
        return prop["select"].get("name", "")
    return ""


def _target_page_if_requested(
    session: requests.Session,
    settings: Settings,
    stage_property_id: str,
) -> list[dict[str, Any]] | None:
    """Return one webhook/manual target page, or None when normal queue polling is required."""
    page_id = os.getenv("TARGET_PAGE_ID", "").strip()
    if not page_id:
        return None

    page = _retrieve_target_page(session, settings, page_id)
    stage = _stage_value(page, stage_property_id)
    if stage not in {"", AI_QUEUE}:
        print(f"Target page skipped because Stage is already {stage!r}.")
        return []
    return [page]


def stage_from_ai(result: dict[str, Any]) -> str:
    if result.get("evidence_sufficient") is not True:
        return NEEDS_RESEARCH
    if result.get("eligible") is not True:
        return REJECTED
    return READY_TO_SEND


def _is_empty_row(candidate: dict[str, str]) -> bool:
    return not any(
        (
            candidate.get("candidate", "").strip(),
            candidate.get("verified_profile_url", "").strip(),
            candidate.get("instagram_handle", "").strip(),
            candidate.get("personalised_dm_angle", "").strip(),
        )
    )


def _entry_complete(candidate: dict[str, str]) -> bool:
    """Run the verification gate once the human has supplied a candidate and evidence note."""
    return all(
        candidate.get(field, "").strip()
        for field in ("candidate", "personalised_dm_angle")
    )


def _patch_page(
    session: requests.Session,
    settings: Settings,
    page_id: str,
    properties: dict[str, Any],
) -> None:
    if settings.dry_run:
        print(json.dumps({"dry_run": True, "page_id": page_id, "properties": properties}))
        return

    response = session.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=_notion_headers(settings.notion_api_key),
        json={"properties": properties},
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(
            f"Notion page update failed ({response.status_code}): {response.text}"
        )


def _mark_terminal(
    session: requests.Session,
    settings: Settings,
    candidate: dict[str, str],
    *,
    stage_property_id: str,
    stage: str,
    reason: str,
) -> None:
    if not settings.dry_run:
        current = _retrieve_target_page(session, settings, candidate["page_id"])
        if (research_fingerprint(candidate_from_page(current)) != research_fingerprint(candidate)
                or _stage_value(current, stage_property_id) not in {"", AI_QUEUE, READY_TO_SEND}):
            raise RuntimeError("Prospect changed during verification; retry from current Notion data")
    _patch_page(
        session,
        settings,
        candidate["page_id"],
        {
            stage_property_id: {"select": {"name": stage}},
            "Priority Score": {"number": 0},
            "AI Qualification Reason": {"rich_text": _rich_text_value(reason)},
            "Draft DM": {"rich_text": []},
            RECEIPT: {"rich_text": []},
            QUALIFIED_AT: {"date": None},
        },
    )


def update_ai_result(
    session: requests.Session,
    settings: Settings,
    candidate: dict[str, str],
    result: dict[str, Any],
    *,
    stage_property_id: str,
) -> str:
    stage = stage_from_ai(result)
    properties: dict[str, Any] = {
        stage_property_id: {"select": {"name": stage}},
        "Priority Score": {"number": result["priority_score"]},
        "AI Qualification Reason": {
            "rich_text": _rich_text_value(result["qualification_reason"])
        },
        "Draft DM": {
            "rich_text": _rich_text_value(result["draft_dm"] if stage == READY_TO_SEND else "")
        },
    }
    if stage == READY_TO_SEND:
        properties["Outreach Approach"] = {
            "select": {"name": result["outreach_approach"]}
        }

    # Re-read after the AI call: do not overwrite a human stage/evidence edit.
    current = _retrieve_target_page(session, settings, candidate["page_id"])
    if not settings.dry_run and (
        research_fingerprint(candidate_from_page(current)) != research_fingerprint(candidate)
        or _stage_value(current, stage_property_id) not in {"", AI_QUEUE, READY_TO_SEND}
    ):
        raise RuntimeError("Prospect changed during AI qualification; retry from current Notion data")
    if stage == READY_TO_SEND:
        if settings.dry_run:
            current = apply_properties(current, {
                "Instagram Handle": {"rich_text": _rich_text_value(candidate["instagram_handle"])},
                "Sport": {"select": {"name": candidate["sport"]}},
            })
        proposed = apply_properties(current, properties)
        previous = receipt(current)
        at = datetime.now(timezone.utc).isoformat()
        if (previous and previous["active"] and _stage_value(current, stage_property_id) == READY_TO_SEND
                and previous.get("fingerprint") == fingerprint(proposed)):
            at = previous.get("at")
        legacy = bool(previous and previous["legacy"] and at is None)
        properties.update(receipt_properties(new_receipt(proposed, at, legacy=legacy)))
    else:
        properties.update({RECEIPT: {"rich_text": []}, QUALIFIED_AT: {"date": None}})
    _patch_page(session, settings, candidate["page_id"], properties)
    return stage


def run_outreach() -> int:
    settings = Settings.from_env(require_openai=os.getenv("COUNTER_ONLY", "").lower() != "true")
    session = NotionSession()

    stage_property_id = _resolve_stage_property_id(session, settings)
    missing_schema = ensure_schema(session, settings)
    if missing_schema and not settings.dry_run:
        raise RuntimeError("Run migrate_counter.py --apply-schema before running this worker")
    if missing_schema and settings.dry_run:
        print("Dry run: schema migration pending; qualification preview only")

    counter_only = os.getenv("COUNTER_ONLY", "").lower() == "true"
    external_counter = (
        os.getenv("OUTREACH_EXTERNAL_COUNTER", "").lower() == "true"
        or bool(missing_schema and settings.dry_run)
    )
    if counter_only:
        try:
            _update_daily_progress_counter(session, settings, stage_property_id=stage_property_id)
            return 0
        except Exception as exc:
            print(f"WARNING: daily progress counter update failed: {exc}", file=sys.stderr)
            return 1
    client = OpenAI(api_key=settings.openai_api_key)
    targeted_pages = _target_page_if_requested(session, settings, stage_property_id)
    if targeted_pages is None:
        pages = query_ai_queue(session, settings, stage_property_id)
        print(f"New / AI Queue prospects pulled from Notion: {len(pages)}")
    else:
        pages = targeted_pages
        print(f"Targeted prospects pulled from Notion: {len(pages)}")

    processed = 0
    counter_failed = False
    skipped = 0
    failed = 0

    for page in pages:
        candidate = candidate_from_page(page)
        label = candidate["candidate"] or candidate["instagram_handle"] or candidate["page_id"]

        if _stage_value(page, stage_property_id) == READY_TO_SEND and _ready_row_needs_repair(page):
            try:
                current = _retrieve_target_page(session, settings, candidate["page_id"])
                changes = reconcile(current, stage_property_id, datetime.now(timezone.utc))
                if _stage_value(current, stage_property_id) == READY_TO_SEND and changes:
                    _patch_page(session, settings, candidate["page_id"], changes)
                    processed += 1
                    print(f"Needs Research: {label} — approval requires an explicit AI Queue recheck")
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                print(f"ERROR: {label}: {exc}", file=sys.stderr)
            continue

        if _is_empty_row(candidate):
            skipped += 1
            print(f"Skipped empty row: {candidate['page_id']}")
            continue

        if not _entry_complete(candidate):
            if _stage_value(page, stage_property_id) == READY_TO_SEND:
                reason = (
                    "Needs research: Candidate and Personalised DM Angle must be complete "
                    "before this prospect can be Ready to Send."
                )
                _mark_terminal(
                    session,
                    settings,
                    candidate,
                    stage_property_id=stage_property_id,
                    stage=NEEDS_RESEARCH,
                    reason=reason,
                )
                print(f"{NEEDS_RESEARCH}: {label} — {reason}")
                processed += 1
            else:
                skipped += 1
                print(f"Skipped incomplete entry: {label}")
            continue

        try:
            timing_issue = fight_date_issue(candidate)
            if timing_issue:
                stage, reason = timing_issue
                _mark_terminal(
                    session, settings, candidate,
                    stage_property_id=stage_property_id, stage=stage, reason=reason,
                )
                print(f"{stage}: {label} — {reason}")
                processed += 1
                continue

            verified_handle, verification_problem = verified_profile_reason(candidate)
            if verification_problem:
                _mark_terminal(
                    session,
                    settings,
                    candidate,
                    stage_property_id=stage_property_id,
                    stage=NEEDS_RESEARCH,
                    reason=verification_problem,
                )
                print(f"{NEEDS_RESEARCH}: {label} — {verification_problem}")
                processed += 1
                continue

            current_handle = candidate["instagram_handle"].strip().lstrip("@")
            if current_handle != verified_handle:
                candidate["instagram_handle"] = verified_handle or ""
                _patch_page(
                    session,
                    settings,
                    candidate["page_id"],
                    {
                        "Instagram Handle": {
                            "rich_text": _rich_text_value(candidate["instagram_handle"])
                        }
                    },
                )
                print(
                    f"Corrected Instagram handle for {label}: "
                    f"{current_handle or '<blank>'} -> {verified_handle}"
                )

            if not candidate["sport"].strip():
                candidate["sport"] = DEFAULT_SPORT
                _patch_page(
                    session,
                    settings,
                    candidate["page_id"],
                    {"Sport": {"select": {"name": DEFAULT_SPORT}}},
                )

            if candidate["sport"] != DEFAULT_SPORT:
                reason = "Current private beta outreach is boxing-only."
                _mark_terminal(
                    session,
                    settings,
                    candidate,
                    stage_property_id=stage_property_id,
                    stage=REJECTED,
                    reason=reason,
                )
                print(f"{REJECTED}: {label} — {reason}")
                processed += 1
                continue

            missing = preflight_reason(candidate)
            if missing:
                _mark_terminal(
                    session,
                    settings,
                    candidate,
                    stage_property_id=stage_property_id,
                    stage=NEEDS_RESEARCH,
                    reason=missing,
                )
                print(f"{NEEDS_RESEARCH}: {label} — {missing}")
                processed += 1
                continue

            result = qualify_and_draft(client, settings, candidate)
            timing_issue = fight_date_issue(
                candidate, draft=result["draft_dm"], approach=result["outreach_approach"],
            )
            if timing_issue:
                stage, reason = timing_issue
                _mark_terminal(
                    session, settings, candidate,
                    stage_property_id=stage_property_id, stage=stage, reason=reason,
                )
                print(f"{stage}: {label} — {reason}")
                processed += 1
                continue
            stage = update_ai_result(
                session,
                settings,
                candidate,
                result,
                stage_property_id=stage_property_id,
            )
            print(f"{stage}: {label} — score {result['priority_score']}")
            processed += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR: {label}: {exc}", file=sys.stderr)

    if not external_counter:
        try:
            _update_daily_progress_counter(session, settings, stage_property_id=stage_property_id)
        except Exception as exc:
            counter_failed = True
            print(f"WARNING: daily progress counter update failed: {exc}", file=sys.stderr)

    print(
        f"Outreach run complete. Processed={processed}, Skipped={skipped}, Failed={failed}"
    )
    return 1 if failed or counter_failed else 0


if __name__ == "__main__":
    raise SystemExit(run_outreach())
