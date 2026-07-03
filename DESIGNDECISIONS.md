# Design Decisions

The record of what Photoslop deliberately **won't** do, what it will only do
**partially**, and why. Every entry is judged against the project's prime
directive; when a proposed feature and the directive collide, the directive
wins and the reasoning lands here so it never has to be re-litigated from
scratch.

Format: each decision has a status (**Accepted** / **Rejected** /
**Partial**), the decision itself, the why, and the consequences —
including which backlog trackers it re-scoped or closed.

---

## DD-001 — Memory performance beats features (the prime directive)

**Status: Accepted (founding constraint, 2026-07-02).**

Photoslop exists to be the layered editor that treats RAM like it costs
money: exactly one premultiplied 8-bit buffer per layer, copy-on-write
sharing, viewport-only compositing, 128-px tile undo deltas, crop as an
offset shift, and an install measured in megabytes. Every feature proposal
is evaluated against this first, features second. A capability that would
be routine elsewhere is rejected here if its *resident* memory cost scales
with document size.

**Consequence:** the rulings below. The dividing line that recurs in all of
them: **transient spikes during an operation are acceptable house style;
resident growth of the per-layer budget is not.**

---

## DD-002 — No resident deep-bit buffers (16-bit / 32-bit layers)

**Status: Rejected (2026-07-03).**

16-bit-per-channel layers double every buffer (8 bytes/px vs 4); 32-bit
float quadruples them (16 bytes/px). A 45 MP layer goes 180 MB → 360 MB →
720 MB, and layers *are* the memory budget — this is not a corner case, it
is the core cost. Even as an opt-in document flag, deep bit depth infects
every engine path (numpy views, LUTs, blends, ORA I/O), roughly doubles the
code and test surface, and its entire payoff contradicts DD-001.

**Consequences:** the deep-bit rows were removed from tracker #108 (which
was re-scoped to ICC only — see DD-004). Transient high-bit-depth inside a
single operation remains allowed (see DD-007).

---

## DD-003 — No scene-referred / HDR pipeline

**Status: Rejected (2026-07-03). Tracker #113 closed.**

A scene-referred workflow (filmic/sigmoid view transforms, linear-light
math, EXR/HDR I/O) requires 32-bit float buffers plus linear intermediates —
the worst resident-memory profile of anything on the backlog. It is also a
solved problem elsewhere: darktable exists, is free, and is excellent at
exactly this. Photoslop stays display-referred 8-bit and interoperates
instead of competing where its architecture forbids it to win.

---

## DD-004 — ICC color management: yes, because it's viewport-only

**Status: Accepted (2026-07-03). Tracker #108 re-scoped to this.**

Color management was accepted precisely because it does *not* touch the
per-layer budget: document profiles are metadata, the display transform
applies to the composited **viewport region only** (the architecture's
native unit of work), soft-proofing is a viewport LUT, and export
conversion is a transient pass over tiles. This is the rare parity feature
that the memory-frugal design makes *cheaper*, not harder.

**Consequence:** #108 is now "ICC color management + soft-proofing" —
assign/convert document profiles, monitor-profile-aware display, soft-proof
toggle, and transient CMYK export (DD-005), with the print pipeline as a
stretch row.

---

## DD-005 — No CMYK working mode; CMYK export only

**Status: Partial (2026-07-03).**

A native CMYK mode means a fourth channel (+25% resident memory) and a
duplicated compositing/adjustment pipeline. Rejected. CMYK **export** — a
one-shot transient conversion at write time through the ICC machinery — is
fine and stays on #108 as a stretch row.

---

## DD-006 — GIMP-bridge: spawn-per-call only, never resident

**Status: Partial (2026-07-03). Tracker #111 annotated.**

Keeping a headless GIMP warm (Script-Fu server) idles at 200–500 MB RSS —
the least memory-frugal idea on the board, rejected outright. The bridge
survives only as **spawn-per-call**: launch GIMP headless for the one
filter run, harvest the result, and let the process die. Slower, but the
memory cost is transient and zero at rest. If spawn latency makes it
useless in practice, the bridge dies entirely rather than going resident.

---

## DD-007 — Raw development: transient 16-bit in, 8-bit layer out

**Status: Partial (2026-07-03). Tracker #112 re-scoped.**

The raw develop stage may hold the full raw plus a 16-bit RGB intermediate
*while the develop dialog is open* — a bounded, single-document transient,
same class as crop and rotate. The **result committed to the document is an
8-bit layer**, keeping the resident budget untouched. Heavy raw ML (denoise,
upscale) routes through the model-adapter contract so the memory lives on
whatever backend the user brings — the most memory-frugal feature shape
Photoslop has (see DD-009).

---

## DD-008 — G'MIC filter runs: bounded float transients accepted

**Status: Accepted with eyes open (2026-07-03). Tracker #111 annotated.**

libgmic computes in float internally, so each filter run costs roughly a
4× transient copy of **one layer at a time**, released when the filter
returns. That is within the transient-spike allowance of DD-001 and is the
price of ~600 filters for near-zero code. The tracker documents the cost so
nobody mistakes it for a leak.

---

## DD-009 — ML features never hardwire infrastructure

**Status: Accepted (2026-07-02, CJ directive).**

Model-backed features (Select Subject, Generative Fill, future denoise/
upscale) speak the documented ModelAdapter contract — any HTTP backend or
entry-point plugin, no vendor account, no bundled model weights, no
hardwired hosts. Besides the freedom argument, this is also the memory
story: the heavy lifting happens on whatever machine the user points at,
and Photoslop's resident footprint stays flat.

---

*New decisions get the next DD number. Reversing one requires a new entry
that names the entry it supersedes — history is append-only.*

Proudly Made in Nebraska. Go Big Red! 🌽 https://xkcd.com/2347/
