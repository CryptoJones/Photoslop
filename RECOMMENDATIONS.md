# Photoslop Codebase Audit and Recommendations

Reviewed: 2026-07-20

Primary audit target: `github/main` at `a21a574` (v1.29.1 source)

Desktop comparison target: `fix/text-layer-move-effects` at `84c4067`

## Executive verdict

Photoslop has a broad, well-tested desktop feature set, but it is not yet at a
safe release baseline. The most urgent defects are data-integrity problems:
some layer edits can be discarded without an undo entry or unsaved-change
prompt; saves overwrite their destination non-atomically; background work can
apply stale results; and the iPad app lacks project persistence, dirty-state
handling, and unified undo. Release metadata and automation also disagree about
the current version, and the portable release workflow is missing the token
permission needed to upload tagged artifacts.

The recommended order is:

1. Fix the five P0 release blockers below.
2. Harden all untrusted inputs and remote/native execution boundaries.
3. Make the release pipeline reproducible and enforce the claimed support
   matrix.
4. Address accessibility, performance evidence, recovery, and architectural
   debt before expanding the feature surface.

## Implementation record — 2026-07-21

The implementation was delivered as a reviewable local branch stack based on
the audited `github/main` commit. “Implemented” below means the code and local
automated evidence exist; it does not substitute for OS-specific signing,
assistive-technology, App Store, or hosted GitHub Actions evidence.

| Recommendation | State | Implementation/evidence |
|---|---|---|
| P0.1, P0.3 | Implemented | `b2bf5dc`: typed property undo, document/layer identity and revisions, captured async inputs, stale completion rejection, close/task scopes, and regression tests. |
| P0.2 | Implemented | `8002c14`: durable atomic replacement, per-path write coordination, checked encoders, collision-safe artboards, and failure/cancellation tests. |
| P0.4 | Implemented; Xcode evidence pending | `bb3b865`: versioned `.photoslop` `FileDocument` package, atomic persistence/autosave, dirty prompts/restoration, unified undo, background rendering/export, and Swift tests. |
| P0.5 | Implemented; disposable tag proof pending | `aad7006`: v1.30.0 source of truth, cross-surface version gate, and least-privilege tag-only release permission. |
| P1.1–P1.5 | Implemented | `8b2cdf5`: shared adaptive resource budgets, hardened XML/archive/SVG/data/image/model validation, constrained MCP roots, and default-denied unsafe plugin/native operations. |
| P1.6 | Implemented; device evidence pending | `bb3b865`: bounded off-main iPad render/import/export and package encoding with stale-result guards. |
| P1.7 | Implemented; manual AT matrix pending | `815b587`: desktop/iPad semantics, keyboard canvas workflows, scalable UI/handles, focus/high contrast/reduced motion, reversible gesture cancellation, and the manual AT evidence matrix. |
| P1.8 | Implemented; signed artifacts pending | `419d740`: locked PyInstaller builds, packaged pixel round-trip smoke, full generated notices, CycloneDX SBOM, build identity, checksums, fail-closed signing/notarization/Authenticode, and provenance attestation. |
| P2.1–P2.4 | Implemented | `419d740`: Python 3.10/latest plus Linux/macOS/Windows CI, wheel/sdist smoke, honest removal of unusable mypy config, branch-coverage floors, and enforced real TaskService/RSS benchmarks. |
| P2.5–P2.6 | Implemented | Atomic versioned recovery snapshots with metadata, retention/pruning/recovery/discard behavior, plus centralized version and surface-parity documentation. |
| P2.7 | Increment delivered | Service boundaries now isolate file/export/filter/model operations, task scheduling/monitoring, diagnostics, structured errors, recovery, actions, tools, accessibility, and workspace state. Further monolith reduction remains incremental maintenance, not a rewrite gate. |
| P2.8–P2.10 | Implemented | Durable redacted diagnostics/result history, attributable plugin failures, explicit invariant errors, zero CLI deprecations, structured CLI/MCP codes, scheduled security maintenance, and adversarial/state-transition coverage. |
| P3.1 | Implemented | `4c3c7e8`: one repository-wide Ruff formatting baseline with lint and format CI gates. |
| P3.2–P3.3 | Implemented | Priority/FIFO memory-aware scheduling, head-of-line bypass, visible task/session history, task/scope/global cancellation, durable outcomes, unique/platform-safe shortcuts, and command-palette/menu discovery. |

Final local automated evidence on Linux, Python 3.12.13, PySide6 6.11.1:

- full suite with loopback integrations: **3,122 passed, 13 skipped**;
- critical branch-coverage suite: **82 passed**, all 11 measured module floors;
- Ruff lint and formatting: **192 files pass**;
- Bandit medium/high gate and complete tracked/untracked secret scan: pass;
- `pip-audit` of the exact locked all-extras export: no known vulnerabilities;
- v1.30.0 wheel and source distribution build, plus out-of-tree 8×8 exact-pixel
  CLI round trip: pass;
- enforced full-resolution 4K/10-layer and 12-MP/4-layer latency, RSS,
  cancellation, and output gates: pass.

The remaining release evidence is deliberately fail-closed and is not claimed
from this Linux workspace:

- macOS codesign/notarization and Windows Authenticode portable artifacts;
- a disposable tag proving GitHub release upload and provenance end to end;
- Xcode simulator/device execution of the iPad persistence/rendering tests;
- VoiceOver, NVDA, Orca, high-contrast, 200%-text, and reduced-motion manual rows;
- hosted matrix/security/portable/scheduled performance jobs on the final commit.

Those rows remain release-candidate evidence owned by hosted workflows and
manual platform reviewers; this implementation record does not pre-claim them.

Priority meanings:

- **P0 — release blocker:** credible data loss, corruption, stale mutation, or
  broken release behavior.
- **P1 — next release:** security boundary, major reliability, platform
  viability, or a substantial mismatch between documented and actual behavior.
- **P2 — scheduled:** quality, maintainability, diagnostics, or defense in depth.
- **P3 — polish:** useful cleanup after correctness is under control.

## Audit baseline

The following checks were run against the clean desktop worktree, with current
`github/main` exported separately so the v1.29.1 release and native iPad code
could also be reviewed without changing the user's branch.

- Git freshness: fetched all remotes and pruned; the working branch's v1.28.0
  commit is patch-equivalent to the corresponding squash commit on `main`.
- Tests: **3,070 passed, 13 skipped**. Four HTTP tests initially failed only
  because the sandbox denied loopback sockets; all four passed with loopback
  permission. The suite emits **101 deprecation warnings**, all from the old
  `QImage.mirrored(bool, bool)` overload in `photoslop/cli.py`.
- Lint and packaging: Ruff lint passed, `uv lock --check` passed, and wheel plus
  source distribution builds passed.
- Dependency audit: no known vulnerabilities were reported for the resolved
  environment. The local Photoslop package is naturally not found on PyPI.
- Security scan: no embedded secrets were found. Bandit reported no high-severity
  findings, four medium XML/URL findings, and 27 low-severity findings.
- Shell/config validation: ShellCheck, `bash -n`, plist parsing, and asset JSON
  parsing passed.
- Current GitHub evidence: main CI passed; the manually dispatched macOS and
  Windows portable build completed; the v1.29.0 iPad tag build and tests passed,
  but its release upload failed before the later permission fix.
- Not locally executable: Xcode/iPad, Swift, PowerShell, and packaged GUI binaries.
  Recommendations for those areas are based on source and workflow review.

Passing checks are not evidence that the P0 cases are safe: the current tests do
not exercise dirty state, interruption, concurrent writes, or stale async
completion in the affected paths.

## P0 — release blockers

### P0.1 — Route every document mutation through undo and dirty tracking

**Evidence**

- `photoslop/propertiespanel.py` directly assigns layer name, visibility,
  opacity, and blend mode, then emits a structure notification.
- `photoslop/layerpanel.py` directly assigns the same properties; some paths
  emit a pixel notification and layer rename does not consistently notify.
- These paths do not push a `QUndoCommand`. A direct reproduction changed layer
  opacity to 50% while `Document.is_dirty()` remained false and
  `undo_stack.canUndo()` remained false.

**Risk**

The close prompt can treat a modified document as clean and discard the user's
work. The same edits cannot be undone and are inconsistent with command-driven
canvas operations.

**Recommendation**

- Add command objects for name, visibility, opacity, and blend-mode changes, or
  one typed layer-property command.
- Use the same command path from both panels and any keyboard/menu actions.
- Merge consecutive opacity slider updates into one undo step without hiding
  the initial dirty transition.
- Make mutation APIs difficult to call without notifying revision, dirty state,
  and observers.

**Acceptance checks**

- Each property edit marks a clean document dirty, produces exactly one logical
  undo step, and restores both the value and rendered output on undo/redo.
- Closing after only one of these edits asks to save.
- Tests cover both panels, slider merging, layer rename, and the save-point
  transition after saving and then editing again.

### P0.2 — Make all writes atomic, checked, and serialized per destination

**Evidence**

- `photoslop/io_ora.py`, `photoslop/io_svg.py`, `photoslop/io_formats.py`,
  `ExportService.write()` in `photoslop/services.py`, and CLI output paths write
  directly to the final destination.
- Cancellation is checked cooperatively around task work, but a writer can
  modify the final file before the next cancellation check reports the task as
  cancelled.
- The UI can start overlapping saves, including multiple writes to the same
  destination.
- CLI artboard export sanitizes names without resolving collisions and does not
  consistently check `QImage.save()`; two artboards can silently overwrite one
  another while the command reports success.

**Risk**

A crash, disk-full event, failed encoder, cancellation, or racing save can
truncate or replace the user's last good file. Artboard export can silently lose
outputs.

**Recommendation**

- Write to a uniquely named temporary file in the destination directory, flush
  and close it, then atomically replace the target only after full success.
- Preserve the previous file and report a clear error if encoding, flush, close,
  or replacement fails. Consider `fsync` for project documents where durability
  is expected.
- Serialize writes by canonical destination and disable or coalesce duplicate
  Save actions. Save immutable snapshots so a later UI mutation cannot change
  the in-flight payload.
- Define cancellation precisely: before commit leaves the destination untouched;
  after atomic commit is success, not “cancelled.”
- Deduplicate sanitized artboard names deterministically, check every encoder
  return value, and fail the command if any requested output failed.

**Acceptance checks**

- Fault-injection tests at encode/write/flush/replace leave the original file
  byte-for-byte intact and remove temporary files.
- Concurrent saves to one path cannot interleave or let an older snapshot finish
  last unnoticed.
- Cancellation before commit never changes the destination.
- Colliding artboard names produce distinct files; an encoder failure gives a
  non-zero CLI exit and no false success path.

### P0.3 — Reject stale background results with one document revision model

**Evidence**

- `photoslop/tasks.py` provides cooperative execution, but completion guards in
  `photoslop/mainwindow.py` are ad hoc `QImage.cacheKey()` comparisons.
- A filter can finish after its target layer was deleted or reordered; the
  captured layer object can then be changed or recorded in undo despite no
  longer belonging to the document.
- Generative fill sends one captured mask/selection to the backend, then its
  completion path recomputes the current selection when applying the result.
- Select-subject guards only a tuple of layer image keys, missing offsets,
  order, visibility, opacity, effects, document structure, and other composite
  inputs. Denoise has similarly incomplete validation.
- Closing or quitting does not establish an explicit policy for in-flight tasks.

**Risk**

Slow work can mutate the wrong layer, apply a result to a different selection,
or install a mask derived from an obsolete composite. This is silent document
corruption, not merely stale display.

**Recommendation**

- Add a monotonic document revision and specific sub-revisions where useful
  (pixels, structure, selection). Every mutation path must increment the
  relevant revision through one API.
- Capture immutable input, document identity, target layer identity, membership,
  selection, and revision at dispatch. On completion, discard results unless
  every relevant precondition still holds.
- Apply generative results using the exact captured selection and geometry used
  for the request, never a recomputed current selection.
- Define close/quit behavior: cancel and wait safely, or detach tasks while
  guaranteeing they cannot commit into a closed document.

**Acceptance checks**

- Tests mutate selection, offsets, layer order, visibility, effects, pixels,
  active layer, and document structure while each async operation runs.
- Deleting the target layer or closing the document always discards completion.
- Discarded results create no undo command, dirty transition, or status message
  implying success.

### P0.4 — Add real iPad project persistence, recovery, and undo

**Evidence**

- The native app in `ipados/Photoslop` exports a flattened PNG but has no layered
  project save/open format, dirty flag, unsaved-change prompt, autosave, state
  restoration, or unified `UndoManager` integration for layer operations.
- New/Open/import can replace the current editing state immediately.
- Command-S maps to Export PNG, which is not a recoverable project save.
- Existing iPad tests cover only basic store behavior, not persistence or data
  loss scenarios.

**Risk**

Background termination, a crash, document replacement, or an accidental new
operation can destroy the only editable copy. A flattened PNG cannot restore
layers or PencilKit data.

**Recommendation**

- Define a versioned layered document package. Prefer interoperability with ORA
  where feasible, with an explicit extension for PencilKit/vector data; otherwise
  document a native iPad format and provide import/export boundaries.
- Implement atomic save, autosave/recovery, dirty tracking, state restoration,
  and save/discard/cancel prompts before replacement or dismissal.
- Integrate layer and drawing changes with `UndoManager`.
- Rename Command-S to Export only if no project save exists; once save exists,
  reserve Command-S for it.

**Acceptance checks**

- Round-trip tests preserve layer order, names, visibility, opacity, pixels,
  drawings, canvas size, and metadata.
- Forced termination and simulated failed saves recover the last consistent
  state without corrupting the previous project.
- New/Open/import and app dismissal cannot silently discard a dirty document.
- Undo/redo spans both drawing and layer operations with correct dirty state.

### P0.5 — Establish one release version and make tag uploads work

**Evidence**

- On audited `main`, `pyproject.toml` declares 1.29.1 while
  `photoslop/__init__.py`, the README badge, and several docs still report
  1.29.0; feature-parity documentation still names 1.28.0. Runtime CLI/window
  version comes from `__version__`, so a 1.29.1 wheel identifies itself as
  1.29.0.
- iPad build settings remain at 1.29.0 while the repository source version is
  1.29.1, without an explicit independent-version policy.
- `.github/workflows/portable.yml` uploads assets with `gh release upload` on
  tags but does not grant `contents: write`. Repository defaults are read-only,
  so the next tagged upload is expected to fail just as the original iPad upload
  did before its permission fix.

**Recommendation**

- Choose one authoritative version source and derive Python runtime metadata,
  packaging, app metadata, docs, badges, and release names from it. If desktop
  and iPad versions intentionally differ, encode and document that policy.
- Add a release gate that compares tag, distribution metadata, runtime
  `--version`, changelog, and platform bundle versions.
- Grant `contents: write` only to a minimal tag-only portable release job; keep
  build/test jobs read-only.
- Do not publish v1.29.1 until the version and upload checks pass.

**Acceptance checks**

- An installed wheel, source checkout, desktop About UI/CLI, tag, changelog, and
  generated docs all report the intended version.
- A dry-run or disposable prerelease tag proves both portable artifacts upload.
- Pull-request jobs retain read-only permissions.

## P1 — security, reliability, and platform viability

### P1.1 — Bound and safely parse every untrusted document

**Evidence**

- ORA import and preview parse ZIP/XML and read entries, metadata, thumbnails,
  profiles, and layer images without consistent limits on archive size,
  per-entry size, total uncompressed bytes, compression ratio, layer count,
  dimensions, metadata length, or memory estimate.
- ORA and SVG use the standard XML parser on untrusted content; Bandit flags the
  relevant ElementTree calls.
- SVG import reads the full file, can decode embedded base64 images, and may
  allocate a canvas or hand content to `QSvgRenderer` before enforcing a complete
  resource budget.
- AVIF/JXL preview decodes the full image before scaling it down.

**Recommendation**

- Introduce shared import budgets: compressed bytes, uncompressed bytes,
  compression ratio, file count/layers, dimensions, total pixels, metadata,
  XML nodes/depth, embedded payloads, and estimated decoded memory.
- Reject ZIP traversal, duplicate/conflicting entries, encrypted entries, and
  unexpected entry types before extraction/decoding.
- Use a hardened XML parser or explicitly reject DTD/entity declarations and
  enforce byte/node/depth limits before building large trees.
- Use codec-level thumbnail/downsample support rather than decode-then-scale.
- Return an actionable “document exceeds safe limits” error, not an allocation
  failure or crash.

**Acceptance checks**

- Corpus tests cover ZIP bombs, huge dimensions, deep XML, entity payloads,
  oversized metadata/base64, malformed profiles, and high layer counts.
- Preview and full import honor separate documented budgets.
- Fuzz/property tests cannot cause unbounded allocation or uncontrolled parser
  exceptions under the configured cap.

### P1.2 — Enforce canvas and allocation limits at every entry point

**Evidence**

- The new-document UI permits very large unit values and up to 2400 DPI; inches
  or centimeters can convert to implausibly large pixel dimensions.
- CLI size parsing and DPI options lack a shared dimension/product/memory cap;
  MCP inherits those paths.
- Individual dimensions alone are insufficient because width × height × layers
  × working buffers determines actual memory use.

**Recommendation**

- Centralize checked dimension conversion and estimate peak bytes for canvas,
  layers, undo snapshots, masks, effects, and temporary buffers.
- Apply the same policy to GUI, CLI, MCP, imports, resize, plugins, and model
  outputs. Validate finite positive DPI and dimensions before integer conversion.
- Offer an explicit advanced override only with a clear memory estimate and
  confirmation; never rely on a failed/null `QImage` as validation.

**Acceptance checks**

- Boundary tests cover unit conversion, overflow, negative/NaN/infinite values,
  huge aspect ratios, many layers, and operations requiring multiple buffers.
- GUI, CLI, MCP, and imports reject the same unsafe request consistently.

### P1.3 — Harden model endpoints and validate all responses

**Evidence**

- `photoslop/modeladapter.py` accepts general URL schemes through `urllib`, reads
  response bodies without a strict byte limit, and base64-decodes payloads
  without a decoded-size budget.
- Generative fill validates result size, but denoise can replace a layer with a
  differently sized result, and select-subject does not require a document-sized
  mask.
- Content type, schema shape, image format, pixel count, and finite geometry are
  not consistently checked across operations.

**Recommendation**

- Allow only `http` and `https`; default to loopback or HTTPS. Require an explicit
  warning/opt-in for non-loopback plaintext HTTP because image and mask data may
  be sensitive.
- Add connection, read, and total timeouts plus status, content-type, body-byte,
  decoded-byte, image-dimension, and schema limits.
- Validate every output as non-null, expected format, exact expected dimensions,
  and within the global allocation budget before changing a document.
- Store authentication in OS-backed secret storage or environment/config
  references, never project files or logs. Redact URLs/headers where needed.

**Acceptance checks**

- Tests cover unsupported schemes, redirects, slow/large/truncated bodies,
  invalid JSON/base64, wrong content type, wrong image/mask size, decompression
  bombs, and non-2xx responses.
- Every invalid response leaves document, undo stack, and dirty state unchanged.

### P1.4 — Default-deny unsafe MCP/plugin operations and constrain paths

**Evidence**

- The MCP surface exposes CLI operations including raw G'MIC command strings and
  GIMP Script-Fu/plugin escape hatches. These native/plugin surfaces are much
  broader than ordinary image filters and may access files or execute arbitrary
  behavior.
- MCP accepts arbitrary input, output, and export paths without an allowed-root,
  symlink, or overwrite policy stated in its user-facing contract.
- Installed Python entry-point plugins execute trusted package code during
  discovery. Plugin discovery failures are often swallowed, reducing auditability.
- Imported ORA smart-filter metadata can name filters later re-applied by the
  user, crossing from untrusted document data into plugin execution.

**Recommendation**

- Exclude raw/native/plugin execution from MCP by default. Require an explicit
  startup capability such as `--allow-unsafe-plugins`, expose that state to
  clients, and never infer it from a request.
- Add canonical allowed roots, symlink resolution, overwrite rules, and separate
  read/write capabilities. Prefer a dedicated workspace root.
- Treat installed plugins as trusted code, document that boundary, validate
  plugin metadata, and surface load failures in diagnostics.
- Strictly validate imported filter recipes. Mark external/plugin recipes from
  documents as untrusted and require confirmation before native execution.

**Acceptance checks**

- Default MCP cannot access paths outside configured roots or invoke raw G'MIC,
  Script-Fu, executable plugins, or equivalent escape hatches.
- Traversal, symlink escape, case-normalization, overwrite, and TOCTOU tests pass.
- Imported documents cannot trigger plugin execution merely by opening,
  rendering, previewing, or restoring history.

### P1.5 — Make SVG subset handling strict and non-destructive

**Evidence**

- The custom path tokenizer recognizes only `M`, `L`, `C`, and `Z` plus numbers.
  Unsupported letters such as `H`, `V`, `Q`, `S`, `T`, or `A` are not tokenized,
  so following numeric tokens can be silently interpreted under a previous
  supported command instead of forcing a warning/fallback.
- Group-inherited transforms, styles, visibility, opacity, units, and other SVG
  features are only partially represented by the editable-vector subset.

**Recommendation**

- Use a lexer that accounts for every non-whitespace character and rejects any
  unsupported or unconsumed syntax. Never silently reinterpret a path.
- Implement common commands and correct relative/repeated semantics, or reliably
  rasterize unsupported content with a visible import warning.
- Apply inherited group transform/style/visibility/opacity correctly. Validate
  finite view boxes, transforms, dimensions, token counts, and path complexity.
- Explicitly disable or reject external resources in both custom and Qt fallback
  paths.

**Acceptance checks**

- Conformance fixtures cover every path command, relative/repeated commands,
  exponents, compact separators, malformed tokens, nested transforms, inherited
  styles, and unsupported features.
- Import either preserves appearance within a defined tolerance or reports a
  clear fallback; it never silently produces different geometry.

### P1.6 — Redesign iPad rendering around bounded, off-main work

**Evidence**

- `EditorStore` is `@MainActor`; each layer holds a full-canvas `UIImage` plus a
  `PKDrawing`.
- `refreshCanvas()` synchronously recomposites every visible layer and rasterizes
  PencilKit drawings for frequent changes including selection, visibility, and
  opacity adjustments.
- File and Photos import use full `Data`/`UIImage` decoding and normalization on
  the main actor without a shared pixel/memory budget. Full export rendering and
  PNG encoding also occur on the main actor.

**Risk**

Real camera images and multiple layers will cause interaction stalls, memory
pressure, or process termination, especially on lower-memory iPads.

**Recommendation**

- Move decoding, downsampling, compositing, and encoding off the main actor with
  immutable snapshots and revision-checked completion.
- Downsample imports at decode time and enforce the same allocation budget as
  desktop.
- Replace eager full-document recomposition with tiled/viewport rendering,
  dirty-region invalidation, cached layer surfaces, and preview-quality updates
  during continuous controls.
- Measure peak resident memory and frame latency on representative low- and
  high-end physical devices.

**Acceptance checks**

- UI remains responsive during large import, opacity scrubbing, drawing, layer
  toggles, and export; stale completion cannot replace newer state.
- Defined 12 MP/48 MP and multilayer scenarios stay inside memory and latency
  budgets on the oldest supported device.

### P1.7 — Deliver actual canvas and workflow accessibility

**Evidence**

- `AccessibilityController` currently applies global styling, infers some names
  from tooltip/title/text, slows marching ants, and announces status messages.
  Tests mainly prove a generic Qt accessible interface/name exists.
- The custom canvas lacks a meaningful accessibility model for document,
  selection, coordinates, layers, handles, and available actions.
- Several drag workflows have no equivalent keyboard action. Escape in the
  canvas cancels the active tool and then clears selection, even when the
  selection is unrelated.
- The “200% control scale” behavior is chiefly a minimum-height stylesheet, not
  demonstrated full control/text/handle scaling. Dynamically created dialogs
  are not comprehensively audited after startup.

**Recommendation**

- Define semantic roles, names, values, actions, focus order, announcements, and
  keyboard alternatives for the canvas, layer tree, tool options, dialogs, and
  transform/selection workflows.
- Make Escape cancel only the active interaction first; clearing selection
  should be a separate subsequent action.
- Respect OS contrast, reduced-motion, font scaling, and input settings; test
  custom overlays and focus indicators instead of relying on one global palette.
- Correct documentation that marks accessibility work complete until acceptance
  evidence exists.

**Acceptance checks**

- Complete edit/save/export flows work keyboard-only without pointer emulation.
- NVDA/JAWS on Windows, VoiceOver on macOS/iPadOS, and relevant switch-control
  paths have a documented manual test matrix with no critical blockers.
- Automated tests verify semantic roles/actions/state changes, dialog focus,
  dynamic widgets, Escape behavior, 200% text/control scaling, and contrast.

### P1.8 — Make portable distributions reproducible and supportable

**Evidence**

- Portable scripts run `uv sync` without `--locked` and then install
  `pyinstaller>=6.10` separately, allowing build-time dependency drift outside
  the lockfile.
- Release workflows pin actions mostly by moving major tags; XcodeGen is installed
  from an unpinned Homebrew state.
- Portable builds run only manually or on tags, not as pull-request validation,
  and successful artifact creation is not followed by an executable launch and
  representative import/export smoke test.
- macOS and Windows outputs are unsigned; there is no notarization/Authenticode,
  checksum manifest, provenance, or SBOM.
- `THIRD_PARTY_NOTICES.md` covers only Tabler while portable bundles include Qt,
  PySide6, NumPy, Pillow, rawpy, codecs, and other dependencies. Bundle inclusion
  of required license material is not explicitly verified.

**Recommendation**

- Put build tools in a locked build extra with exact compatible versions and use
  `uv sync --locked` everywhere.
- Pin third-party actions by commit SHA and external build tools by reviewed
  version/checksum.
- Build on relevant pull requests or a scheduled cadence and launch the packaged
  CLI/GUI headlessly enough to verify imports, codecs, Qt plugins, and a small
  open/edit/export workflow.
- Add code signing/notarization when artifacts are intended for general users;
  publish checksums, SBOM, and build provenance.
- Generate complete third-party notices from the resolved bundle and have
  qualified counsel or a compliance owner review redistribution obligations.

**Acceptance checks**

- Two clean builds from the same commit and lock produce explainable/reproducible
  dependency inventories.
- Packaged smoke tests execute on both target OSes before release upload.
- Artifacts contain the project license, complete notices, SBOM, version/build
  identity, and verifiable signatures when signing is enabled.

## P2 — engineering quality and maintainability

### P2.1 — Make CI enforce the supported Python/platform matrix

Current CI tests only Ubuntu with Python 3.12 while packaging claims Python
3.10+. Add Python 3.10 and latest supported Python, plus Windows/macOS smoke
coverage. Build and install the wheel/sdist in CI and execute a minimal command
from the installed artifact so source-tree imports cannot mask packaging errors.

### P2.2 — Repair or remove the nonfunctional type-checking contract

Mypy is a development dependency with `python_version = 3.10`, but checking
currently stops on missing GI/lensfun stubs, Python-3.12-only NumPy stubs, and an
invalid character in the installed G'MIC stub before it can meaningfully check
Photoslop. Define supported optional-dependency stubs/overrides, isolate broken
third-party stubs behind reviewed interfaces, and introduce mypy to CI module by
module. If static typing is not an intended contract, remove the misleading
configuration rather than leaving a permanently unusable check.

### P2.3 — Measure coverage in the failure-prone paths

The large test count is valuable, but there is no coverage report or threshold.
Add branch coverage and initially gate only critical modules/behaviors: document
commands and dirty state, serializers, atomic writes, task completion, model
validation, path policy, and release/version checks. Raise thresholds based on
observed coverage rather than selecting an arbitrary repository-wide number.

### P2.4 — Replace synthetic benchmarks with evidence-bearing tests

The CI “4K/50” and “12K/20” benchmarks run at scale 0.01, so they exercise tiny
canvases. Target constants are reported but do not affect exit status. The
“cancellation” measurement times a standalone `threading.Event` loop rather than
TaskService or real filter/I/O/model cancellation, and cache-budget output
largely reports configured values rather than measured memory.

- Rename current jobs as smoke benchmarks if retained.
- Add bounded nightly/full-scale scenarios and fail on reviewed latency, memory,
  cancellation, and output-correctness regressions.
- Measure actual cancellation of filters, model requests, imports, exports, and
  saves—including time until side effects stop.
- Track resident/peak memory and real cache occupancy, not layer counts or
  constants presented as measurements.

### P2.5 — Add desktop autosave and crash recovery

Atomic manual save prevents corruption but not loss since the last save. Add a
versioned recovery journal or snapshots with bounded retention, recovery on next
launch, document identity, and clear cleanup after confirmed save/discard.
Autosave must snapshot safely without blocking the UI or racing manual save.
Test crash points, disk-full behavior, stale recovery, and multiple documents.

### P2.6 — Centralize version/docs/feature claims

Generate version badges and release-facing docs where practical. Update feature
parity to include the iPad app and distinguish desktop, iPad, CLI, and MCP
capabilities. Do not mark accessibility, cancellation, large-canvas, or platform
support “complete” until the acceptance evidence in this audit exists. Keep a
small release checklist that detects stale version strings and documentation.

### P2.7 — Decompose the remaining application monoliths

`mainwindow.py` (~2,776 lines), `tools.py` (~2,020), `cli.py` (~1,361),
`commands.py` (~813), `npimage.py` (~784), and `canvas.py` (~689) still combine
unrelated state and behavior. Continue the service split around document
mutation, task dispatch/completion, import/export policy, command registration,
and tool state machines. Keep UI objects thin and make the extracted logic
headless-testable. Do this incrementally behind characterization tests rather
than as a rewrite.

### P2.8 — Improve diagnostics and invariant handling

- Failed tasks often reduce an exception to the final traceback line in a
  transient status bar. Add a durable diagnostics view/log with operation,
  safe context, cause chain, and retry guidance while redacting secrets.
- Plugin discovery/loading failures should be visible and attributable instead
  of silently swallowed.
- Replace runtime `assert` statements used for reachable application invariants
  with explicit validation and controlled errors; asserts disappear under
  `python -O`.
- Replace the deprecated `QImage.mirrored(bool, bool)` overload and make
  deprecation warnings fail in focused CI once the current 101 warnings are gone.
- Define structured CLI/MCP error codes so automation can distinguish invalid
  input, unsupported capability, unsafe operation, cancellation, and I/O failure.

### P2.9 — Automate dependency and security maintenance

The present dependency audit is clean, but it is a point-in-time result. Add a
scheduled dependency update process, `pip-audit` (or equivalent) against the
lock, SBOM generation, and a triaged Bandit configuration. Pin or constrain
optional native backends and record which components were present in each
artifact. Fail builds on new secrets and new unreviewed high/medium findings,
with narrow documented suppressions for intentional subprocess/plugin code.

### P2.10 — Expand adversarial and state-transition tests

Add focused tests for gaps discovered during this audit:

- panel dirty/undo/save-prompt behavior;
- layer deletion/reorder and selection/document mutation during async tasks;
- concurrent, cancelled, failed, and disk-full saves;
- ORA/SVG bombs, malformed metadata, parser depth, and allocation limits;
- model response size/schema/time/redirect failures;
- MCP root, symlink, overwrite, and unsafe-operation policy;
- SVG unsupported commands and inherited transforms/styles;
- artboard filename collisions and encoder failures;
- iPad persistence, drawing retention, reorder, interruption, large imports,
  memory pressure, accessibility, and UI state restoration;
- tag/version/metadata/workflow permission consistency.

## P3 — cleanup after correctness

### P3.1 — Adopt one formatting baseline

`ruff format --check .` currently reports 111 files that would change. Either
adopt Ruff formatting in one isolated mechanical change and enforce it in CI, or
remove any implied format check. Do not mix repository-wide formatting with
correctness fixes.

### P3.2 — Improve task scheduling and user control

The task service is FIFO and can head-of-line-block a short interactive task
behind long work. After cancellation and commit safety are fixed, add bounded
priorities or separate queues for interactive preview, project writes, remote
models, and bulk export. Show queued/running state, meaningful progress, cancel
scope, and a durable result/error history.

### P3.3 — Review discoverability and shortcut consistency

Once accessibility semantics are in place, audit menu names, platform-standard
shortcuts, focus restoration, destructive confirmations, and command
discoverability across desktop and iPad. Avoid assigning “Save” shortcuts to
flattened export, and keep identical operations routed through the same command
implementation.

## Proposed implementation sequence

### Phase 1 — stop data loss and release breakage

1. P0.1 property commands/dirty tracking.
2. P0.2 atomic writes, per-path serialization, and artboard correctness.
3. P0.3 document revisions and stale-result rejection.
4. P0.5 version source, release gate, and portable permissions.
5. P0.4 iPad project persistence/undo before advertising it as an editor for
   recoverable layered work.

### Phase 2 — close trust boundaries

1. Shared allocation/import budgets and hardened XML/archive handling.
2. Model endpoint validation and privacy-safe transport rules.
3. MCP allowed roots and default-denied raw/plugin operations.
4. Strict SVG parsing/fallback behavior.

### Phase 3 — prove platform quality

1. iPad rendering/memory redesign.
2. Portable reproducibility, smoke tests, signing, notices, and SBOM.
3. Python/platform CI matrix, artifact install tests, coverage, type checking,
   dependency/security automation.
4. Realistic performance, cancellation, and memory measurements.

### Phase 4 — recovery, access, and sustainable maintenance

1. Desktop autosave/crash recovery.
2. End-to-end accessibility and assistive-technology evidence.
3. Architecture decomposition, durable diagnostics, warning cleanup, formatting,
   and task scheduling.

## Release gate suggested by this audit

A release candidate should not ship until all of the following are true:

- No ordinary edit can change output without dirty state and an undo policy.
- All project/output writes are atomic, checked, and concurrency-safe.
- Async completion is revision-checked and cannot target closed/deleted/stale
  state.
- iPad either has recoverable layered persistence or is explicitly labeled as a
  non-project-capable preview/export application without a misleading Save
  command.
- Package/runtime/bundle/docs/tag versions agree, and tagged artifact uploads
  have passed with least-privilege permissions.
- Untrusted documents, remote responses, canvas creation, and MCP paths have
  enforced resource and trust boundaries.
- Supported Python/platform artifacts build, install, launch, and pass smoke
  workflows in CI.
- Known release warnings, dependency vulnerabilities, and untriaged high/medium
  security findings are zero or explicitly reviewed and documented.

This file should remain an active engineering checklist. When an item is fixed,
link its regression tests and pull request beside the item; do not mark it done
from implementation alone.
