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

## Job durations and caps

Each `test` leg runs pytest with `--durations=25 --durations-min=1.0` and
copies the resulting slowest-tests table into its job summary on the run's
Summary page, so a slow leg is diagnosed from its own numbers rather than from
another platform's; the full transcript (`pytest.log`) sits in the test-report
artifact next to the JUnit XML. The per-leg timeout is the `cap-minutes` field
of the matrix in `.github/workflows/test.yml`, sized so the leg's worst recent
run stays under 70% of it, and a closing "cap watch" step prints the elapsed
time against that cap in the summary and raises a workflow warning once a run
crosses the 70% line. A warning means the cap is about to go stale the way it
did in #335: read the slowest-tests table first, and only raise the cap if
the growth is the suite's rather than a regression's. The first measured run
(PR #365) put the same tests in the same order on all four legs with a
near-constant ratio — Windows about 2x Ubuntu 3.14 and 1.4–2x macOS for
every entry — so the Windows gap is the runner's per-test cost, and the
reason its cap is the largest; the three slowest tests are the same
everywhere and are where suite-side savings would come from.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
