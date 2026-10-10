from __future__ import annotations

import calendar
import json
import os
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlparse

from openai import OpenAI

NOTION_VERSION = "2026-03-11"
DEFAULT_DATA_SOURCE_ID = "08d8b476-129a-42b0-b980-102b08ce4bd8"
DEFAULT_MODEL = "gpt-5.6-luna"

INSTAGRAM_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
INSTAGRAM_PROFILE_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
INSTAGRAM_RESERVED_PATHS = {
    "accounts",
    "about",
    "direct",
    "explore",
    "p",
    "reel",
    "reels",
    "stories",
    "tv",
}

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
- Separate the publication date of a social post (e.g. "posted 1 October 2026") from
  the actual bout/event date ("fight on 24 October 2026"). Compare ONLY the event
  date against today when evaluating an upcoming fight. A past publication date is
  not proof of an expired fight.
- For an upcoming fight, require a verified calendar date with day, month and year.
  Never treat an expired fight as upcoming.
- The date and venue of an event alone do NOT establish that this particular athlete
  is competing there. Require evidence linking the athlete to the card or fight,
  such as a named fight poster, athlete confirmation or an opponent announcement.
  If that link is missing, mark Needs Research and say to confirm PARTICIPATION,
  not to supply a date already given.
- A recent completed fight can be used as a past result for Private Beta outreach.
  Do not reject the athlete merely because a clearly historical bout has ended.
- Include the exact verified date in any DM about an upcoming fight, e.g. "24 October 2026".
  Never say "in two weeks", "a few days", "tomorrow", or other relative timings.
- If the only fight evidence is an unanchored relative date or ambiguous year, evidence is
  insufficient. Do not draft an upcoming-fight DM.
- Prefer the real-world fact over talking about the social post that revealed it. For example,
  write "saw you picked up your second European title" rather than "saw your post about winning".

QUALIFICATION
- The current outreach beta is boxing-only.
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
- The numeric score is assigned deterministically after qualification. Do not try to reward prestige.
- Titles, medals, rankings, Olympian status, professional status, fame, purse, record, wins/losses,
  reputation, and high follower count add ZERO priority points.
- Competitive achievements may support that the athlete is genuine/active or provide a DM hook,
  but they must never raise the numeric priority score by themselves.
- Priority is driven by: recent activity, a clear reason to contact now, current camp/upcoming fight,
  usable personalisation evidence, and warm-source signals.
- Set recent_activity true only when the supplied notes support genuinely recent boxing training or competition.
- Set timely_reason true only when there is a clear present-tense reason to contact now beyond prestige alone.
- Set strong_personalisation true when the supplied detail is specific, recent and naturally usable in a DM.
- A title/medal/ranking can be the DM hook, but achievement level itself adds ZERO points.
- "Follower" means an existing UNLXCK follower/warm audience signal, not a high follower count.

OUTREACH APPROACH
- B = Camp Priority only when supplied evidence clearly shows a current camp or a verified future fight date.
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
- If Candidate is a clear personal name, use its obvious first-name component after "Yo". For example,
  Candidate "Yash Patel" may become "Yo Yash". Do not invent a nickname, translate a name, or guess a
  name from the Instagram handle. If the Candidate field is ambiguous, use "Yo bro".

MESSAGE STRUCTURE (BOTH APPROACHES)
- Return exactly three short lines labelled M1, M2 and M3. No extra explanation.
- Aim for 25-35 words total. Never omit a required verified fight date just to hit the target.
- M1 (about 8-15 words): "Yo [first name], saw [one natural verified detail]."
  Personalise once, without adding a pitch or an unsupported assumption.
- M2 (about 10-20 words): one sentence introducing early access to Unlxck and ONE
  relevant benefit. Sell the outcome, not a list of features. Never assume the athlete
  is fatigued, injured, struggling or needs help without supporting evidence.
- M3 must be exactly: "Want the details?"
- Keep M1, M2 and M3 concise even when research notes contain many details.

M2 ANGLES
Choose the strongest relevant angle using only verified prospect context:
- Fight the next day (D-1): position Unlxck for the NEXT camp, not last-minute gains.
- Fight in 2-6 days: taper/freshness or the next camp, without promising instant results.
- Fight in 7+ days: camp planning around sparring, conditioning and fight night.
- Recently completed fight (last 14 days): next training block and recovery, without
  assuming the result or that the athlete is injured. This remains Approach A.
- Verified current camp, no confirmed fight date: fit extra work around sparring.
- Publicly disclosed injury: adapt training to restrictions, without medical promises.
- Verified style or conditioning goal: style-specific conditioning.
- Verified heavy training schedule: readiness-guided load decisions, without assuming fatigue.
- Explicit interest in round-based drills: session timer.
- Otherwise: personalised training around goals and daily readiness.
These are alternatives, not a checklist. Use only ONE angle in M2.

M2 EXAMPLES (STYLE REFERENCES, NOT FIXED SCRIPTS)
Keep each to 10-20 words, name Unlxck and early access, and adapt naturally to
verified context. Never infer a training problem from fight timing alone.
- Fight tomorrow: "We're giving fighters early access to Unlxck to plan their next camp around training and recovery."
- Fight in 2-6 days: "We're offering early access to Unlxck to manage training load as fight night gets closer."
- Fight in 7+ days: "We're giving fighters early access to Unlxck to plan conditioning around sparring and fight night."
- Recently fought: "We're giving fighters early access to Unlxck to structure the next training block around recovery."
- Current camp: "We're giving fighters early access to Unlxck to fit conditioning around existing sparring sessions."
- No scheduled fight: "We're giving fighters early access to Unlxck for training built around their goals and daily readiness."
- Disclosed injury: "We're giving fighters early access to Unlxck to adjust training around injury restrictions and recovery."
- Timer interest: "We're giving fighters early access to Unlxck for round timers that keep conditioning sessions organised."
Select one relevant benefit; do not combine examples, repeat hooks, or claim guaranteed results.

APPROACH A: PRIVATE BETA
Use for qualified prospects without a verified current camp or future fight, including
recently completed fights. Apply the same M1/M2/M3 structure with an appropriate angle.
Example for a verified recent achievement:
M1: Yo John, saw you picked up your second European title.
M2: We're giving fighters early access to Unlxck for training built around their goals and readiness.
M3: Want the details?

APPROACH B: CAMP PRIORITY
Use only for a verified current camp or future fight. Do not invent camp status
from a confirmed fight date. Include the exact verified day, month and year in M1
for any upcoming fight; the short-message target never overrides this requirement.
Example for a verified future fight:
M1: Yo Sam, saw you've got a fight on 24 October 2026.
M2: We're giving fighters early access to Unlxck to plan conditioning around sparring and fight night.
M3: Want the details?

FINAL DRAFT CHECK BEFORE RETURNING
Ask yourself:
1. Would a normal person realistically send this as an Instagram DM?
2. Did I convert research notes into conversational language rather than copy them?
3. Is every factual implication supported by the supplied notes?
4. Did I use only one strong personalisation detail unless two facts are genuinely inseparable?
5. Did I include the exact day, month and year for an upcoming fight and avoid relative timings?
6. Did I avoid em dashes, en dashes, semicolons, emojis, exclamation marks and corporate language?
7. Did I avoid inventing camp status, a pain point, product need, or name?
If any answer is no, rewrite the draft before returning it.

If evidence is insufficient, do not draft anything.
Return only the requested structured output.
""".strip()


_MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTHS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTHS["sept"] = 9
_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))
_MONTH_YEAR_RE = re.compile(rf"\b(?P<month>{_MONTH_PATTERN})\s+(?P<year>20\d{{2}})\b", re.IGNORECASE)
_FIGHT_DATE_RE = re.compile(
    rf"\b(?:(?P<d1>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<m1>{_MONTH_PATTERN})\.?(?:,?\s+(?P<y1>20\d{{2}}))?"
    rf"|(?P<m2>{_MONTH_PATTERN})\.?\s+(?P<d2>\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(?P<y2>20\d{{2}}))?"
    rf"|(?P<d3>\d{{1,2}})/(?P<m3>\d{{1,2}})/(?P<y3>(?:20)?\d{{2}})"
    rf"|(?P<y4>20\d{{2}})-(?P<m4>\d{{1,2}})-(?P<d4>\d{{1,2}}))\b",
    re.IGNORECASE,
)
_FIGHT_CONTEXT_RE = re.compile(
    r"\b(fight|bout|vs|versus|debut|championships?|camp|poster|card|locked in|worlds|events?|shows?|tournaments?)\b",
    re.IGNORECASE,
)
_UPCOMING_RE = re.compile(
    r"\b(upcoming|coming up|locked in|tomorrow|next week|fight week|"
    r"\d+\s+weeks?\s+(?:out|to go)|(?:a |one |two |three |few )weeks?\s+(?:out|to go))\b",
    re.IGNORECASE,
)
_POSTED_DATE_PREFIX_RE = re.compile(
    r"\b(?:post(?:ed)?|published|uploaded|announced|shared)\s+(?:(?:on|at|dated)\s*)?$",
    re.IGNORECASE,
)
_GENERIC_UPCOMING_EVENT_RE = re.compile(
    r"\b(?:upcoming|next|future)\s+(?:(?:boxing|fight)\s+)?(?:event|show|tournament)\b",
    re.IGNORECASE,
)
_ATHLETE_EVENT_LINK_RE = re.compile(
    r"\b(?:fighting|competing|boxing\s+(?:at|on)|booked|confirmed\s+(?:to|for)|"
    r"scheduled\s+(?:to|for)|listed|named\s+(?:on|for)|appearing|participating|"
    r"joins?|features?|featuring|faces?|facing|takes?\s+on|vs\.?|versus|on\s+(?:the\s+)?card)\b",
    re.IGNORECASE,
)
_RELATIVE_DM_RE = re.compile(
    r"\b(tomorrow|next week|this weekend|in (?:a |the )?few days|"
    r"in (?:\d+|one|two|three|four)\s+(?:days?|weeks?)|"
    r"(?:one|two|three|four|\d+)\s+weeks?\s+(?:out|to go))\b",
    re.IGNORECASE,
)


def _dated_matches(text: str) -> list[tuple[date, int, int]]:
    """Parsed full dates with offsets, excluding unparseable calendar dates."""
    result = []
    for match in _FIGHT_DATE_RE.finditer(text):
        g = match.groupdict()
        year = g["y1"] or g["y2"] or g["y3"] or g["y4"]
        if not year:
            continue
        day = g["d1"] or g["d2"] or g["d3"] or g["d4"]
        month = g["m1"] or g["m2"] or g["m3"] or g["m4"]
        try:
            parsed = date(int(year) + (2000 if len(year) == 2 else 0),
                          _MONTHS[month.lower()] if month.lower() in _MONTHS else int(month),
                          int(day))
        except ValueError:
            continue
        result.append((parsed, match.start(), match.end()))
    return result


def _fight_dates(text: str) -> list[date]:
    """Dates of real-world events, never dates explicitly labelled as post metadata."""
    return [value for value, start, _ in _dated_matches(text)
            if not _POSTED_DATE_PREFIX_RE.search(text[:start])]


def fight_date_issue(
    candidate: dict[str, str],
    draft: str = "",
    approach: str = "",
    today: date | None = None,
) -> tuple[str, str] | None:
    """Distinguish publication metadata, bouts, and unverified event participation."""
    today = today or datetime.now(ZoneInfo("Europe/London")).date()
    evidence = candidate.get("personalised_dm_angle", "")
    future, past = [], []
    upcoming, partial_date, generic_event_without_athlete = False, False, False
    for part in re.split(r"\s*\+\s*|[;\n]", evidence):
        if not _FIGHT_CONTEXT_RE.search(part):
            continue
        is_upcoming = bool(_UPCOMING_RE.search(part))
        upcoming |= is_upcoming
        matches = _dated_matches(part)
        event_dates = [value for value, start, _ in matches
                       if not _POSTED_DATE_PREFIX_RE.search(part[:start])]
        # Publication dates, including a month/year within a full posted date,
        # never make a future event appear expired.
        if is_upcoming:
            for month_year in _MONTH_YEAR_RE.finditer(part):
                if any(start <= month_year.start() < end for _, start, end in matches):
                    continue
                if _POSTED_DATE_PREFIX_RE.search(part[:month_year.start()]):
                    continue
                month_number = _MONTHS[month_year["month"].lower()]
                year_number = int(month_year["year"])
                if (year_number, month_number) < (today.year, today.month):
                    past.append(date(year_number, month_number, 1))
        partial_date |= bool(_FIGHT_DATE_RE.search(part)) and not bool(matches)
        for event_date in event_dates:
            (future if event_date >= today else past).append(event_date)
        if (is_upcoming and _GENERIC_UPCOMING_EVENT_RE.search(part)
                and not _ATHLETE_EVENT_LINK_RE.search(part)):
            generic_event_without_athlete = True

    claims_future = bool(re.search(r"\b(coming up|upcoming|locked in|fight night gets closer)\b", draft, re.I))
    if upcoming and not future and past:
        stale = past[0]
        if any(stale.day == 1 and _MONTH_YEAR_RE.search(p) for p in re.split(r"\s*\+\s*|[;\n]", evidence)):
            return "Rejected", f"Rejected: purported upcoming fight was in {stale:%B %Y}, before today ({today:%d %B %Y})."
        return "Rejected", f"Rejected: purported upcoming fight was on {stale:%d %B %Y}, before today ({today:%d %B %Y})."
    if past and claims_future and not future:
        return "Rejected", f"Rejected: draft describes a past fight as upcoming (today: {today:%d %B %Y})."
    if upcoming and not future:
        return "Needs Research", "Needs research: supply the verified full upcoming fight date (day, month, year), not relative timing."
    if generic_event_without_athlete and future:
        return ("Needs Research", "Needs research: the event date is provided, but the notes "
                "do not confirm this boxer is actually competing on that card. "
                "Verify the athlete's participation before requeuing.")
    current_camp = bool(re.search(r"\b(current(?:ly)?(?:\s+\w+){0,3}\s+camp|in\s+camp|camp\b.{0,40}\bcurrent)\b", evidence, re.I))
    if approach == "B" and partial_date and not future:
        return "Needs Research", "Needs research: confirm the event year and full fight date before sending."
    if (approach == "B" or claims_future) and not future and not current_camp:
        return "Needs Research", "Needs research: camp priority requires confirmed current camp or a full future fight date."
    if draft and _RELATIVE_DM_RE.search(draft):
        return "Needs Research", "Needs research: draft uses relative fight timing. Use a verified exact calendar date."
    if draft and (approach == "B" or claims_future) and future and not any(d in _fight_dates(draft) for d in future):
        return "Needs Research", "Needs research: upcoming fight DM must state the verified exact day, month and year."
    return None

WARM_SOURCE_BONUS = {
    "Existing follower": 10,
    "Story engager": 10,
    "Connector referral": 12,
    "Athlete referral": 12,
    "Inbound application": 15,
}


def deterministic_priority_score(candidate: dict[str, str], result: dict[str, Any]) -> int:
    """Rank outreach urgency without rewarding athlete prestige."""
    if result.get("eligible") is not True:
        return 0
    if result.get("evidence_sufficient") is not True:
        return 25

    signals = result.get("priority_signals") or {}
    score = 40
    if signals.get("recent_activity") is True:
        score += 10
    if signals.get("timely_reason") is True:
        score += 10
    if result.get("outreach_approach") == "B":
        score += 20
    if signals.get("strong_personalisation") is True:
        score += 5
    score += WARM_SOURCE_BONUS.get(candidate.get("source", ""), 0)
    return min(score, 100)


OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "eligible": {"type": "boolean"},
        "evidence_sufficient": {"type": "boolean"},
        "priority_score": {"type": "integer", "minimum": 0, "maximum": 100},
        "priority_signals": {
            "type": "object",
            "properties": {
                "recent_activity": {"type": "boolean"},
                "timely_reason": {"type": "boolean"},
                "strong_personalisation": {"type": "boolean"},
            },
            "required": ["recent_activity", "timely_reason", "strong_personalisation"],
            "additionalProperties": False,
        },
        "qualification_reason": {"type": "string"},
        "outreach_approach": {"type": "string", "enum": ["A", "B", ""]},
        "draft_dm": {"type": "string"},
    },
    "required": [
        "eligible",
        "evidence_sufficient",
        "priority_score",
        "priority_signals",
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
    def from_env(cls, *, require_openai: bool = True) -> "Settings":
        return cls(
            openai_api_key=_required_env("OPENAI_API_KEY") if require_openai else "",
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
        "verified_profile_url": _url_value(properties.get("Verified Profile URL")),
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


def instagram_handle_from_profile_url(value: str) -> str | None:
    """Extract a canonical Instagram username from a copied profile URL."""
    raw = (value or "").strip()
    if not raw:
        return None

    try:
        parsed = urlparse(raw)
    except ValueError:
        return None

    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc.lower() not in INSTAGRAM_PROFILE_HOSTS:
        return None

    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if len(parts) != 1:
        return None

    handle = parts[0].lstrip("@")
    if handle.lower() in INSTAGRAM_RESERVED_PATHS:
        return None
    if (not INSTAGRAM_HANDLE_RE.fullmatch(handle)
            or handle.startswith(".") or handle.endswith(".") or ".." in handle):
        return None
    return handle


def verified_profile_reason(candidate: dict[str, str]) -> tuple[str | None, str | None]:
    """Return (canonical_handle, problem) for the human-copied Instagram profile URL."""
    verified_url = candidate.get("verified_profile_url", "").strip()
    if not verified_url:
        return (
            None,
            "Needs research: paste the exact Instagram profile URL into Verified Profile URL. "
            "Do not type or guess the username.",
        )

    handle = instagram_handle_from_profile_url(verified_url)
    if not handle:
        return (
            None,
            "Needs research: Verified Profile URL must be a direct Instagram profile link, "
            "for example https://www.instagram.com/username/.",
        )

    return handle, None


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
        instructions=f"Today's date in Europe/London: {datetime.now(ZoneInfo('Europe/London')):%d %B %Y}.\n{AI_INSTRUCTIONS}",
        input=json.dumps(safe_candidate, ensure_ascii=False),
        text={
            "format": {
                "type": "json_schema",
                "name": "outreach_decision",
                "schema": OUTPUT_SCHEMA,
                "strict": True,
            }
        },
        max_output_tokens=1200,
        store=False,
    )
    result = json.loads(response.output_text)
    validate_ai_result(result)
    result["priority_score"] = deterministic_priority_score(candidate, result)
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
