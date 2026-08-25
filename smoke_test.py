from __future__ import annotations

import requests
from openai import AuthenticationError, OpenAI

from main import Settings, qualify_and_draft, query_pending_candidates


def main() -> int:
    settings = Settings.from_env()
    session = requests.Session()

    # Proves the Notion token can query the real candidate data source.
    pages = query_pending_candidates(session, settings)
    print(f"Notion connection OK. Found-stage prospects visible: {len(pages)}")

    # Synthetic input exercises the OpenAI request without touching a real athlete record.
    candidate = {
        "candidate": "Synthetic integration test",
        "instagram_handle": "@synthetic_test",
        "profile_url": "https://instagram.com/synthetic_test",
        "sport": "Boxing",
        "experience": "Amateur",
        "source": "Manual discovery",
        "source_detail": "Integration test only",
        "location": "UK",
        "city": "",
        "gym": "",
        "personalised_dm_angle": "A public fight announcement says the athlete is preparing for a bout on 18 October.",
        "notes": "Synthetic record used only to validate the outreach engine. Do not infer any other facts.",
    }

    try:
        result = qualify_and_draft(OpenAI(api_key=settings.openai_api_key), settings, candidate)
    except AuthenticationError as exc:
        raise RuntimeError(
            "OpenAI authentication failed. Replace the GitHub Actions secret OPENAI_API_KEY with a current OpenAI API key."
        ) from exc

    if not result["eligible"] or not result["evidence_sufficient"]:
        raise RuntimeError(f"Smoke test should qualify the synthetic prospect: {result}")
    if result["outreach_approach"] != "B":
        raise RuntimeError(f"Expected Camp Priority approach B: {result}")
    draft = result["draft_dm"]
    if not all(label in draft for label in ("M1", "M2", "M3")):
        raise RuntimeError(f"Expected labelled M1/M2/M3 sequence: {draft}")

    print("OpenAI structured-output smoke test OK.")
    print(draft)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
