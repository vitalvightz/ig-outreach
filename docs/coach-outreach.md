# Personalised coach DMs

The normal `pipeline.py` poll now runs a separate coach handler after athlete
processing. It shares the existing Notion token/session, OpenAI client and model,
with coach calls capped by the existing per-run candidate limit. Athlete
qualification, statuses and counters are unchanged.
Counter-only runs and targeted athlete runs do not process coaches. Keep the
existing Hetzner weekday two-minute schedule and deployment configuration.

The Coaches CRM data source defaults to
`418d6e71-8d27-816c-98fb-000b08e2fb0b` (override with
`NOTION_COACHES_DATA_SOURCE_ID`). The handler adds only `Personalised DM Angle`
and `Draft DM` as rich text if missing, and refuses to replace incompatible types.
Both fields were added to the live Coaches CRM during implementation. Existing
statuses, views and records were preserved; no live drafts were generated.

Only `To Contact` coaches with no `Last Contacted` date, a supplied Coach / Gym
name and a nonblank personalisation are drafted. Any personalisation text is
accepted without profile, sport, qualification, research or evidence checks.
The model rewrites only the observation using supplied information. Code uses
the supplied Coach / Gym label verbatim for the greeting and appends exactly:

> We're speaking with a few combat coaches to see how Unlxck could support their fighters' training and recovery. Would you be open to hearing more?

Only `Draft DM` is written. Changing the angle (or supplied name) regenerates an
unchanged AI draft; unrelated edits do not call AI. Existing nonempty drafts are
treated as manual. Once a change or deletion of an AI draft is observed, that
record is held as manual even if the angle subsequently changes. Sending stays
manual and the handler never changes Status.

## Deployment requirements

After PR review and merge, deploy the reviewed revision to the **existing**
Hetzner outreach worker checkout/virtualenv using its current deployment process.
Do not install another service, timer or token. Existing dependencies suffice.

- Grant the existing Notion integration access to the Coaches CRM (and schema
  update permission if deploying against a copy missing the two fields).
- Set `OUTREACH_COACH_STATE` in that worker's existing environment to a persistent,
  absolute, writable path, for example
  `/opt/unlxck/outreach-worker/state/coach-drafts.json`. The default is
  `var/coach-drafts.json` relative to the checkout. Keep it across deployments and
  backups; it contains personal message copy and is written with mode 0600.
- All local invocations must use the same path. A file lock serializes coach
  processing. Keep only the existing worker active; do not run a live GitHub
  fallback against coaches while Hetzner is polling. Different hosts cannot
  share this lock/state.
- First use `DRY_RUN=true python pipeline.py` with the normal worker environment.
  Coach preview reports eligible pending page IDs without AI calls, Notion writes
  or state changes. Then test one unsent coach under the existing poll: add an
  angle, confirm the exact fixed introduction/invitation, poll again, change the
  angle, manually edit the message, and confirm that subsequent angle changes
  preserve the manual copy. Check logs for errors and athlete/counter regression.

Generated copy is saved before Notion PATCH; failed writes reuse it, and a lost
PATCH response is recovered by comparing the current draft. The state must not be
deleted to force regeneration: after state loss, existing drafts are conservatively
treated as manual. Corrupt state stops coach processing without affecting athlete
writes. Restore the last good state backup after checking the current CRM.

Notion provides no conditional page PATCH. The handler re-reads status, contact
date, name, angle and draft immediately before writing, but an edit in the narrow
read-to-write interval cannot be ruled out. Polling also cannot observe edits
changed back entirely between polls. Avoid editing a coach while its draft is
being generated. A process crash after an AI response but before its durable save
can require another AI call; successful saved generations and write retries do not.

Validation: `python -m unittest discover -s tests -v`. Rollback restores the prior
code revision; retain the additive CRM fields and state file. No database migration
or scheduling change is required, and this PR does not deploy or merge itself.
