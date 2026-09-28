#!/usr/bin/env python3
"""Step 0: can this API key manage projects and tasks, and which parts?

Prints JSON:
  { "status": "ready" | "partial" | "blocked" | "unknown",
    "can": [steps], "cannot": [{ step, missing, reason, optional }],
    "next_action": "collect_inputs" | null }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _access  # noqa: E402
import _common  # noqa: E402

# Each step of this skill and the permissions its API calls require. Keep in
# step with the scripts.
STEPS = [
    {"step": "See projects, tasks and their statuses", "needs": ["project:read", "task:read",
                                                              "project_template:read", "task_template:read"]},
    {"step": "Create and edit projects", "needs": ["project:create", "project:update"], "optional": True},
    {"step": "Add or remove people on a project", "needs": ["project:assign"], "optional": True},
    {"step": "Delete projects", "needs": ["project:delete"], "optional": True},
    {"step": "Create and edit tasks", "needs": ["task:create", "task:update"], "optional": True},
    {"step": "Assign tasks", "needs": ["task:assign"], "optional": True},
    {"step": "Delete tasks", "needs": ["task:delete"], "optional": True},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
