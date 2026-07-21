# Critical-path coverage gate

Photoslop gates branch coverage for modules where failures can lose data, cross
a trust boundary, or publish stale state. It intentionally does not advertise a
repository-wide percentage as a quality score.

The baseline was measured on 2026-07-21 with Python 3.12 using the atomic I/O,
commands/document, ORA/SVG, model, recovery, resource, MCP, service, task, and
release-gate tests. Observed module coverage was:

| Module | Observed | Enforced floor |
|---|---:|---:|
| `atomicio.py` | 90% | 88% |
| `commands.py` | 48% | 46% |
| `document.py` | 50% | 48% |
| `io_ora.py` | 65% | 63% |
| `io_svg.py` | 53% | 51% |
| `modeladapter.py` | 72% | 70% |
| `recovery.py` | 86% | 84% |
| `resources.py` | 78% | 76% |
| `server.py` | 79% | 77% |
| `services.py` | 55% | 53% |
| `tasks.py` | 86% | 84% |

The floor is checked by `scripts/check-critical-coverage.py`. Raise an
individual floor only after adding durable tests and recording a new observed
baseline; do not lower one merely to make CI green.
