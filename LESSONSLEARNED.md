# Lessons Learned

Faults that cost more than they should have, written down so the next person —
or the next model — starts from the diagnosis rather than the symptom.

Each entry records what the symptom looked like, what it actually was, and the
rule that would have shortened the hunt. Add to it when something takes more than
two attempts to fix.

---

## L-001 — "Exists but cannot be tapped" on a SwiftUI `Menu` is an accessibility artefact, not a layout bug

**Cost:** four wrong fixes, five CI cycles, roughly six hours (2026-08-12, #249/#251).

**Symptom.** An XCUITest asserting `isHittable` on the crop bar's aspect control
failed only on CI, never on five local simulators:

```
Crop aspect exists but cannot be tapped.
Its frame is (381.0, 1147.5, 63.5, 20.5) and the window is (0.0, 0.0, 834.0, 1210.0)
```

On screen, in the window, and untappable — which reads exactly like a control
that is covered or pushed off the edge.

**What it actually was.** SwiftUI renders a `Menu` as **a Button wrapping a
Button**. An `.accessibilityIdentifier` applied to the `Menu` lands on the outer
wrapper, and the wrapper is not itself hittable because a tap resolves to the
inner one. The accessibility hierarchy showed it plainly:

```
Button 0x…51d0 {{381.0, 1147.5}, {63.5, 20.5}} identifier: 'Crop aspect'
  Button 0x…52f0 {{381.0, 1147.5}, {63.5, 20.5}}        ← the real control
    Other  0x…5410
      Image 'lock.open'
      StaticText 'Free'
```

The bar was perfectly laid out the whole time: Cancel at x=16, aspect at x=381,
Crop at x=756, all at y≈1147 in a 1210-tall window. Nothing covered it. Nothing
was off-screen.

**The fix — and a fifth wrong turn before it.**
`.accessibilityElement(children: .combine)` on the `Menu` *looks* like the
answer: collapse the pair into the single element it appears to be. It does not
work on this iOS version. The hierarchy dump after applying it still showed the
nested `Button`, unchanged.

What works is to stop asserting `isHittable` on a `Menu` at all. It is a fact
about the framework's hit-test model, not about whether a finger can reach the
control. The tests now assert **geometry** — the control's frame is inside the
window — and **function** — tapping by coordinate opens the menu and reshapes the
crop. Both are true, checkable, and independent of how SwiftUI chooses to nest
its accessibility elements.

**The four wrong fixes**, each plausible, each aimed at a fault that did not
exist: removing `.ignoresSafeArea()` from the dimming layer; giving the bottom
bar `.layoutPriority(1)`; `.clipped()` on the overlay; clamping handle touch
targets inside the canvas. Two of those changed real user-visible behaviour and
had to be reverted — the handles had been moved off the crop edge they exist to
mark.

### Rules this earns

1. **An identical failure frame across fixes means none of your fixes touched
   the cause.** The reported rect was byte-identical — `(381.0, 1147.5, 63.5,
   20.5)` — through four different commits. That was conclusive evidence by the
   second one, and it was read as coincidence.
2. **Dump the accessibility hierarchy on the second failure, not the fifth.**
   `print(app.debugDescription)` in the failing branch answered in one run what
   four rounds of reasoning could not. Instrument before theorising when the
   failure is only observable somewhere you cannot attach a debugger.
3. **`isHittable == false` has three causes, and "covered" is only one.** It is
   also false for a non-interactive wrapper element, and for an element the
   framework considers off-screen. Distinguish them from the hierarchy before
   changing layout.
4. **Never change user-visible behaviour to satisfy a test you have not
   diagnosed.** Both reverted changes altered how crop feels in the hand. A test
   failure is a claim about the app; verify the claim before acting on it.
5. **`.clipped()` clips drawing, not hit-testing.** It is not a way to stop a
   child receiving touches outside its parent's bounds.

---

## L-002 — A test that passes only on your machine is not passing

**Cost:** two CI cycles (2026-08-12, #248/#250).

**Symptom.** The export-to-Photos test passed locally and failed on CI with "no
confirmation", as though the save were broken.

**What it actually was.** The permission had been granted by hand with
`xcrun simctl privacy <device> grant photos-add <bundle-id>` before running it
locally. CI never did that, so the save sat on the system consent dialog forever.

**The fix.** CI grants the permission the same way, per device, immediately
before that device's tests.

**And the fix's own fault:** the first version booted *both* simulators up front
to grant in one step, which left two running for the whole job. The runner
starved and unrelated tests began failing on "the editor never came up". One
simulator at a time, which is what `xcodebuild` does when left alone.

### Rules this earns

1. **Environment setup done by hand is part of the test.** If a local run needed
   a command first, CI needs it too — or the test is asserting something about
   your machine.
2. **A CI fix that changes resource usage is a change to every other test.**
   Booting a second simulator is not free.

---

## L-003 — Reachability bugs hide behind device geometry, and retries hide them completely

**Cost:** three separate user-reported bugs in one month (#227, #242, #246),
each found by a person using the app rather than by CI.

**Symptom.** A control exists in the code, passes its tests, and cannot be
reached on a device:

- **#227** — iPhone: UIKit dropped the trailing toolbar group entirely, so there
  was no way to export at all.
- **#242** — iPad mini in portrait is 744pt and reports the *regular* size class,
  so it took the iPad layout: nine bar items, eleven once a text layer made Edit
  Text and Move Text appear. UIKit collapsed the trailing group behind an
  unlabelled chevron and Export left the bar.
- **#246** — the tool strip overflowed its width and scrolled with no indicator.
  Ink colour and brush width, the two controls a painting app touches most, were
  measured at x=415.7 on a 402pt iPhone and x=773.5 on a 744pt iPad mini.

**The compounding factor.** The iOS suite ran with `-retry-tests-on-failure
-test-iterations 3`, on the reading that the app was reliable and the harness
was racy. That reading was wrong. #242 was on the wrong side of those retries for
months: **a retry cannot tell a flaky test from a feature that is only sometimes
there.**

Six causes were behind that flag, all now fixed: the bar overflow above; every
test inheriting the previous test's documents; a layer-count assertion racing an
async decode; queries enumerating the system document browser's hierarchy until
XCTest could not snapshot them; a cold simulator charging its first-document cost
to whichever test ran first; and the canvas-size question being asked twice.

### Rules this earns

1. **`.regular` does not mean wide.** An iPad mini in portrait has barely 50pt
   more usable strip than an iPhone, and larger controls. It is the worst case
   and it never looks like one.
2. **Budget every bar for its narrowest device, with an item count that cannot
   change with document state.** Edit Text and Move Text appear only when a text
   layer is active, so the bar fitted until the user added text — and every test
   written before that step passed.
3. **Assert reachability, not existence.** `exists` is true for a control 14pt
   below the bottom of the screen. Assert that the frame is inside the window, on
   the narrowest device — and add `isHittable` only for plain controls, never for
   a `Menu`, whose wrapper reports false regardless (L-001). See
   `testNothingIsHandedToTheSystemOverflow` and
   `testEveryToolStripControlIsReachableWithoutScrolling`.
4. **Test both orientations.** A reachability assertion cannot fire on a screen
   that happens to be tall enough.
5. **Keep the retry budget as low as it will go.** Every iteration is somewhere
   a real defect can hide. The remaining two exist for one failure mode only:
   the XCTest daemon failing to initialise a UI-testing session, where zero tests
   execute and no app is involved.

---

## L-004 — Local passes are evidence, not proof, when the runner is three times slower

**Cost:** repeated across the session — claimed green before CI agreed, twice.

**Symptom.** Work reported as verified on the strength of local runs, then
failing on CI.

**What it actually was.** The CI runner is roughly 3× slower than a dev machine,
and its simulators are freshly erased. Timeouts tuned locally expire there while
the app is still coming up, and the failure reads as "the editor never came up"
when the truth is that nobody waited long enough.

### Rules this earns

1. **Do not report a change as verified until the job that gates it is green.**
   Local runs are a filter, not a verdict.
2. **State what was actually run.** "13 UI tests green on an iPad mini and an
   iPhone 17 Pro, CI pending" is honest; "verified" is not.

---

## L-005 — Three bugs with one cause look like three bugs until you count them

**Cost:** three user-reported bugs and three separate fixes over a fortnight
(#260, #268, #270), plus a fourth latent in each of three features that had not
been built yet (#266, #262, #261).

**Symptom.** Three unrelated-looking complaints about the crop tool:

1. "instead of cropping exactly where you tell it to, the top horizontal start
   is at the top of the image, not the top of the crop box"
2. "when I crop a second time it tries to start at the original image size not
   my new cropped image size"
3. "I need to be able to scale in and out of the canvas with pinch and zoom"

The first reads as arithmetic, the second as a race, the third as a missing
feature. Each was diagnosed correctly and fixed on its own terms — publish the
canvas rectangle; then publish it sooner; then stop switching off hit-testing.

**What it actually was.** One decision: the overlay lived in screen coordinates
while the thing it described lived in document coordinates. Every symptom above
is a way that conversion can be wrong — stale inputs, out-of-order inputs, and
the fact that a view floating above a scroll view is not *in* it and so cannot
share its gestures. Deleting the conversion deleted all three at once, and the
fix is smaller than any of the three patches it replaced.

**What should have raised it earlier.** The second bug in the same conversion.
The first fix added a published rectangle; the second fix adjusted *when* that
rectangle was published. A fix that adjusts the timing of a previous fix is not
a fix, it is a symptom of a design that has to be kept in sync — and anything
that has to be kept in sync will eventually not be.

### Rules this earns

1. **When a second bug lands in the same conversion, stop fixing bugs and
   question the conversion.** Two faults in one mechanism is the mechanism
   telling you about itself.
2. **Prefer deleting a translation to correcting it.** A coordinate space you do
   not convert between cannot be converted wrongly. Ask what space the data is
   *already* in and whether the view can simply live there.
3. **Count the callers before fixing the third instance.** Three more features
   were queued behind this one — a placement box, a layer resize, a text box —
   and every one would have inherited the same split. Fixing it once cost less
   than the three patches would have, before counting the three it prevented.
4. **A user reporting a missing feature may be reporting a bug.** "I need pinch
   and zoom while cropping" sounds like an enhancement; it was one line of
   collateral damage from an unrelated fix.

---

## L-006 — Dev testing comes before beta testing, and "locally" is not a configuration

**Cost:** four consecutive CI failures on one pull request, several hours of the
user's morning, and a release that should have shipped overnight (2026-08-14,
#270 and friends).

**The rule, in the user's words:** *"the number one rule I teach junior
developers is dev testing first before beta testing."* Every failure below is
that rule broken in the same way.

**Symptom.** The iOS suite passed locally — repeatedly, on two device classes,
with no retries — and failed on CI four times running. Each failure was
diagnosed, fixed, pushed, and replaced by the next one.

**What it actually was.** The local simulators were **iOS 26.5**. CI's are
**iOS 18.5**. Everything that broke lived in the gap:

- SwiftUI's `DragGesture` inside a `UIHostingController` inside a `UIScrollView`
  is **never sent a touch** on 18.5. Instrumented, it reported `changes=0` while
  the handle was hittable and the press registered. On 26.5 it works.
- An element with no gesture reports `isHittable == false` to XCUITest on 18.5,
  so the runner refuses to drag it — where a finger has no difficulty.

No amount of re-running on 26.5 could find either. The runs were not weak
evidence; they were evidence about a different system.

**What made it worse.** CI selected its simulators as *"the first iPad in the
list"*. Nobody could tell what had been tested without reading the log, and the
mismatch with local machines was invisible by construction.

**The fix, beyond the bugs.** `scripts/ci-local.sh` pins the same two devices
and the same runtime CI uses and runs the same legs in the same order; the
workflow now pins those models by name and warns loudly if it has to fall back.
A green run in one place now means the same sentence in the other.

### Rules this earns

1. **Pin the test configuration, and share the pin between local and CI.** A
   suite that runs on "whatever this machine has" is not a suite, it is a
   coincidence. This is the whole lesson; everything else follows.
2. **The OS version is part of the configuration.** So is the device model.
   "It passes on my machine" needs a version attached before it means anything,
   and a framework's gesture arbitration is exactly the kind of thing that moves
   between them.
3. **Reproduce before fixing, even when reproducing is expensive.** Downloading
   a 9 GB runtime took less time than the two wrong fixes pushed while guessing
   across the gap, and it turned a four-hour hunt into a single run.
4. **Instrument the mechanism, not the symptom.** A counter on the gesture's
   `onChanged` answered in one run — `changes=0` — what three rounds of
   plausible reasoning could not. This is L-001 rule 2, learned again.
5. **Test what CI tests before pushing, not after.** "I will watch the build"
   is not a plan; nothing watches between turns. Run the same configuration
   first, and report the result rather than the intention.

---

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
