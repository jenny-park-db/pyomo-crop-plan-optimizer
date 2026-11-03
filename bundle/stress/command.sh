#!/usr/bin/env bash
# AI Runtime entry point for stress_test. Keep this file mode 644: an executable bit makes the task
# fail with "Input/output error" (observed on AI Runtime). tests/test_bundle.py checks it.
set -euo pipefail
python -m cropplan_jobs.stress_air
