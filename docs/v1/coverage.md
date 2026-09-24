# Critical-path coverage gate

Photoslop gates branch coverage for modules where failures can lose data, cross
a trust boundary, or publish stale state. It intentionally does not advertise a
repository-wide percentage as a quality score.

The baseline was re-measured on 2026-09-24 (v2.37.3, #406) with Python 3.12
against the **whole** test suite, which is what the `critical-coverage` CI job
runs. Each floor sits two points under the observed figure:

| Module | Observed | Enforced floor |
|---|---:|---:|
| `atomicio.py` | 95.7% | 93% |
| `commands.py` | 93.7% | 91% |
| `document.py` | 97.6% | 95% |
| `io_ora.py` | 92.2% | 90% |
| `io_svg.py` | 84.7% | 82% |
| `modeladapter.py` | 85.4% | 83% |
| `recovery.py` | 98.5% | 96% |
| `resources.py` | 100% | 98% |
| `server.py` | 81.3% | 79% |
| `services.py` | 98.8% | 96% |
| `tasks.py` | 91.2% | 89% |

The first baseline (2026-07-21) measured a hand-picked list of test files that
missed tests exercising these modules, so it read 30–50 points low. The job
moved to the whole suite but the floors did not follow, and until #406 a module
such as `commands.py` could have lost half its tests without failing the gate.

The floor is checked by `scripts/check-critical-coverage.py`. Raise an
individual floor only after adding durable tests and recording a new observed
baseline; do not lower one merely to make CI green.

*Proudly Made in Nebraska. Go Big Red! 🌽 <https://xkcd.com/2347/>*
