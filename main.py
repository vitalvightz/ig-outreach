from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any

import requests
from openai import OpenAI

NOTION_VERSION = "2026-03-11"
DEFAULT_DATA_SOURCE_ID = "08d8b476-129a-42b0-b980-102b08ce4bd8"
DEFAULT_MODEL = "gpt-5.6-luna"

AI_INSTRUCTIONS = """
You are UNLXCK's internal athlete-outreach qualification and drafting engine.
Work only from the structured prospect data supplied to you. Never invent a fact,
result, injury, fight date, gym, location, relationship, or performance claim.

QUALIFICATION
- Prioritise active combat athletes, especially boxing and MMA.
- A human sourcer is responsible for pre-screening that a Stage=Found prospect has
  a real active public profile, appears to be 18+, and trains consistently.
- Treat those baseline checks as passed unless the supplied data clearly contradicts
  them. Do not reject solely because explicit proof of age or profile activity is not
  repeated in the structured fields.
- Evaluate the supplied combat sport, recent public detail, current activity, camp
  relevance, and likely usefulness of a fight-camp performance app.
- UK athletes are preferred, but strong international candidates can qualify.
- Follower count, fame, purse, and whether they won or lost are not qualification
  criteria.
- A genuine recent public detail must exist before a DM can be drafted.
- If the supplied detail is too vague to personalise safely, mark evidence_sufficient
  false rather than inventing context.

PRIORITY SCORE (0-100)
- 90-100: confirmed current camp/upcoming fight plus strong product fit or warm signal.
- 75-89: strong recent competition/training activity, referral, follower/engager,
  or another clear reason to contact now.
- 60-74: qualified but lower urgency.
- Below 60: weak fit, unclear activity, or insufficient reason to prioritise.

OUTREACH APPROACH
- B = Camp Priority when the public evidence clearly shows an upcoming fight or
  current camp.
- A = Private Beta for other qualified prospects.

DRAFTING
- Use only the supplied verified public detail for personalisation.
- Do not use the old '7-0 post-surgery' or '8% more power per strike' claim.
- Do not send links in the first outreach.
- Do not feature-dump or use generic compliments.
- Keep the tone calm, direct, natural, and non-salesy.
- Approach A should be one short opening message using the verified detail, then:
  'We're selecting a few fighters for private Unlxck access before launch. Want the details?'
- Approach B should return a three-message sequence labelled M1, M2, M3:
  M1 uses the verified camp/fight detail and says it could be useful for this camp.
  M2 explains that Unlxck works out what actually needs priority so sparring,
  conditioning, S&C and recovery are not competing with each other as fight night gets closer.
  M3 asks permission to send more information.
- If evidence is insufficient, do not draft anything.

Return only the requested structured output.
""".strip()

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "eligible": {"type": "boolean"},
        "evidence_sufficient": {"type": "boolean"},
        "priority_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "qualification_reason": {"type": "string"},
        "outreach_approach": {"type": "string", "enum": ["A", "B", ""]},
        "draft_dm": {"type": "string"},
    },
    "required": [
        "eligible",
        "evidence_sufficient",
        "priority_score",
        "qualification_reason",
        "outreach_approach",
        "draft_dm",
    ],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    notion_api_key: str
    notion_data_source_id: str
    openai_model: str
    max_candidates_per_run: int
    dry_run: bool

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            openai_api_key=_required_env("OPENAI_API_KEY"),
            notion_api_key=_required_env("NOTION_API_KEY"),
            notion_data_source_id=os.getenv("NOTION_DATA_SOURCE_ID", DEFAULT_DATA_SOURCE_ID),
            openai_model=os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
            max_candidates_per_run=max(1, int(os.getenv("MAX_CANDIDATES_PER_RUN", "100"))),
            dry_run=os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"},
        )


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _notion_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _rich_text_value(value: str) -> list[dict[str, Any]]:
    if not value:
        return []
    return [{"type": "text", "text": {"content": value[:2000]}}]


def _plain_text(prop: dict[str, Any] | None) -> str:
    if not prop:
        return ""
    prop_type = prop.get("type")
    if prop_type not in {"title", "rich_text"}:
        return ""
    return "".join(item.get("plain_text", "") for item in prop.get(prop_type, []))


def _select_value(prop: dict[str, Any] | None) -> str:
    if not prop or prop.get("type") != "select" or not prop.get("select"):
        return ""
    return prop["select"].get("name", "")


def _url_value(prop: dict[str, Any] | None) -> str:
    if not prop or prop.get("type") != "url":
        return ""
    return prop.get("url") or ""


def candidate_from_page(page: dict[str, Any]) -> dict[str, str]:
    properties = page.get("properties", {})
    return {
        "page_id": page["id"],
        "candidate": _plain_text(properties.get("Candidate")),
        "instagram_handle": _plain_text(properties.get("Instagram Handle")),
        "profile_url": _url_value(properties.get("Profile URL")),
        "sport": _select_value(properties.get("Sport")),
        "experience": _select_value(properties.get("Experience")),
        "source": _select_value(properties.get("Source")),
        "source_detail": _plain_text(properties.get("Source Detail")),
        "location": _plain_text(properties.get("Location")),
        "city": _plain_text(properties.get("City")),
        "gym": _plain_text(properties.get("Gym")),
        "personalised_dm_angle": _plain_text(properties.get("Personalised DM Angle")),
        "notes": _plain_text(properties.get("Notes")),
    }


def query_pending_candidates(session: requests.Session, settings: Settings) -> list[dict[str, Any]]:
    url = f"https://api.notion.com/v1/data_sources/{settings.notion_data_source_id}/query"
    results: list[dict[str, Any]] = []
    start_cursor: str | None = None

    while len(results) < settings.max_candidates_per_run:
        payload: dict[str, Any] = {
            "filter": {"property": "Stage", "select": {"equals": "Found"}},
            "sorts": [{"timestamp": "created_time", "direction": "ascending"}],
            "page_size": min(100, settings.max_candidates_per_run - len(results)),
        }
        if start_cursor:
            payload["start_cursor"] = start_cursor

        response = session.post(
            url,
            headers=_notion_headers(settings.notion_api_key),
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        results.extend(body.get("results", []))

        if not body.get("has_more"):
            break
        start_cursor = body.get("next_cursor")
        if not start_cursor:
            break

    return results[: settings.max_candidates_per_run]


def preflight_reason(candidate: dict[str, str]) -> str | None:
    if not candidate["instagram_handle"] and not candidate["profile_url"]:
        return "Needs research: missing Instagram handle or profile URL."
    if not candidate["personalised_dm_angle"].strip():
        return "Needs research: no genuine recent public personalisation detail recorded."
    if not candidate["sport"].strip():
        return "Needs research: combat sport is not recorded."
    return None


def qualify_and_draft(client: OpenAI, settings: Settings, candidate: dict[str, str]) -> dict[str, Any]:
    safe_candidate = {key: value for key, value in candidate.items() if key != "page_id"}
    response = client.responses.create(
        model=settings.openai_model,
        instructions=AI_INSTRUCTIONS,
        input=json.dumps(safe_candidate, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "outreach_decision",
                "schema": OUTPUT_SCHEMA,
                "strict": True,
            }
        },
        max_output_tokens=500,
        store=False,
    )
    result = json.loads(response.output_text)
    validate_ai_result(result)
    return result


def validate_ai_result(result: dict[str, Any]) -> None:
    score = result.get("priority_score")
    if not isinstance(score, int) or not 0 <= score <= 100:
        raise ValueError("AI returned an invalid priority score")

    eligible = result.get("eligible") is True
    evidence_sufficient = result.get("evidence_sufficient") is True
    approach = result.get("outreach_approach", "")
    draft = result.get("draft_dm", "").strip()

    if eligible and evidence_sufficient:
        if approach not in {"A", "B"}:
            raise ValueError("Qualified prospect is missing outreach approach A/B")
        if not draft:
            raise ValueError("Qualified prospect is missing a DM draft")
    elif draft:
        raise ValueError("AI drafted a DM despite insufficient evidence or ineligibility")


def stage_from_result(result: dict[str, Any]) -> str:
    if not result["evidence_sufficient"]:
        return "Researching"
    if not result["eligible"]:
        return "Rejected"
    return "Ready to DM"


def update_candidate(
    session: requests.Session,
    settings: Settings,
    candidate: dict[str, str],
    *,
    stage: str,
    priority_score: int,
    qualification_reason: str,
    outreach_approach: str = "",
    draft_dm: str = "",
) -> None:
    properties: dict[str, Any] = {
        "Stage": {"select": {"name": stage}},
        "Priority Score": {"number": priority_score},
        "AI Qualification Reason": {"rich_text": _rich_text_value(qualification_reason)},
        "Draft DM": {"rich_text": _rich_text_value(draft_dm)},
    }
    if outreach_approach:
        properties["Outreach Approach"] = {"select": {"name": outreach_approach}}

    if settings.dry_run:
        print(
            json.dumps(
                {
                    "dry_run": True,
                    "candidate": candidate.get("candidate") or candidate.get("instagram_handle"),
                    "stage": stage,
                    "priority_score": priority_score,
                    "outreach_approach": outreach_approach,
                    "draft_dm": draft_dm,
                },
                ensure_ascii=False,
            )
        )
        return

    response = session.patch(
        f"https://api.notion.com/v1/pages/{candidate['page_id']}",
        headers=_notion_headers(settings.notion_api_key),
        json={"properties": properties},
        timeout=30,
    )
    response.raise_for_status()


def run_outreach() -> int:
    settings = Settings.from_env()
    session = requests.Session()
    client = OpenAI(api_key=settings.openai_api_key)

    pages = query_pending_candidates(session, settings)
    print(f"Pending prospects pulled from Notion: {len(pages)}")

    processed = 0
    failed = 0

    for page in pages:
        candidate = candidate_from_page(page)
        label = candidate["candidate"] or candidate["instagram_handle"] or candidate["page_id"]

        try:
            missing = preflight_reason(candidate)
            if missing:
                update_candidate(
                    session,
                    settings,
                    candidate,
                    stage="Researching",
                    priority_score=0,
                    qualification_reason=missing,
                )
                print(f"Researching: {label} — {missing}")
                processed += 1
                continue

            result = qualify_and_draft(client, settings, candidate)
            stage = stage_from_result(result)
            update_candidate(
                session,
                settings,
                candidate,
                stage=stage,
                priority_score=result["priority_score"],
                qualification_reason=result["qualification_reason"],
                outreach_approach=result["outreach_approach"] if stage == "Ready to DM" else "",
                draft_dm=result["draft_dm"] if stage == "Ready to DM" else "",
            )
            print(f"{stage}: {label} — score {result['priority_score']}")
            processed += 1
        except Exception as exc:
            failed += 1
            print(f"ERROR: {label}: {exc}", file=sys.stderr)

    print(f"Outreach run complete. Processed={processed}, Failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run_outreach())