# UNLXCK Outreach AI

Internal outreach automation for the UNLXCK private beta.

## Architecture

`Intern View -> OpenAI qualification/drafting -> Ready to Send -> human Instagram send -> human pipeline updates`

Notion is the single source of truth. Google Sheets is no longer part of the workflow.

## Manual vs automated

### Intern manually does

1. Add `Candidate`.
2. Add `Instagram Handle`.
3. Add one genuine recent public `Personalised DM Angle`.
4. Optionally add `Source`.
5. Visually confirm the profile is real/active, appears 18+, and consistently trains in boxing.
6. If AI returns `Needs Research`, improve the evidence and set `Stage = AI Queue` for a re-check.
7. If AI returns `Ready to Send`, verify the real profile and draft, send the DM manually, then set `Stage = Contacted` and update contact/follow-up fields.
8. Update later stages only when the real athlete action happens.

### Automation/AI does

- Detects new prospects whose Stage is blank, plus explicit `AI Queue` re-checks.
- Defaults blank `Sport` to `Boxing` for the current beta.
- Uses the Notion `Profile URL` formula generated from Instagram Handle.
- Qualifies/ranks the prospect from the supplied evidence.
- Chooses Approach A or B.
- Writes `Priority Score`, `AI Qualification Reason`, `Outreach Approach`, and `Draft DM`.
- Sets Stage to `Needs Research`, `Ready to Send`, or `Rejected`.
- Never sends Instagram DMs.
- Never changes `Contacted` or any later human-owned stage.

## Stage ownership

### AI/system stages

- Blank Stage — newly entered prospect; automatically detected.
- `AI Queue` — manual trigger to ask AI to re-check a corrected prospect.
- `Needs Research` — more/better public evidence is required.
- `Ready to Send` — AI-qualified and drafted; human must verify before sending.
- `Rejected` — unsuitable for current outreach unless the founder overrides.

### Human stages after outreach

- `Contacted`
- `Replied`
- `Applied`
- `Accepted`
- `Reserve`
- `Activated`
- `Inactive`

## Safety rules

The automation must not invent athlete facts, results, injuries, fight dates, gyms, locations, relationships, or performance claims. It must not reuse the old 7-0 / 8% power claim.

Cold Instagram sends remain human-only.

## Required GitHub secrets

- `OPENAI_API_KEY`
- `NOTION_API_KEY`

Never commit either secret to the repository.

## Schedule

GitHub Actions runs hourly from 08:00 through 17:00 UTC on weekdays and can also be started manually.

A new blank-stage row is processed once. A `Needs Research` record is not repeatedly billed; after fixing its evidence, a human sets it to `AI Queue` to request another AI check.

## Local run

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="..."
export NOTION_API_KEY="..."
python pipeline.py
```

For a no-write test:

```bash
DRY_RUN=true python pipeline.py
```

## Code structure

- `core.py` — shared configuration, Notion parsing, AI prompt/schema and validation.
- `pipeline.py` — stage ownership, Notion queue processing and writes.
- `smoke_test.py` — read-only Notion/OpenAI integration validation.

## Model

The default model is `gpt-5.6-luna` for this structured classification/drafting workload. Override with `OPENAI_MODEL` if required.
