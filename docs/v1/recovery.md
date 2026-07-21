# Recovery, background work, and diagnostics

## Recovery snapshots

Desktop documents receive a debounced recovery snapshot two seconds after an
edit. Snapshots and their schema-versioned metadata are written atomically and
identify the document, original path, application version, and save time. The
recovery store keeps at most 20 documents and prunes entries older than 30 days.
A failed or disk-full snapshot leaves the previous consistent snapshot intact.

On the next launch, Photoslop offers each recoverable document. Accepting opens
it as unsaved recovered work. Declining is a confirmed discard and removes the
snapshot and metadata. A successful project save also clears its recovery data.
Recovery is a last-crash safety net, not a substitute for saving a project.

## Background tasks

View → Background Tasks shows queued and running operations, priority, scope,
progress, and the bounded history for the current session. The dialog can
cancel one operation, every operation for the selected document/scope, or all
active work. Cancellation is cooperative: a backend that cannot stop
immediately is still prevented from installing a stale result. Project writes
commit atomically, so cancellation before commit preserves the destination and
a completed commit is reported as success.

## Durable diagnostics

Help → Diagnostics retains up to 200 redacted operation results and failures in
a mode-0600 JSONL file under the Photoslop settings directory. Failed records
include the safe operation context, full cause chain, and next-step guidance;
task success and cancellation records provide an attributable result history.
Autosave successes are intentionally omitted to prevent them from crowding out
user operations. Passwords, tokens, authorization headers, URL credentials,
and secret-valued context keys are removed before persistence.
