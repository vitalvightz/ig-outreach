"""Incremental Notion reconciliation with transactional, durable checkpoints."""
from __future__ import annotations

import copy
from contextlib import closing
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from core import _notion_headers, candidate_from_page
from qualification import (QUALIFIED_AT, RECEIPT, count_today,
                           profile, receipt, reconcile, today_bounds, utc_time)


class NotionSession(requests.Session):
    """Pace Notion requests and retry transient failures, including Retry-After."""
    def __init__(self):
        super().__init__()
        self._last_request = 0.0

    def request(self, method, url, **kwargs):
        for attempt in range(5):
            time.sleep(max(0, .35 - (time.monotonic() - self._last_request)))
            self._last_request = time.monotonic()
            try:
                response = super().request(method, url, **kwargs)
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 4:
                    raise
            else:
                if response.status_code not in {429, 500, 502, 503, 504} or attempt == 4:
                    return response
                try:
                    delay = float(response.headers.get("Retry-After", 2 ** attempt))
                except ValueError:
                    delay = 2 ** attempt
                if delay > 60:
                    response.raise_for_status()  # Defer to the next scheduler pass.
                time.sleep(max(0, delay))
                continue
            time.sleep(2 ** attempt)
        raise RuntimeError("Notion retry budget exhausted")


def api(session, settings, method, path, **kwargs):
    response = getattr(session, method)(f"https://api.notion.com/v1/{path}",
                                       headers=_notion_headers(settings.notion_api_key),
                                       timeout=30, **kwargs)
    response.raise_for_status()
    return response.json()


def query_all(session, settings, filter_=None):
    pages, cursor, seen = [], None, set()
    while True:
        payload = {"page_size": 100, "sorts": [{"timestamp": "created_time", "direction": "ascending"}]}
        if filter_:
            payload["filter"] = filter_
        if cursor:
            payload["start_cursor"] = cursor
        body = api(session, settings, "post", f"data_sources/{settings.notion_data_source_id}/query", json=payload)
        if not isinstance(body.get("results"), list) or type(body.get("has_more")) is not bool:
            raise RuntimeError("Incomplete Notion query response; counter left unchanged")
        pages.extend(body["results"])
        if not body["has_more"]:
            return pages
        cursor = body.get("next_cursor")
        if not cursor or cursor in seen:
            raise RuntimeError("Invalid Notion pagination; counter left unchanged")
        seen.add(cursor)


def apply_properties(page, properties):
    """Build the same parsed shape as a Notion response, for committed metadata."""
    page = copy.deepcopy(page)
    for name, value in properties.items():
        prop = copy.deepcopy(value)
        prop["type"] = next(iter(value))
        if "rich_text" in prop:
            for item in prop["rich_text"]:
                item["plain_text"] = item["text"]["content"]
        key = next((key for key, old in page["properties"].items()
                    if key == name or old.get("id") == name), name)
        if "id" in page["properties"].get(key, {}):
            prop["id"] = page["properties"][key]["id"]
        page["properties"][key] = prop
    return page


def ensure_schema(session, settings, *, apply=False):
    """Add only our two metadata fields; never touch formulas or views."""
    path = f"data_sources/{settings.notion_data_source_id}"
    schema = api(session, settings, "get", path)["properties"]
    additions = {}
    for name, kind in ((QUALIFIED_AT, "date"), (RECEIPT, "rich_text")):
        if name in schema:
            if schema[name].get("type") != kind:
                raise RuntimeError(f"{name} exists with the wrong type; refusing to replace it")
        else:
            additions[name] = {kind: {}}
    if additions and apply and not settings.dry_run:
        api(session, settings, "patch", path, json={"properties": additions})
    return additions


def sync_counter(session, settings, stage_id, counter_id, *, now=None, state_path=None):
    now = now or datetime.now(timezone.utc)
    state_path = state_path or os.getenv("OUTREACH_COUNTER_STATE", "var/daily-counter.sqlite3")
    path = Path(state_path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, timeout=1)) as db, db:
        path.chmod(0o600)
        db.execute("CREATE TABLE IF NOT EXISTS pages (id TEXT PRIMARY KEY, body TEXT NOT NULL)")
        db.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.commit()
        db.execute("BEGIN IMMEDIATE")  # Another local pass must not publish an older snapshot.
        source = db.execute("SELECT value FROM metadata WHERE key='source'").fetchone()
        if source and source[0] != settings.notion_data_source_id:
            raise RuntimeError("Counter state belongs to a different Notion data source")
        if ensure_schema(session, settings):
            raise RuntimeError("Run migrate_counter.py --apply-schema before enabling the counter")
        checkpoint = db.execute("SELECT value FROM metadata WHERE key='checkpoint'").fetchone()
        cached = {id_: json.loads(body) for id_, body in db.execute("SELECT id, body FROM pages")}
        filter_ = None
        if checkpoint:
            since = utc_time(checkpoint[0]) - timedelta(minutes=5)
            filter_ = {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since.isoformat()}}
        # All pages must be fetched successfully before any metadata or UI writes.
        changed_ids = set()
        for page in query_all(session, settings, filter_):
            if page["id"].replace("-", "") != counter_id.replace("-", ""):
                cached[page["id"]] = page
                changed_ids.add(page["id"])

        start, end = today_bounds(now)
        # A complete date query is authoritative membership, including archive/delete
        # removal. Refreshing up to 50 contributors takes one paginated query rather
        # than 50 page retrievals. Any failed/incomplete query aborts publication.
        live_today = query_all(session, settings, {"and": [
            {"property": QUALIFIED_AT, "date": {"on_or_after": start.isoformat()}},
            {"property": QUALIFIED_AT, "date": {"before": end.isoformat()}},
        ]})
        live_ids = {p["id"] for p in live_today}
        todays_handles = set()
        for id_, page in list(cached.items()):
            proof = receipt(page)
            if proof and proof.get("at") and start <= utc_time(proof["at"]) < end:
                todays_handles.add(profile(page))
                if id_ not in live_ids and id_ not in changed_ids:
                    cached[id_] = dict(page, archived=True)
        for page in live_today:
            cached[page["id"]] = page
            todays_handles.add(profile(page))

        # Historical duplicates also own credit. Check only owners of profiles
        # relevant today, so archived historical duplicates cannot suppress credit.
        owners = {id_: page for id_, page in cached.items()
                  if receipt(page) and profile(page) in todays_handles and id_ not in live_ids}
        handles = sorted({candidate_from_page(p)["instagram_handle"] for p in owners.values()})
        found_ids = set()
        for offset in range(0, len(handles), 50):
            matches = query_all(session, settings, {"or": [
                {"property": "Instagram Handle", "rich_text": {"equals": handle}}
                for handle in handles[offset:offset+50]
            ]})
            for page in matches:
                found_ids.add(page["id"])
                cached[page["id"]] = page
        for id_, page in owners.items():
            if id_ not in found_ids:
                cached[id_] = dict(page, archived=True)
        for id_, page in list(cached.items()):
            properties = reconcile(page, stage_id, now)
            if stage_id in properties and not settings.dry_run:
                # A stale Ready snapshot must never regress a newly Contacted row.
                page = api(session, settings, "get", f"pages/{id_}")
                cached[id_] = page
                properties = reconcile(page, stage_id, now)
            if properties:
                if not settings.dry_run and not page.get("archived") and not page.get("in_trash"):
                    api(session, settings, "patch", f"pages/{id_}", json={"properties": properties})
                cached[id_] = apply_properties(page, properties)
        count = count_today(list(cached.values()), stage_id, now)
        if settings.dry_run:
            db.rollback()
            print(f"Dry-run daily progress: {count}/50 (no checkpoint or Notion writes)")
            return count
        api(session, settings, "patch", f"pages/{counter_id}", json={"properties": {
            "Candidate": {"title": [{"type": "text", "text": {"content": f"{count} / 50 complete"}}]},
            "Priority Score": {"number": count},
        }})
        db.executemany("INSERT OR REPLACE INTO pages VALUES (?, ?)",
                       [(id_, json.dumps(page)) for id_, page in cached.items()])
        db.executemany("INSERT OR REPLACE INTO metadata VALUES (?, ?)",
                       [("checkpoint", now.isoformat()), ("source", settings.notion_data_source_id)])
        db.commit()
        print(f"Daily progress: {count}/50")
        return count
