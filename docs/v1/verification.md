# Release verification matrix

This matrix is the release gate for accessibility, performance, interaction
visuals, and native-vector workflows. Automated rows run in CI and publish the
JUnit plus standardized benchmark JSON files as a commit-addressed artifact.

| Area | Automated evidence | Manual evidence |
|---|---|---|
| Keyboard and accessibility tree | `test_accessibility.py`: names, native roles, dynamic canvas state, registered actions, layer semantics, focusable controls, preferences, announcements, transform nudges, dialog naming, and two-stage Escape; gesture tests prove cancelled pixels restore | VoiceOver/NVDA/JAWS/Orca and iPad VoiceOver/Switch Control matrix in [Accessibility](accessibility.md) |
| Scale/theme/icon/cursor states | `test_visual_states.py`, `test_cursors.py`, `test_toolbox.py`: 1x/2x × light/dark/high-contrast renders, alpha, DPR, hotspots, modifiers, invalid targets, temporary pan | Inspect at 100% and 200% on each platform; record clipping or contrast defects |
| Performance and memory | `test_performance.py`, `test_tasks.py`, CI `4k-50`/`12k-20` reports: P50/P95, peak RSS, document bytes, cancellation lifecycle, memory queueing, proxy/cache bounds | Full-scale fixtures on the release machine using [Performance](performance.md) |
| Native vectors | `test_vector_schema.py`, `test_vector_workflows.py`, `test_svg_interchange.py`, `test_vector_layers.py`: legacy migration, Béziers, appearance/gradients, transforms/undo, Boolean, align/distribute, snapping, ordered artboards, SVG and ORA round trips | Open exported SVG in a browser and Inkscape; record Illustrator/Affinity smoke results when available |

## Release record

Record the commit, OS, Qt/Python versions, display scale/theme, assistive
technology version, full test totals, artifact link, benchmark machine and
JSON values, SVG applications tested, and every waived failure. A row is not
“full parity” unless both its end-to-end task and interchange assertions pass.
Platform-dependent manual rows cannot be inferred from offscreen CI and must be
reported as unverified until a human completes them.

Every Ubuntu job that imports Qt installs the same minimal EGL/GL/font/runtime
set through `scripts/install-ci-qt-linux.sh`. The core OS/Python matrix does not
force the optional G'MIC native package to compile on unsupported runners; a
dedicated Linux job installs that extra and exercises its backend tests.
