from __future__ import annotations

import requests
from openai import AuthenticationError, OpenAI

from main import Settings, qualify_and_draft, query_pending_candidates, validate_ai_result


def main() -> int:
    settings = Settings.from_env()
    session = requests.Session()

    # Proves the Notion token can query the real candidate data source without writing.
    pages = query_pending_candidates(session, settings)
    print(f"Notion connection OK. Found-stage prospects visible: {len(pages)}")

    # Synthetic input exercises OpenAI authentication + structured output only.
    # Qualification policy itself is covered by unit tests and should not make this
    # integration smoke test brittle.
    candidate = {
        "candidate": "Integration Test Fighter",
        "instagram_handle": "@integration_test_fighter",
        "profile_url": "https://instagram.com/integration_test_fighter",
        "sport": "Boxing",
        "experience": "Amateur",
        "source": "Manual discovery",
        "source_detail": "Integration fixture",
        "location": "UK",
        "city": "",
        "gym": "",
        "personalised_dm_angle": "A public fight announcement says the athlete is preparing for a bout on 18 October.",
        "notes": "Integration fixture. Do not infer facts beyond the supplied fields.",
    }

    try:
        result = qualify_and_draft(OpenAI(api_key=settings.openai_api_key), settings, candidate)
    except AuthenticationError as exc:
        raise RuntimeError(
            "OpenAI authentication failed. Replace the GitHub Actions secret OPENAI_API_KEY with a current OpenAI API key."
        ) from exc

    validate_ai_result(result)

    required = {
        "eligible",
        "evidence_sufficient",
        "priority_score",
        "qualification_reason",
        "outreach_approach",
        "draft_dm",
    }
    missing = required.difference(result)
    if missing:
        raise RuntimeError(f"OpenAI structured output missing fields: {sorted(missing)}")

    print("OpenAI authentication + structured-output smoke test OK.")
    print(
        f"eligible={result['eligible']} evidence_sufficient={result['evidence_sufficient']} "
        f"score={result['priority_score']} approach={result['outreach_approach'] or 'none'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
