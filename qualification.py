"""Pure qualification state and London-day counting; no network or storage."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any

from core import (_plain_text, _select_value, candidate_from_page,
                  fight_date_issue, instagram_handle_from_profile_url)

COMPLETED_STAGES = frozenset({"Ready to Send", "Contacted", "Replied", "Applied",
                              "Accepted", "Reserve", "Activated"})
QUALIFIED_AT = "Qualified At"
RECEIPT = "AI Qualification Receipt"
LONDON = ZoneInfo("Europe/London")


def utc_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Qualification timestamps must include a timezone")
    return parsed.astimezone(timezone.utc)


def today_bounds(now: datetime) -> tuple[datetime, datetime]:
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    start = now.astimezone(LONDON).replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


def stage(page: dict, stage_id: str) -> str:
    for key, prop in page.get("properties", {}).items():
        if prop.get("id", key) == stage_id:
            return _select_value(prop)
    return ""


def profile(page: dict) -> str | None:
    candidate = candidate_from_page(page)
    handle = instagram_handle_from_profile_url(candidate["verified_profile_url"])
    return handle.lower() if handle else None


def research_fingerprint(candidate: dict) -> str:
    candidate = dict(candidate)
    candidate.pop("page_id", None)
    candidate.pop("profile_url", None)  # Derived formula is not AI evidence.
    handle = instagram_handle_from_profile_url(candidate.get("verified_profile_url", ""))
    candidate["verified_profile_url"] = handle.lower() if handle else None
    candidate["instagram_handle"] = candidate.get("instagram_handle", "").strip().lstrip("@").lower()
    return hashlib.sha256(json.dumps(candidate, sort_keys=True).encode()).hexdigest()


def fingerprint(page: dict) -> str:
    candidate = research_fingerprint(candidate_from_page(page))
    props = page["properties"]
    outputs = {name: _plain_text(props.get(name)) for name in ("Draft DM", "AI Qualification Reason")}
    outputs["Outreach Approach"] = _select_value(props.get("Outreach Approach"))
    return hashlib.sha256(json.dumps([candidate, outputs], sort_keys=True).encode()).hexdigest()


def receipt(page: dict) -> dict | None:
    try:
        value = json.loads(_plain_text(page.get("properties", {}).get(RECEIPT)))
        if (value.get("version") != 1 or value.get("eligible") is not True
                or value.get("evidence_sufficient") is not True
                or value.get("page_id") != page["id"]):
            return None
        if type(value.get("active")) is not bool or type(value.get("legacy")) is not bool:
            return None
        if value.get("at") is not None:
            utc_time(value["at"])
        if value["active"] and value.get("at") is None and not value["legacy"]:
            return None
        return value
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def fields_valid(page: dict) -> bool:
    candidate = candidate_from_page(page)
    handle = profile(page)
    props = page["properties"]
    return bool(
        not page.get("archived") and not page.get("in_trash")
        and candidate["candidate"].strip() and candidate["personalised_dm_angle"].strip()
        and handle and candidate["instagram_handle"].strip().lstrip("@").lower() == handle
        and candidate["sport"] == "Boxing"
        and _plain_text(props.get("AI Qualification Reason")).strip()
        and _plain_text(props.get("Draft DM")).strip()
        and _select_value(props.get("Outreach Approach")) in {"A", "B"}
        and isinstance((props.get("Priority Score") or {}).get("number"), (int, float))
    )


def genuinely_qualified(page: dict, stage_id: str, now: datetime) -> bool:
    proof = receipt(page)
    if not (proof and fields_valid(page) and proof.get("fingerprint") == fingerprint(page)
            and stage(page, stage_id) in COMPLETED_STAGES):
        return False
    # A sent DM need not remain an upcoming fight forever.
    if stage(page, stage_id) == "Ready to Send":
        props = page["properties"]
        if fight_date_issue(candidate_from_page(page), draft=_plain_text(props.get("Draft DM")),
                            approach=_select_value(props.get("Outreach Approach")),
                            today=now.astimezone(LONDON).date()):
            return False
    return True


def new_receipt(page: dict, at: str | None, *, legacy: bool = False) -> dict:
    if not fields_valid(page):
        raise ValueError("Cannot attest an incomplete prospect")
    if at is not None:
        at = utc_time(at).isoformat(timespec="milliseconds")
    return {"version": 1, "page_id": page["id"], "eligible": True,
            "evidence_sufficient": True, "fingerprint": fingerprint(page),
            "active": True, "legacy": legacy, "at": at}


def receipt_properties(proof: dict) -> dict:
    return {RECEIPT: {"rich_text": [{"type": "text", "text": {"content": json.dumps(proof, sort_keys=True)}}]},
            QUALIFIED_AT: {"date": {"start": proof["at"]} if proof.get("at") else None}}


def reconcile(page: dict, stage_id: str, now: datetime) -> dict:
    """Return only needed metadata patches. Receipt is the crash-recovery source."""
    proof = receipt(page)
    if not proof:
        # A manual date or manual stage is never evidence of AI approval.
        return {QUALIFIED_AT: {"date": None}} if (page["properties"].get(QUALIFIED_AT) or {}).get("date") else {}
    valid = genuinely_qualified(page, stage_id, now)
    updated = dict(proof)
    if not valid:
        updated.update(active=False, at=None, legacy=False)
    elif not proof["active"]:
        # Manual return to a valid stage may reuse approval only for identical data.
        observed = utc_time(page["last_edited_time"])
        updated.update(active=True, at=min(observed, now).isoformat(timespec="milliseconds"), legacy=False)
    date = (page["properties"].get(QUALIFIED_AT) or {}).get("date")
    actual = date.get("start") if date else None
    expected = updated.get("at")
    try:
        same_date = actual is None and expected is None or (
            actual is not None and expected is not None
            and utc_time(actual) == utc_time(expected))
    except (ValueError, TypeError):
        same_date = False
    if updated != proof or not same_date:
        return receipt_properties(updated)
    return {}


def count_today(pages: list[dict], stage_id: str, now: datetime) -> int:
    """A profile's earliest currently valid qualification owns the credit."""
    start, end = today_bounds(now)
    owners: dict[str, datetime | None] = {}
    for page in pages:
        proof = receipt(page)
        if not proof or not proof["active"] or not genuinely_qualified(page, stage_id, now):
            continue
        handle = profile(page)
        at = utc_time(proof["at"]) if proof.get("at") else None
        if handle not in owners or at is None or (owners[handle] is not None and at < owners[handle]):
            owners[handle] = at
    return sum(at is not None and start <= at < end for at in owners.values())
