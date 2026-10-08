# Qualified outreach counter: review and rollout

This change is not deployed by a pull request. No migration or scheduler changes run
on import, CI, merge, or a normal worker pass. Review the paths/user in the supplied
systemd templates against the actual Hetzner installation before installation.
The repository previously contained no Hetzner service or timer definitions.

## Why the old number was unsafe

The old query selected pages by `created_time` in the London day and counted any
row with Candidate, Verified Profile URL and Personalised DM Angle. It did not
validate the URL, require AI approval/outputs, consider Stage, exclude duplicate
profiles, or attribute a later repair to its actual completion day. A rejected row
with all three fields could inflate employee productivity, and an older row fixed
today could earn no credit. The existing weekday scheduler could leave Friday's
number visible all weekend. Partial pagination also silently returned partial counts.

## Meaning of the new number

`Today` and the existing chart-free counter row/icon remain unchanged. The worker
updates only that row's Candidate title (`22 / 50 complete`) and numeric backing
field. Target stays 50. Profile URL, Daily Complete, other formulas, view filters,
view sorts, prospect stages, and intern data are not changed by this migration.
The old Daily Complete formula is not a source for this counter.

A contributor must have valid human inputs, a handle matching the verified URL,
Boxing sport, complete AI outputs, and a worker-written structured success receipt
bound to that page and the current inputs/outputs. Neither free text nor score
thresholds establish success. Stage must be one of Ready to Send, Contacted,
Replied, Applied, Accepted, Reserve or Activated. The existing fight-date safety
check still applies to unsent Ready to Send drafts; sent prospects do not lose
qualification merely because a fight date later passes.

Approval and Qualified At are written in the same prospect PATCH. A valid stage
progression preserves the date. An observed disqualification clears the date and
marks its receipt inactive. Returning identical, already-approved data to a valid
stage gives a new timestamp; changed research or outputs need an AI Queue recheck.
A real AI rejection/failure to qualify clears the approval. An API/AI exception
cannot create approval. The date mirror is repaired from the receipt on retries.
Requalifications use the observed Notion edit timestamp; successful AI approvals
use the timestamp when the result is written, not creation time. All dates are UTC
instants; day boundaries use Europe/London's timezone database (23/25-hour DST days).

Profiles are deduplicated by the verified URL's lowercase Instagram username,
ignoring host variants, trailing slash and tracking parameters. The earliest
currently qualified copy owns credit; a historical or undated legacy owner
prevents a new duplicate earning today's credit. If the owner loses qualification
or is archived/deleted, another currently qualified copy may own credit. This is
one count per profile, across candidate names. No prospect rows are deleted/merged.

## Additive schema and historical backfill

Two new system-owned fields are required:

- `Qualified At`: date. Cleared when revoked; immutable during valid progression.
- `AI Qualification Receipt`: rich_text. Versioned structured success, fingerprints,
  current qualification timestamp, and legacy/revoked state. Hide both fields from
  the intern views if Notion displays newly added properties automatically.

The script adds only missing fields. It refuses mismatched existing property types
and never replaces a formula, view, or existing prospect property.

1. Stop the current Hetzner worker and disable any live manual GitHub fallback.
   Back up the deployment and export Notion prospect data. Pick a maintenance
   window before a new UK day so historical ambiguity cannot distort today's KPI.
2. Install this revision and existing requirements with Python 3.12 and system
   timezone data. Use the existing Notion credentials; the migration needs no
   OpenAI key. Preview schema additions, then explicitly apply them:

   ```bash
   python migrate_counter.py
   python migrate_counter.py --apply-schema
   python migrate_counter.py --export counter-inventory.json
   ```

3. Make a separate `counter-approvals.json` from the inventory. Audit each included
   prospect against its original successful structured AI response/worker logs.
   Only approved rows belong in this manifest. Set eligible/evidence_sufficient
   to true and supply an evidence_reference identifying the reviewed approval.
   Leave rows with no proof out; a plausible reason, draft or high score alone is
   not proof. Their current Stage and data stay untouched. They must receive an
   audited AI requalification before being included in the new counter; manually
   advanced rows must not be grandfathered as approved.
4. Use an original timezone-aware qualification timestamp only when provable.
   Never infer it from creation time or last_edited_time. Unknown historical times
   stay null: the receipt is marked legacy, approval survives, and the row receives
   no daily credit until it is revoked and qualifies again. For an optional fresh
   AI audit of a legacy row, record that result as historical validation with null
   time; do not claim today's productivity for it. The script does not bill OpenAI.
   Every supplied date must precede the manifest's fixed export cutoff. An example:

   ```json
   {
     "cutoff": "2026-10-08T22:00:00+00:00",
     "pages": {
       "<page-id-from-inventory>": {
         "fingerprint": "<unchanged-fingerprint-from-inventory>",
         "eligible": true,
         "evidence_sufficient": true,
         "evidence_reference": "<original AI approval log/reference reviewed>",
         "qualified_at": null
       }
     }
   }
   ```

5. Validate the whole manifest before writes and review the preview:

   ```bash
   python migrate_counter.py --manifest counter-approvals.json
   python migrate_counter.py --manifest counter-approvals.json --apply
   ```

   Changed fingerprints or regressed stages stop the batch. The script rechecks
   each row before writing. Re-running skips rows already carrying an approval,
   so a partial API failure can be safely resumed without changing existing dates.
   Keep inventory/manifest private and outside Git; defaults are gitignored.
6. Initialize the persistent cache, first previewing and then publishing:

   ```bash
   COUNTER_ONLY=true DRY_RUN=true OUTREACH_COUNTER_STATE=/var/lib/unlxck-counter/daily-counter.sqlite3 python pipeline.py
   COUNTER_ONLY=true OUTREACH_COUNTER_STATE=/var/lib/unlxck-counter/daily-counter.sqlite3 python pipeline.py
   ```

   Run as the service account with write permission on that directory. The first
   pass scans once; subsequent passes query edits since a durable checkpoint with
   a five-minute overlap. Losing the cache triggers another full scan, recovering
   dates from Notion, without treating historical rows as newly qualified.

## Hetzner schedule

Keep the existing AI worker on weekdays. Set `OUTREACH_EXTERNAL_COUNTER=true` in
that worker's environment so its AI calls do not delay or duplicate counter syncs.
Add the supplied counter-only timer to run every two minutes, 24/7. COUNTER_ONLY
requires only the Notion key and cannot call OpenAI. Default normal worker behavior
still updates the counter once after processing if no separate timer is installed.

The example files assume `/opt/ig-outreach`, `.venv`, user `unlxck`, and the existing
secret environment file `/etc/unlxck/outreach.env`; adapt these to actual server
paths. Review, then install `deploy/unlxck-counter.service` and `.timer` under
`/etc/systemd/system`, run `systemctl daemon-reload`, and enable/start
`unlxck-counter.timer`. These are deployment steps for the operator, not PR automation.

Systemd prevents overlapping invocations of the same oneshot service. SQLite
serializes concurrent local counter passes. All counter processes on Hetzner must
use the same absolute state path. Live GitHub fallback remains available, but stop
the Hetzner worker and counter timer before using it and restart them afterwards:
GitHub runner state and locks cannot serialize with a different host. Manual
workflow runs are serialized with each other. Dry runs do not advance checkpoints
or modify Notion. Do not run two live AI workers for the same database.

## Recovery and acceptance checks

A complete current-day date query detects archive/deletion removal without one
request per contributor. Only historical duplicate owners for today's profiles
need extra batched handle queries. Retries pace requests and handle bounded
network/5xx/429 failures and Retry-After; pagination must be complete and cursors
must advance. Fetch failures occur before publishing. A failed metadata/UI write
rolls back the cache checkpoint; partial successful metadata writes are recovered
from their Notion receipts. The previous displayed value remains on failure;
logs and nonzero process exit indicate that it is stale. Never substitute zero
for a failed query. After recovery the next complete pass recomputes the number.

Check `journalctl -u unlxck-counter.service` and timer status. Confirm a genuinely
approved test row increments, Needs Research decrements, unchanged Ready to Send
requalification increments once, Contacted/Replied preserves credit, and archive
removal decrements. Verify the intern's Add/Fix and Send DMs views and the existing
Profile URL formula. Confirm London midnight resets and weekend timer activity.
Unit regression coverage runs with `python -m unittest discover -s tests -v`.

Polling observes current state, not every intermediate edit: a revoke-and-restore
performed entirely between two polls is invisible to Notion's query API. Exact
attribution of every such event would require durable Notion change events/history,
which this repository does not have. Concurrent Notion edits can also occur between
read and PATCH because the API has no conditional write/version check; worker
results recheck current research/stage before writing, and subsequent syncs repair
state. Keep metadata system-owned and restrict intern edits to intended fields:
receipts prevent accidental stage advancement/copying, not deliberate fabrication
by someone with permission to edit all database properties. Instagram URL parsing
verifies structure/identity, not public-profile existence; the existing human
verification responsibility is preserved.

Do not use an unaudited legacy migration or stale display to make performance
judgments. No exact historical timestamp can be reconstructed from the old fields.

## Rollback

Stop the counter timer and worker. Restore the previous application revision and
previous scheduler configuration; retain both new metadata fields, manifests and
cache backup. They are additive and do not alter prospect data/formulas. The old
counter's productivity limitations return on rollback; do not use its number as a
qualification-based KPI. Reapplying the migration and this revision is idempotent.
