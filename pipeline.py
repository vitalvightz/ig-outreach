from __future__ import annotations

import json
import sys
from typing import Any

import requests
from openai import OpenAI

from core import (
    Settings,
    _notion_headers,
    _rich_text_value,
    candidate_from_page,
    preflight_reason,
    qualify_and_draft,
)

AI_QUEUE = "AI Queue"
NEEDS_RESEARCH = "Needs Research"
READY_TO_SEND = "Ready to Send"
REJECTED = "Rejected"
DEFAULT_SPORT = "Boxing"
STAGE_PROPERTY_LABELS = ("Stage", "Stage (AI Fills First)")


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

    # Last-resort compatibility for a future explanatory Stage label.
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
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []

    url = f"https://api.notion.com/v1/data_sources/{settings.notion_data_source_id}/query"
    results: list[dict[str, Any]] = []
    start_cursor: str | None = None

    while len(results) < limit:
        payload: dict[str, Any] = {
            "filter": {"property": stage_property_id, "select": select_filter},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
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


def query_ai_queue(
    session: requests.Session,
    settings: Settings,
    stage_property_id: str | None = None,
) -> list[dict[str, Any]]:
    """Pull explicit AI rechecks first, then new blank-stage prospects."""
    max_results = settings.max_candidates_per_run
    stage_property_id = stage_property_id or _resolve_stage_property_id(session, settings)

    rechecks = _query_stage_filter(
        session,
        settings,
        stage_property_id=stage_property_id,
        select_filter={"equals": AI_QUEUE},
        limit=max_results,
    )

    remaining = max_results - len(rechecks)
    new_rows = _query_stage_filter(
        session,
        settings,
        stage_property_id=stage_property_id,
        select_filter={"is_empty": True},
        limit=remaining,
    )

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for page in [*rechecks, *new_rows]:
        page_id = page.get("id")
        if not page_id or page_id in seen:
            continue
        seen.add(page_id)
        merged.append(page)

    return merged[:max_results]


def stage_from_ai(result: dict[str, Any]) -> str:
    if not result["evidence_sufficient"]:
        return NEEDS_RESEARCH
    if not result["eligible"]:
        return REJECTED
    return READY_TO_SEND


def _is_empty_row(candidate: dict[str, str]) -> bool:
    return not any(
        (
            candidate.get("candidate", "").strip(),
            candidate.get("instagram_handle", "").strip(),
            candidate.get("personalised_dm_angle", "").strip(),
        )
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
    _patch_page(
        session,
        settings,
        candidate["page_id"],
        {
            stage_property_id: {"select": {"name": stage}},
            "Priority Score": {"number": 0},
            "AI Qualification Reason": {"rich_text": _rich_text_value(reason)},
            "Draft DM": {"rich_text": []},
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

    _patch_page(session, settings, candidate["page_id"], properties)
    return stage


def run_outreach() -> int:
    settings = Settings.from_env()
    session = requests.Session()
    client = OpenAI(api_key=settings.openai_api_key)

    stage_property_id = _resolve_stage_property_id(session, settings)
    pages = query_ai_queue(session, settings, stage_property_id)
    print(f"New / AI Queue prospects pulled from Notion: {len(pages)}")

    processed = 0
    skipped = 0
    failed = 0

    for page in pages:
        candidate = candidate_from_page(page)
        label = candidate["candidate"] or candidate["instagram_handle"] or candidate["page_id"]

        if _is_empty_row(candidate):
            skipped += 1
            print(f"Skipped empty row: {candidate['page_id']}")
            continue

        try:
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

    print(
        f"Outreach run complete. Processed={processed}, Skipped={skipped}, Failed={failed}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_outreach())
