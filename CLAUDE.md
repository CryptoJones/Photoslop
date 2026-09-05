# AGENTS.md — AI Agent Contributor Guide (Photoslop)

Guidance for AI agents working in this repo. Read this before running anything
that touches a simulator, a device, or a build.

---

## Clean up after yourself — this is not optional

**You share this machine.** `makemake` is not a build box; it also hosts the
entire Buzz agent fleet (10 `buzz-acp` supervisors + ~54 `buzz-agent` +
`buzz-dev-mcp` children) and it has **16 GB of RAM, shared, no discrete GPU**.
Anything you leave running is taken directly from that.

### iOS simulators

**Booted simulators are acceptable only while you are actively testing. The
moment your task is done — pass, fail, or abandoned — shut them down:**

```bash
xcrun simctl shutdown all
osascript -e 'tell application "Simulator" to quit'
```

Do this even if the run failed. *Especially* if the run failed.

Why it matters, measured 2026-08-25: two forgotten simulators
(`CI-iPhone-18.5` and an `iPhone 13 Pro Max`) were holding **5.88 GB of RAM and
344 processes** — a third of everything on the box. Shutting them down returned
1.27 GB of free memory and released **3.5 GB of swap**, and dropped the machine
from 1002 processes to 632.

This is the failure this repo already knows about: `scripts/ci-local.sh`'s own
header warns that "two booted simulators starve the machine and unrelated tests
start failing on 'the editor never came up' (L-002)." The same pressure on
`makemake` has previously knocked every Buzz agent off the relay, where it
presented as "the agents are ignoring me" rather than as a memory problem — so a
stranded simulator costs someone else hours in a completely different system.

`scripts/ci-local.sh` now carries an `EXIT` trap that shuts simulators down on
any exit including an interrupt. **If you boot a simulator outside that script —
by hand, via `xcodebuild`, or through Xcode — the trap does not cover you.** You
are the cleanup.

### Check before you leave

```bash
xcrun simctl list devices booted    # must print no "(Booted)" lines
```

If you started a long build, a preview server, or a device log stream, kill it.
Leave the machine as you found it.

---

## Three-platform parity is a standing requirement

Every feature or fix ships with parity across **desktop GUI (Qt:
Linux/Windows/macOS)**, **photoslop-cli**, and **iPad/iPhone**. This is the
default, not something to be asked for. Before opening a PR, audit the change
against the other two platforms and either close the gaps in the same release or
file a tracking issue plus a `BACKLOG.md` line for what is deferred — and say so
in the PR body.

---

## Before pushing

```bash
scripts/ci-local.sh            # everything CI runs
scripts/ci-local.sh ios        # iOS legs only
scripts/ci-local.sh python     # Python gates only
scripts/ci-local.sh desktop    # the desktop app as a user gets it
```

Run it rather than assuming a compile is enough. The local simulators must match
the ones CI uses — this script pins iOS **18.5** and the same devices as
`.github/workflows/ipados.yml`, because the iOS suite has failed on CI four
times while passing locally, every time because the dev machine was on iOS 26.x.

---

## Backlog

This repo keeps a root `BACKLOG.md` mirroring the GitHub Issues tab. Every
backlog item has a matching issue and vice versa, linked both ways. When you add
one, add the other; when something ships, check the box so neither side drifts.

---

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
