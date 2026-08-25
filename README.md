# UNLXCK Outreach AI

Internal outreach automation for the UNLXCK private beta.

## Architecture

`Notion candidate pipeline -> OpenAI qualification/drafting -> Notion Ready to Send view -> human Instagram send`

Google Sheets is no longer part of the workflow.

## What the automation does

For each candidate whose **Stage = Found** it:

1. Checks that an Instagram profile/handle, sport and genuine recent public personalisation detail are present.
2. Uses one OpenAI Responses API call with Structured Outputs.
3. Writes:
   - `Priority Score`
   - `AI Qualification Reason`
   - `Outreach Approach` (`A` or `B`)
   - `Draft DM`
4. Changes the pipeline stage to:
   - `Ready to DM` when qualified and supported by evidence
   - `Researching` when more public evidence is required
   - `Rejected` when the prospect is not a fit
5. Leaves the actual cold Instagram send to a human.

The automation is explicitly instructed not to invent athlete facts or reuse the old 7-0 / 8% power claim.

## Required GitHub secrets

- `OPENAI_API_KEY` — already used by the previous version of this repo.
- `NOTION_API_KEY` — token for a Notion integration that has access to the UNLXCK Beta Candidate Pipeline.

Never commit either secret to the repository.

## One-time Notion setup

1. Create or reuse an internal Notion integration.
2. Share **UNLXCK Beta Candidate Pipeline** with that integration.
3. Add the integration token to this repository as the `NOTION_API_KEY` Actions secret.

The current Notion data-source ID is configured in the workflow and can be overridden with `NOTION_DATA_SOURCE_ID`.

## Schedule

GitHub Actions runs hourly from 08:00 through 17:00 UTC on weekdays and can also be started manually.

Only `Found` records are processed, so completed/rejected/researching records are not repeatedly billed through the OpenAI API. If a `Researching` record is fixed and should be reprocessed, set its Stage back to `Found`.

## Local run

```bash
pip install -r requirements.txt
export OPENAI_API_KEY="..."
export NOTION_API_KEY="..."
python main.py
```

For a no-write test:

```bash
DRY_RUN=true python main.py
```

## Model

The default model is `gpt-5.6-luna`, chosen for a high-volume, structured classification/drafting workload. Override with `OPENAI_MODEL` if required.
