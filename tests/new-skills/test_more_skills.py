"""DITA maps, brand kits, projects & tasks, the prompt library, and the
document and dubbing extras, against the same fake Vitra API: what each script
sends, that people see names (never ids), and that nothing destructive or
paid runs twice or without a yes. Run from the repo root:

    python3 -m unittest discover -s tests/new-skills
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from test_new_skills import LANGUAGES, TM_ROWS, SkillCase  # noqa: E402

DOC = "/v1/galaxy/playground/document"
DITA = "/v1/galaxy/translate-photo/dita-map"
RUN = "33333333-3333-4333-8333-333333333333"
TOPIC = "44444444-4444-4444-8444-444444444444"
BASE_ROUTES = {("GET", "/v1/language"): LANGUAGES, ("GET", "/v1/translation-memory"): {"rows": TM_ROWS[:1]}}


def ids_in(out: object, *ids: str) -> bool:
    text = json.dumps(out)
    return any(i in text for i in ids)


class DitaTest(SkillCase):
    def setUp(self) -> None:
        super().setUp()
        self.zip = self.dir / "manual.zip"
        self.zip.write_bytes(b"PK\x03\x04 fake")
        base = self.fake.base
        self.fake.routes.update({
            **BASE_ROUTES,
            ("POST", DITA + "/initialize"): {"data": {"playgroundLogIds": [RUN], "targetLanguages": ["fr-FR"],
                                                      "wordCount": 1200}},
            ("POST", f"{DITA}/{RUN}/generate-translation-zip"): {
                "success": True, "data": {"url": f"{base}/bucket/org/dita-map/{RUN}/out.zip", "failedFileCount": 0}},
            ("GET", f"/bucket/org/dita-map/{RUN}/out.zip"): b"PK zipped",
        })

    def files(self, status: str) -> dict:
        return {"status": "DONE", "summary": {"total": 1, "done": int(status == "DONE"),
                                              "failed": int(status == "FAILED"), "inProgress": 0},
                "tree": [{"type": "folder", "name": "topics", "path": "topics", "children": [
                    {"type": "file", "name": "intro.dita", "path": "topics/intro.dita", "childLogId": TOPIC,
                     "status": status, "error": "parse error" if status == "FAILED" else None}]}]}

    def test_translates_downloads_and_reconnects(self) -> None:
        self.fake.routes[("GET", f"{DITA}/{RUN}/files")] = self.files("DONE")
        code, out = self.run_script("dita-translation", "translate_dita", "--file", str(self.zip),
                                    "--target-language", "French")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "translated")
        lang = out["languages"][0]
        self.assertEqual(Path(self.dir / lang["path"]).read_bytes(), b"PK zipped")
        self.assertFalse(ids_in({k: v for k, v in lang.items() if k != "translation"}, RUN, TOPIC))
        # the memory's own notation, not the user's word
        self.assertIn(b'["fr-FR"]', self.fake.sent("POST", DITA + "/initialize")[0])
        # the same command again: no second upload, no second zip in the Drive
        code, again = self.run_script("dita-translation", "translate_dita", "--file", str(self.zip),
                                      "--target-language", "French")
        self.assertEqual((code, again["languages"][0]["path"]), (0, lang["path"]))
        self.assertEqual(len(self.fake.sent("POST", DITA + "/initialize")), 1)
        self.assertEqual(len(self.fake.sent("POST", f"{DITA}/{RUN}/generate-translation-zip")), 1)

    def test_failed_topics_ask_before_building(self) -> None:
        self.fake.routes[("GET", f"{DITA}/{RUN}/files")] = self.files("FAILED")
        code, out = self.run_script("dita-translation", "translate_dita", "--file", str(self.zip),
                                    "--target-language", "French")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "TOPICS_FAILED")
        self.assertEqual(out["languages"][0]["failed"], [{"file": "topics/intro.dita", "why": "parse error"}])
        self.assertEqual(self.fake.sent("POST", f"{DITA}/{RUN}/generate-translation-zip"), [])

    def test_quality_issues_are_numbered_by_file_and_applied_by_number(self) -> None:
        self.fake.routes.update({
            ("GET", f"{DITA}/{RUN}/files"): self.files("DONE"),
            ("POST", DITA + "/qe-report/publish"): {"report": {"id": "r1", "status": "succeeded",
                                                               "scorecard": {"score": 81, "band": "good"}}},
            ("GET", "/v1/aiqe/reports/r1/segments"): {"segments": [
                {"key": f"{TOPIC}:4", "score": 40, "sourceText": "Hello", "targetText": "Salut",
                 "errors": [{"severity": "major", "category": "style", "explanation": "too casual"}],
                 "correctedTarget": "Bonjour"}]},
            ("PUT", DITA + "/qe-report/apply-fix"): {"applied": 1, "unchanged": 0, "skipped": 0},
        })
        code, out = self.run_script("dita-translation", "quality_report", "--translation", RUN)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["worst"][0]["issue"], 1)
        self.assertEqual(out["worst"][0]["file"], "topics/intro.dita")
        self.assertFalse(ids_in(out, TOPIC))
        code, fixed = self.run_script("dita-translation", "quality_report", "--translation", RUN,
                                      "--apply-fixes", "1")
        self.assertEqual((code, fixed["applied"]), (0, 1))
        self.assertEqual(self.fake.sent("PUT", DITA + "/qe-report/apply-fix")[0],
                         {"playgroundLogId": RUN, "keys": [f"{TOPIC}:4"], "reportId": "r1"})


class DocumentExtrasTest(SkillCase):
    routes = {
        ("POST", DOC + "/ai-proofreading/publish"): {"ok": True},
        ("GET", DOC + "/ai-proofreading/status/t1"): {"data": [
            {"layerIndex": 7, "status": "DONE", "text": "Hi", "translation": "Salut",
             "output": {"updatedText": "Bonjour", "corrections": [{"explanation": "formal"}]}},
            {"layerIndex": 9, "status": "DONE", "text": "Bye", "translation": "Au revoir",
             "output": {"updatedText": "Au revoir"}}]},
        ("PUT", DOC + "/ai-proofreading/apply"): {"ok": True},
    }

    def test_proofreading_lists_changes_and_applies_only_chosen_lines(self) -> None:
        code, out = self.run_script("document-translation", "proofread", "--translation", "t1")
        self.assertEqual(code, 0, out)
        self.assertEqual([s["line"] for s in out["suggestions"]], [1])
        self.assertEqual(out["suggestions"][0]["why"], ["formal"])
        code, done = self.run_script("document-translation", "proofread", "--translation", "t1", "--apply", "1")
        self.assertEqual((code, done["applied"]), (0, [1]))
        self.assertEqual(self.fake.sent("PUT", DOC + "/ai-proofreading/apply")[0]["layers"], [7])


class DubbingExtrasTest(SkillCase):
    routes = {("POST", "/v1/pronunciation-dictionary/org-rules"): {"id": "p1"},
              ("GET", "/v1/galaxy/translate-video/language/transliterate/suggestions"):
                  {"data": ["नमस्ते", "नमस्ते जी"]}}

    def test_pronunciation_rule_is_saved_for_the_language(self) -> None:
        code, out = self.run_script("video-dubbing", "pronunciations", "add", "--word", "SQL", "--say", "sequel",
                                    "--language", "hindi_india")
        self.assertEqual(code, 0, out)
        sent = self.fake.sent("POST", "/v1/pronunciation-dictionary/org-rules")[0]
        self.assertEqual((sent["language"], sent["matchText"], sent["value"]), ("hindi_india", "SQL", "sequel"))
        self.assertFalse(ids_in(out, "p1"))


class BrandKitTest(SkillCase):
    KIT = {"id": "k1", "name": "Acme", "primaryColors": ["#111111"], "website": "https://acme.com"}
    routes = {("GET", "/v1/brand-kit"): {"count": 1, "rows": [KIT]},
              ("POST", "/v1/brand-kit/extract"): {"name": "Acme", "primaryColors": ["#8143FD"], "website": ""},
              ("PATCH", "/v1/brand-kit/k1"): {**KIT, "primaryColors": ["#222222"]},
              ("DELETE", "/v1/brand-kit/k1"): {"id": "k1", "deleted": True}}

    def test_extract_only_drafts(self) -> None:
        code, out = self.run_script("brand-kit", "brand_kits", "extract", "--website", "acme.com")
        self.assertEqual((code, out["status"]), (0, "draft"))
        self.assertEqual(self.fake.sent("POST", "/v1/brand-kit"), [])

    def test_update_by_name_and_delete_needs_a_yes(self) -> None:
        code, out = self.run_script("brand-kit", "brand_kits", "update", "--kit", "acme", "--color", "#222222")
        self.assertEqual((code, out["kit"]["colors"]), (0, ["#222222"]))
        self.assertFalse(ids_in(out, "k1"))
        code, out = self.run_script("brand-kit", "brand_kits", "delete", "--kit", "Acme")
        self.assertEqual(out["error"]["code"], "CONFIRM_NEEDED")
        self.assertEqual(self.fake.sent("DELETE", "/v1/brand-kit/k1"), [])
        code, out = self.run_script("brand-kit", "brand_kits", "delete", "--kit", "Acme", "--confirm")
        self.assertEqual((code, out["status"]), (0, "deleted"))


BOARD = {"status": {"NOT_STARTED": [{"id": "s-todo", "name": "TO DO"}],
                    "ACTIVE": [{"id": "s-doing", "name": "IN PROGRESS"}],
                    "DONE": [{"id": "s-done", "name": "DONE"}], "CLOSED": []},
         "priority": [{"id": "high", "name": "High"}, {"id": "low", "name": "Low"}]}
PROJECT = {"id": "p1", "name": "Q4 launch", "type": "TRANSLATION", "status": "s-doing", "priority": "high",
           "fk_orgId": "org1", "taskCount": "2", "completedTaskCount": "1",
           "members": [{"isAssignee": True, "fk_orgMemberId": "m1", "orgMember": {"user": {"name": "Priya Rao"}}}]}
TASK = {"id": "t1", "title": "Review glossary", "status": "s-todo", "priority": "low", "endDate": "2026-10-10",
        "taskMembers": []}


class ProjectsTest(SkillCase):
    routes = {
        **BASE_ROUTES,
        ("GET", "/v1/project-template"): [BOARD],
        ("GET", "/v1/task-template/project/p1"): BOARD,
        ("GET", "/v1/project"): {"data": [PROJECT], "pagination": {"total": 1}},
        ("POST", "/v1/project"): {**PROJECT, "id": "p2", "name": "App"},
        ("GET", "/v1/task"): {"data": [TASK], "pagination": {"total": 1}},
        ("PUT", "/v1/task/t1"): [1],
        ("GET", "/v1/task/t1"): {**TASK, "status": "s-doing", "taskMembers": [
            {"isAssignee": True, "orgMember": {"user": {"name": "Priya Rao"}}}]},
        ("GET", "/api/auth/organization/list-members"): {"members": [
            {"id": "m1", "user": {"name": "Priya Rao", "email": "priya@acme.com"}}]},
        ("POST", "/v1/task-member/add"): {"ok": True},
    }

    def test_list_names_statuses_and_people(self) -> None:
        code, out = self.run_script("projects", "projects", "list")
        self.assertEqual(code, 0, out)
        p = out["projects"][0]
        self.assertEqual((p["status"], p["priority"], p["tasks"], p["people"]),
                         ("IN PROGRESS", "High", "1/2 done", ["Priya Rao"]))
        self.assertFalse(ids_in(out, "s-doing", "p1", "org1", "m1"))

    def test_create_sends_ids_and_language_keys(self) -> None:
        code, out = self.run_script("projects", "projects", "create", "--name", "App", "--type", "translation",
                                    "--target-language", "German", "--priority", "low")
        self.assertEqual((code, out["status"]), (0, "created"))
        sent = self.fake.sent("POST", "/v1/project")[0]
        self.assertEqual((sent["type"], sent["targetLanguages"], sent["priority"]), ("TRANSLATION", ["german"], "low"))
        self.assertNotIn("status", sent)  # the server starts it on its board

    def test_move_and_assign_a_task_by_name(self) -> None:
        code, out = self.run_script("projects", "tasks", "update", "--project", "Q4 launch", "--task",
                                    "review glossary", "--status", "in progress", "--assign", "Priya Rao")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.fake.sent("PUT", "/v1/task/t1")[0], {"status": "s-doing"})
        self.assertEqual(self.fake.sent("POST", "/v1/task-member/add")[0]["members"][0]["orgMemberId"], "m1")
        self.assertEqual((out["task"]["status"], out["task"]["assignees"]), ("IN PROGRESS", ["Priya Rao"]))
        self.assertFalse(ids_in(out, "t1", "m1", "s-doing"))

    def test_unknown_status_is_a_question(self) -> None:
        code, out = self.run_script("projects", "tasks", "update", "--project", "Q4 launch", "--task",
                                    "Review glossary", "--status", "Blocked")
        self.assertEqual(out["error"]["code"], "CHOICE_NEEDED")
        self.assertEqual(out["error"]["choices"], ["TO DO", "IN PROGRESS", "DONE"])
        self.assertEqual(self.fake.sent("PUT", "/v1/task/t1"), [])


class PromptsTest(SkillCase):
    PROMPT = {"id": "pr1", "name": "Product description", "visibility": "organization", "isOwner": True,
              "variables": ["product", "tone"]}
    routes = {("GET", "/v1/prompts-library"): {"data": [PROMPT], "total": 1},
              ("GET", "/v1/prompts-library/pr1"): {**PROMPT, "content": "Describe {{product}} in a {{ tone }} tone."},
              ("DELETE", "/v1/prompts-library/pr1"): {"status": 200}}

    def test_show_fills_variables_and_reports_the_rest(self) -> None:
        code, out = self.run_script("prompts-library", "prompts", "show", "--prompt", "product description",
                                    "--fill", "product=Trail shoe")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["prompt"]["content"], "Describe Trail shoe in a {{ tone }} tone.")
        self.assertEqual(out["prompt"]["unfilled"], ["tone"])
        self.assertFalse(ids_in(out, "pr1"))

    def test_delete_needs_a_yes(self) -> None:
        code, out = self.run_script("prompts-library", "prompts", "delete", "--prompt", "Product description")
        self.assertEqual(out["error"]["code"], "CONFIRM_NEEDED")
        self.assertEqual(self.fake.sent("DELETE", "/v1/prompts-library/pr1"), [])


if __name__ == "__main__":
    unittest.main()
