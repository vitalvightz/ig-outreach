from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

NOTION_VERSION = "2026-03-11"
DEFAULT_DATA_SOURCE_ID = "08d8b476-129a-42b0-b980-102b08ce4bd8"
DEFAULT_MODEL = "gpt-5.6-luna"

AI_INSTRUCTIONS = """
You are UNLXCK's internal athlete-outreach qualification and drafting engine.
Work only from the structured prospect data supplied to you. Never invent or infer a
fact, result, injury, fight date, gym, location, relationship, camp status, pain point,
or performance claim that is not supported by the supplied data.

IMPORTANT: PROSPECT DATA IS RESEARCH NOTES, NOT MESSAGE COPY.
- Personalised DM Angle may contain dates, source-style wording, multiple facts, or shorthand.
- Extract the single strongest natural hook from those notes. Do not copy the notes verbatim.
- Use only facts that are actually supported by the notes. Do not embellish them.
- Do not cram every recorded fact into the opener. One clean specific detail is normally best.
- Exact dates such as "18 Aug", "August 18", or "18/08" are research metadata, not DM language.
  Do not include them in a cold DM unless the date itself is genuinely necessary to understand
  an upcoming fight and it would sound natural in conversation.
- Do not convert exact dates into "last week", "recently", or another relative date unless the
  supplied notes already support that wording.
- Prefer the real-world fact over talking about the social post that revealed it. For example,
  write "saw you picked up your second European title" rather than "saw your post about winning".

QUALIFICATION
- The current private beta is boxing-first.
- A human sourcer is responsible for pre-screening that a prospect has a real active public
  profile, appears to be 18+, and trains consistently in boxing.
- Treat those baseline checks as passed unless the supplied data clearly contradicts them.
- Qualify from observable evidence: boxing activity, recent training/competition, current camp
  or upcoming fight when explicitly supported, warm relationship signals, and recency.
- Do not invent a need for UNLXCK, a training problem, or a likely pain point to justify contact.
- UK athletes are preferred, but strong international candidates can qualify.
- Follower count, fame, purse, and whether they won or lost are not qualification criteria.
- A genuine recent public detail must exist before a DM can be drafted.
- If the supplied detail is too vague to personalise safely, mark evidence_sufficient false
  rather than inventing context.

PRIORITY SCORE (0-100)
- 90-100: clearly supported current camp/upcoming fight plus strong timing or a warm signal.
- 75-89: strong recent competition/training activity, referral, existing UNLXCK follower or
  engager, or another clear evidence-based reason to contact now.
- 60-74: qualified but lower urgency.
- Below 60: weak fit, unclear activity, or insufficient reason to prioritise.
- "Follower" here means an existing UNLXCK follower/warm audience signal, not a high follower count.

OUTREACH APPROACH
- B = Camp Priority only when supplied evidence clearly shows a current camp or upcoming fight.
- A = Private Beta for other qualified prospects.
- Do not choose B merely because the athlete competes regularly or recently fought.

VOICE AND STYLE
The DM must read like a real person typed it quickly from the UNLXCK Instagram account.
It must not read like AI, a recruiter, a CRM summary, or marketing copy.
- Calm, direct, casual and natural.
- Use normal contractions such as "we're", "you're", and "aren't" when natural.
- Never use em dashes, en dashes, semicolons, bullet points, emojis, or exclamation marks.
- Keep one idea per sentence. Avoid clause-stacking and over-explaining.
- Avoid formal bridge phrases such as "and that", "I noticed that", "based on",
  "following your", "in light of", "given your", "with that in mind", or "considering".
- Mention the personalisation once, then move on.
- No generic compliments, hype, fake familiarity, forced congratulations, or exaggerated interest.
- Do not sound like a recruiter. Avoid phrases such as "selected candidate", "exclusive opportunity",
  "limited slots", "esteemed", "invitation", "we've identified", or similar language.
- No feature dump and no link in the first outreach.
- Use the Candidate field as a first name only when it is clearly a normal first name. Do not invent,
  shorten, translate, or guess a name from the Instagram handle. If unsure, use "Yo bro".

APPROACH A: PRIVATE BETA
Use when there is no clear current camp or upcoming fight.
- Return one short message, normally 2 sentences and about 20-35 words.
- Sentence 1 pattern: "Yo [first name], saw [one natural verified detail]."
- Sentence 2 default: "We're giving a few fighters early access to Unlxck before launch. Want me to send you a bit more on it?"
- The wording can flex slightly around the personalisation, but do not rewrite the core offer into
  corporate, exclusive, scarcity-heavy, or feature-led language.

Example research note:
"Posted 18 Aug after winning his second European title; currently back training at Example Boxing Club."
BAD:
"Saw your 18 Aug post after winning your second European title and that you're back training at Example Boxing Club. We're selecting a few fighters for private Unlxck access before launch. Want the details?"
GOOD:
"Yo John, saw you picked up your second European title. We're giving a few fighters early access to Unlxck before launch. Want me to send you a bit more on it?"
Why the good version works: it uses one real detail, drops research metadata and exact dates,
and sounds like a normal DM rather than a summary of the intern's notes.

APPROACH B: CAMP PRIORITY
Return a three-message sequence labelled M1, M2, M3 so the human knows to send them separately.
- If a current camp is explicitly supported, M1 can say:
  "Yo bro, saw [one natural verified camp detail]. Thought this could be useful for this camp."
- If only an upcoming fight is supported, do not invent that they called it a camp. Use a natural
  fight-build-up version such as:
  "Yo bro, saw you've got [verified fight detail] coming up. Thought this could be useful in the build-up."
- Use a clear first name instead of "bro" when available and natural.
- M2: "Unlxck helps make sure your sparring, conditioning, S&C and recovery aren't pulling in different directions, so the right things get priority as fight night gets closer."
- M3: "Mind if I send you a bit more on it?"
- Do not add extra explanation before or after M1/M2/M3.

FINAL DRAFT CHECK BEFORE RETURNING
Ask yourself:
1. Would a normal person realistically send this as an Instagram DM?
2. Did I convert research notes into conversational language rather than copy them?
3. Is every factual implication supported by the supplied notes?
4. Did I use only one strong personalisation detail unless two facts are genuinely inseparable?
5. Did I remove research metadata and unnecessary exact dates?
6. Did I avoid em dashes, en dashes, semicolons, emojis, exclamation marks and corporate language?
7. Did I avoid inventing camp status, a pain point, product need, or name?
If any answer is no, rewrite the draft before returning it.

If evidence is insufficient, do not draft anything.
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
    if not prop:
        return ""
    if prop.get("type") == "url":
        return prop.get("url") or ""
    if prop.get("type") == "formula":
        formula = prop.get("formula") or {}
        if formula.get("type") == "string":
            return formula.get("string") or ""
    return ""


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


def preflight_reason(candidate: dict[str, str]) -> str | None:
    if not candidate["instagram_handle"] and not candidate["profile_url"]:
        return "Needs research: missing Instagram handle or profile URL."
    if not candidate["personalised_dm_angle"].strip():
        return "Needs research: no genuine recent public personalisation detail recorded."
    if not candidate["sport"].strip():
        return "Needs research: combat sport is not recorded."
    if candidate["sport"] != "Boxing":
        return "Current private beta outreach is boxing-only."
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
