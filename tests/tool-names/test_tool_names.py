"""Every tool a SKILL.md names exists on the server (scripts/mcp-tools.json),
and every server tool is reachable from some skill.

A skill names tools in backticks (`find_assets`) and in commands
(`vitra.py call find_assets ...`). Backticked snake_case words that are not
tools must be a tool argument, a toolset, or one of the few result fields and
action values the skills quote, so a mistyped or renamed tool fails here
instead of at a user's first call.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / "scripts" / "mcp-tools.json").read_text(encoding="utf-8"))
TOOLS = set(CATALOG["titles"])
ARGUMENTS = {a for names in CATALOG["arguments"].values() for a in names}
TOOLSETS = set(CATALOG["toolsets"])

# Result fields and action values the skills quote; not tools, not arguments.
QUOTED = {
    "check_again_in_seconds",  # every long job's status answer
    "awaiting_voices", "review_ready", "needs_memory",  # dub / subtitle states
    "ready_to_translate",  # image translation state
    "save_to_drive", "back_translate",  # action values
    "sign_in_url",  # the not-signed-in error carries it
    "skills_update",  # vitra.py notes a newer published version
    "brand_kit_id", "entry_id", "prompt_id",  # ids results carry when names repeat
}

# Server tools deliberately left out of every skill (e.g. organization-admin
# tools no customer skill should drive). Every other tool in
# scripts/mcp-tools.json must be named by at least one SKILL.md.
NOT_IN_A_SKILL: set[str] = set()

BACKTICKED = re.compile(r"`([a-z][a-z0-9_]*)`")
COMMAND = re.compile(r"vitra\.py (?:call|describe) ([A-Za-z0-9_<>-]+)")


def skill_files() -> list[Path]:
    return sorted(p for p in ROOT.glob("*/SKILL.md") if not p.parent.name.startswith((".", "_")))


class ToolNamesTest(unittest.TestCase):
    def test_catalog_is_consistent(self) -> None:
        in_sets = {n for names in CATALOG["toolsets"].values() for n in names}
        self.assertEqual(in_sets, TOOLS)
        self.assertEqual(set(CATALOG["arguments"]), TOOLS)

    def test_every_named_tool_exists(self) -> None:
        for path in skill_files():
            text = path.read_text(encoding="utf-8")
            with self.subTest(skill=path.parent.name):
                for name in COMMAND.findall(text):
                    if name.startswith("<"):
                        continue  # the placeholder in "How to call Vitra"
                    self.assertIn(name, TOOLS, f"{path.parent.name} calls unknown tool {name}")
                for word in BACKTICKED.findall(text):
                    if "_" not in word or word in TOOLS:
                        continue
                    self.assertTrue(
                        word in ARGUMENTS or word in TOOLSETS or word in QUOTED,
                        f"{path.parent.name}/SKILL.md names `{word}`, which is not a server "
                        "tool, argument or toolset (renamed? update scripts/mcp-tools.json)",
                    )

    def test_exclusions_are_real_tools(self) -> None:
        self.assertEqual(sorted(NOT_IN_A_SKILL - TOOLS), [], "excluded tools the server doesn't have")

    def test_every_tool_is_reachable_from_a_skill(self) -> None:
        named: set[str] = set()
        for path in skill_files():
            text = path.read_text(encoding="utf-8")
            named |= {w for w in BACKTICKED.findall(text) if w in TOOLS}
            named |= {w for w in COMMAND.findall(text) if w in TOOLS}
        self.assertEqual(sorted(TOOLS - named - NOT_IN_A_SKILL), [],
                         "server tools no SKILL.md names (name one, or exclude it on purpose)")
        self.assertEqual(sorted(NOT_IN_A_SKILL & named), [],
                         "excluded tools a SKILL.md names anyway (drop the exclusion)")

    def test_listings_name_tools_their_skill_uses(self) -> None:
        for path in skill_files():
            listing = path.parent / "listing.yaml"
            if not listing.exists():
                continue
            text = path.read_text(encoding="utf-8")
            used = set(BACKTICKED.findall(text)) | set(COMMAND.findall(text))
            for name in re.findall(r"^\s+- name: ([a-z_0-9]+)$", listing.read_text(encoding="utf-8"),
                                   re.MULTILINE):
                if name in TOOLS:
                    self.assertTrue(name in used,
                                    f"{path.parent.name}/listing.yaml lists {name}, "
                                    "which its SKILL.md never uses")


if __name__ == "__main__":
    unittest.main()
