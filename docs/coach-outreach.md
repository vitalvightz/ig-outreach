# Personalised coach DMs

The normal `pipeline.py` poll now runs a separate coach handler after athlete
processing. It shares the existing Notion token/session, OpenAI client and model,
with coach drafts capped by the existing per-run candidate limit. Athlete
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
The model selects one supplied detail and rewrites it as a simple 4–9-word
observation. Recent fights, coaching content, gym activity and achievements take
priority when supplied; a gym reference is enough otherwise. It treats the angle
as research rather than copy, avoids credential lists and robotic relationship
phrases, and never assumes multiple fighters. Structured output includes only
the first word of a clear personal name (or `there` for an organisation/unclear
name) and the observation. The general rule is one relevant fact, expressed
conversationally, with enough identifying context to recognise it. It removes
secondary information rather than copying the whole research or becoming vague.
This applies equally to events, gym activity, coaching content and achievements.
There are no event-, venue- or broadcaster-specific keyword bans: a detail can
stay when it is the point of the observation. Personal names
appear only once, as a first-name greeting. Code checks greeting, word count,
repeated personal names and robotic relationship phrases, with one
bounded style retry, and appends exactly:

> We’re inviting a few combat coaches to get early access to Unlxck. We’re building tools to help coaches keep track of their fighters’ training, recovery and fight prep in one place. It’s free to get involved and you’ll have a say in what we build for coaches. Want me to send you the details?

Only `Draft DM` is written. Changing the angle (or supplied name) regenerates an
unchanged AI draft; unrelated edits do not call AI. Existing nonempty drafts are
treated as manual. Once a change or deletion of an AI draft is observed, that
record is held as manual even if the angle subsequently changes. Sending stays
manual and the handler never changes Status. Prompt/offer changes regenerate
unchanged worker-owned drafts once on the next poll; manually edited drafts and
contacted coaches remain protected. The existing persistent state must be retained.

## Writing the personalisation angle

Record one concrete detail in plain English: a recent fight, a coaching post,
gym activity or an achievement. Include the date/context if relevant. A gym alone
is fine when that is all you know. For example: `Head coach at Bideford Boxing
Club` gives the model enough to write `saw you’re coaching at Bideford Boxing Club`.
Do not paste a full biography, credentials, lists of clubs or raw search-result
text such as `associated with`. These encouraged the earlier drafts to repeat
research verbatim instead of sounding like a conversation. The worker still
accepts such notes; cleaner notes make a more useful opening.

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
