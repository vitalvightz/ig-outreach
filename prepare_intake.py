from __future__ import annotations

import os
from typing import Any

import requests

NOTION_VERSION = "2026-03-11"
DEFAULT_DATA_SOURCE_ID = "08d8b476-129a-42b0-b980-102b08ce4bd8"
DEFAULT_SPORT = "Boxing"


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _select_name(prop: dict[str, Any] | None) -> str:
    if not prop or prop.get("type") != "select" or not prop.get("select"):
        return ""
    return prop["select"].get("name", "")


def planned_updates(page: dict[str, Any]) -> dict[str, Any]:
    """Return only the defaults needed for a newly entered beta prospect."""
    properties = page.get("properties", {})
    stage = _select_name(properties.get("Stage"))
    sport = _select_name(properties.get("Sport"))

    updates: dict[str, Any] = {}
    if not stage:
        updates["Stage"] = {"select": {"name": "Found"}}
    if not sport and (not stage or stage == "Found"):
        updates["Sport"] = {"select": {"name": DEFAULT_SPORT}}
    return updates


def _query_pages(
    session: requests.Session,
    *,
    api_key: str,
    data_source_id: str,
    filter_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    url = f"https://api.notion.com/v1/data_sources/{data_source_id}/query"
    pages: list[dict[str, Any]] = []
    cursor: str | None = None

    while True:
        payload: dict[str, Any] = {"filter": filter_payload, "page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor

        response = session.post(
            url,
            headers=_headers(api_key),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        pages.extend(body.get("results", []))

        if not body.get("has_more"):
            break
        cursor = body.get("next_cursor")
        if not cursor:
            break

    return pages


def prepare_intake() -> int:
    api_key = _required_env("NOTION_API_KEY")
    data_source_id = os.getenv("NOTION_DATA_SOURCE_ID", DEFAULT_DATA_SOURCE_ID)
    dry_run = os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
    session = requests.Session()

    filters = [
        {"property": "Stage", "select": {"is_empty": True}},
        {
            "and": [
                {"property": "Stage", "select": {"equals": "Found"}},
                {"property": "Sport", "select": {"is_empty": True}},
            ]
        },
    ]

    seen: set[str] = set()
    updated = 0

    for filter_payload in filters:
        for page in _query_pages(
            session,
            api_key=api_key,
            data_source_id=data_source_id,
            filter_payload=filter_payload,
        ):
            page_id = page["id"]
            if page_id in seen:
                continue
            seen.add(page_id)

            updates = planned_updates(page)
            if not updates:
                continue

            if dry_run:
                print(f"DRY RUN intake defaults: {page_id} -> {list(updates)}")
                continue

            response = session.patch(
                f"https://api.notion.com/v1/pages/{page_id}",
                headers=_headers(api_key),
                json={"properties": updates},
                timeout=30,
            )
            response.raise_for_status()
            updated += 1

    print(f"Intake preparation complete. Updated={updated}, DryRun={dry_run}")
    return 0


if __name__ == "__main__":
    raise SystemExit(prepare_intake())
