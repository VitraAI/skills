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


class MissingKeyTest(SkillCase):
    def test_a_missing_key_says_how_to_get_one(self) -> None:
        import os, subprocess
        env = {k: v for k, v in os.environ.items() if k != "VITRA_UNIVERSE_API_KEY"}
        env["VITRA_HOME"] = str(self.dir)  # no sign-in on this "machine"
        p = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[2] / "projects" / "scripts" /
                            "projects.py"), "list"], capture_output=True, text=True, env=env, cwd=self.dir)
        out = json.loads(p.stdout.strip().splitlines()[-1])
        self.assertEqual((p.returncode, out["error"]["code"]), (2, "AUTH_MISSING"))
        self.assertTrue(out["error"]["sign_up"].endswith("/auth/sign-up"))
        self.assertIn("sign in", out["error"]["ask"])
        self.assertIn("login.py", out["error"]["next_action"])
        self.assertIn("Settings -> API keys", out["error"]["message"])  # the no-browser way
        self.assertEqual(self.fake.calls, [])  # stops before any network call


IT = "/v1/galaxy/translate-photo/image-translator"
JOB = "55555555-5555-4555-8555-555555555555"


class ImageAddLanguageTest(SkillCase):
    routes = {
        ("GET", f"{IT}/{JOB}/translations"): {"statusCode": 200, "versions": [  # the server's shape: newest first
            {"id": "v1", "targetLanguage": "French", "status": "completed", "translatedImageUrl": "https://img/fr.png"}]},
        ("GET", f"{IT}/{JOB}/translations/v1"): {"status": "completed", "translatedImageUrl": "https://img/fr.png",
                                                 "targetLanguage": "French", "translationData": {
            "r-a": {"source": "SALE", "translated": "SOLDES", "status": "u"},
            "r-b": {"source": "Acme", "translated": "Acme", "status": "u"}}},
        ("GET", "/v1/folder"): [{"id": "f-1", "name": "Diwali"}],
        ("PATCH", f"{IT}/{JOB}/folder"): {"ok": True},
        ("PUT", f"{IT}/{JOB}/translations/v1/bulk-region-status"): {"ok": True},
        ("GET", "/v1/assets-management"): {"data": [{"id": "d-1", "name": "Q3 creatives", "type": "folder"}]},
        ("POST", f"{IT}/versions/v1/save-to-drive"): {"data": {"id": "a-1", "name": "sale-fr.png"}},
        ("GET", f"{IT}/jobs/list"): {"data": [{"id": JOB, "name": "poster.png", "tmName": "Acme", "createdAt":
            "2026-09-28T10:00:00Z", "translationVersions": [
                {"id": "v1", "targetLanguage": "French", "status": "completed",
                 "translatedImageUrl": "https://img/fr.png"}]}], "total": 1},
        ("POST", f"{IT}/{JOB}/translate"): {"translationVersionId": "v2", "status": "processing"},
        ("GET", f"{IT}/{JOB}/translations/v2"): {"status": "completed", "targetLanguage": "German",
                                                 "translatedImageUrl": "https://img/de.png"},
    }

    def test_new_languages_reuse_the_analysis_and_done_ones_are_not_redone(self) -> None:
        code, out = self.run_script("image-translation", "add_language", "--job-id", JOB,
                                    "--target-language", "french", "--target-language", "German",
                                    "--poll-interval", "0")
        self.assertEqual((code, out["status"]), (0, "completed"), out)
        self.assertEqual(out["languages"], [
            {"target_language": "french", "image_url": "https://img/fr.png", "reused": True},
            {"target_language": "German", "image_url": "https://img/de.png"}])
        self.assertEqual(self.fake.sent("POST", f"{IT}/{JOB}/translate"), [{"targetLanguage": "German"}])
        self.assertFalse(ids_in(out, JOB, "v2"))

    def test_lines_are_numbered_and_a_change_rerenders_with_overrides(self) -> None:
        code, out = self.run_script("image-translation", "edit_text", "--job-id", JOB)
        self.assertEqual((code, [l["translation"] for l in out["lines"]]), (0, ["SOLDES", "Acme"]), out)
        self.assertFalse(ids_in(out, "r-a", "v1"))
        self.fake.routes[("GET", f"{IT}/{JOB}/translations/v2")] = {
            "status": "completed", "translatedImageUrl": "https://img/fr2.png", "targetLanguage": "French",
            "translationData": {"r-a": {"source": "SALE", "translated": "PROMO"},
                                "r-b": {"source": "Acme", "translated": "Acme", "kept": True}}}
        code, out = self.run_script("image-translation", "edit_text", "--job-id", JOB, "--set", "1=PROMO",
                                    "--keep", "2", "--poll-interval", "0")
        self.assertEqual((code, out["status"], out["image_url"]), (0, "edited", "https://img/fr2.png"), out)
        self.assertEqual(self.fake.sent("POST", f"{IT}/{JOB}/translate")[-1], {
            "targetLanguage": "French", "overrides": {"r-a": {"editedText": "PROMO"}, "r-b": {"action": "keep"}}})

    def test_verify_save_move_and_list_by_name(self) -> None:
        code, out = self.run_script("image-translation", "edit_text", "--job-id", JOB, "--verify", "all")
        self.assertEqual(self.fake.sent("PUT", f"{IT}/{JOB}/translations/v1/bulk-region-status")[0],
                         {"regionIds": ["r-a", "r-b"], "status": "v"})
        code, out = self.run_script("image-translation", "save_to_drive", "--job-id", JOB, "--folder", "Q3 creatives")
        self.assertEqual((code, out["status"], out["folder"]), (0, "saved", "Q3 creatives"), out)
        self.assertEqual(self.fake.sent("POST", f"{IT}/versions/v1/save-to-drive")[0], {"folderId": "d-1"})
        code, out = self.run_script("image-translation", "images", "move", "--job-id", JOB, "--folder", "diwali")
        self.assertEqual(self.fake.sent("PATCH", f"{IT}/{JOB}/folder")[0], {"folderId": "f-1"})
        code, out = self.run_script("image-translation", "images", "list")
        self.assertEqual(out["images"][0]["name"], "poster.png")
        self.assertEqual(out["images"][0]["languages"], ["French"])


AD = "/v1/galaxy/translate-photo/adapt"
STORY = {"id": "var-1", "status": "PLAN_PENDING", "targetConfig": {"width": 1080, "height": 1920, "label": "Story"},
         "reviewData": {"textReview": {"mapped_text": [
             {"original_id": "t9", "status": "typo", "detected_text": "SAEL", "suggested_correction": "SALE"},
             {"original_id": "t10", "status": "ok"}]},
             "visualReview": {"mapped_visuals": [{"original_id": "v3", "status": "missing", "element_type": "logo",
                                                  "factual_observation": "logo cut off",
                                                  "suggested_correction": "show the whole logo"}]}}}


class ResizeSizesTest(SkillCase):
    routes = {("GET", f"{AD}/asset-1/variants"): {"data": [STORY]},
              ("GET", f"{AD}/variants/var-1"): {"data": STORY},
              ("POST", f"{AD}/variants/var-1/approve-plan"): {"ok": True},
              ("POST", f"{AD}/variants/var-1/fix-issues"): {"ok": True},
              ("POST", f"{AD}/variants/export"): {"data": {"results": [
                  {"variantId": "var-1", "filename": "story.png", "base64": "UE5H"}], "failed": []}}}

    def test_pro_plan_is_approved_by_label_and_issues_fixed_by_number(self) -> None:
        code, out = self.run_script("image-resize", "sizes", "list", "--asset", "asset-1")
        self.assertEqual(out["sizes"][0]["size"], "Story")
        self.assertIn("approve", out["sizes"][0]["next"])
        self.assertEqual(out["sizes"][0]["issues"], 2)
        code, out = self.run_script("image-resize", "sizes", "approve", "--asset", "asset-1", "--size", "1080x1920")
        self.assertEqual((code, out["status"]), (0, "approved"))
        code, out = self.run_script("image-resize", "sizes", "fix", "--asset", "asset-1", "--size", "story",
                                    "--issues", "2")
        self.assertEqual(self.fake.sent("POST", f"{AD}/variants/var-1/fix-issues")[0], {"selectedIssueIds": ["v3"]})
        self.assertFalse(ids_in(out, "var-1", "v3"))

    def test_export_writes_each_size(self) -> None:
        code, out = self.run_script("image-resize", "sizes", "export", "--asset", "asset-1",
                                    "--out-dir", str(self.dir / "o"))
        self.assertEqual((code, out["status"]), (0, "exported"), out)
        self.assertEqual(Path(out["files"][0]["path"]).read_bytes(), b"PNG")


SEGS = {"data": [
    {"id": "01", "segmentId": "s-0", "layerIndex": 0, "source": "Welcome", "target": "Bienvenu", "status": "unverified",
     "location": {"label": "Slide 1"}},
    {"id": "02", "segmentId": "s-1", "layerIndex": 1, "source": "Price", "target": "Prix", "status": "verified"}],
    "total": 2}


class DocumentEditTest(SkillCase):
    routes = {("GET", f"{DOC}/logs/t1/segments"): SEGS,
              ("PUT", f"{DOC}/update-phrase"): {"ok": True},
              ("PUT", f"{DOC}/bulk-verify-phrases"): {"ok": True},
              ("PUT", f"{DOC}/sync-to-tm"): {"ok": True},
              ("GET", "/v1/folder"): [{"id": "f-9", "name": "Contracts"}],
              ("PATCH", f"{DOC}/logs/t1/folder"): {"ok": True},
              ("GET", f"{DOC}/logs"): {"data": [{"id": "t1", "name": "contract.docx", "sourceLanguage": "English",
                                                 "targetLanguage": "French", "status": "DONE",
                                                 "PlaygroundLogTm": {"name": "Acme"}}], "totalLogs": 1}}

    def test_lines_are_numbered_with_where_and_corrected_by_number(self) -> None:
        code, out = self.run_script("document-translation", "edit_document", "--translation", "t1")
        self.assertEqual((code, out["lines"][0]), (0, {"line": 1, "source": "Welcome", "translation": "Bienvenu",
                                                        "status": "unverified", "where": "Slide 1"}))
        self.assertFalse(ids_in(out, "s-0"))
        code, out = self.run_script("document-translation", "edit_document", "--translation", "t1",
                                    "--set", "1=Bienvenue", "--everywhere", "--verify", "all", "--sync-to-memory")
        self.assertEqual(out["changed"], [{"line": 1, "before": "Bienvenu", "after": "Bienvenue"}])
        self.assertEqual(self.fake.sent("PUT", f"{DOC}/update-phrase")[0], {
            "playgroundLogId": "t1", "sourceText": "Welcome", "updatePhrase": "Bienvenue", "layerIndex": 0,
            "propagateToDuplicates": True})
        self.assertEqual(self.fake.sent("PUT", f"{DOC}/bulk-verify-phrases")[0]["layers"], [0, 1])
        self.assertEqual(self.fake.sent("PUT", f"{DOC}/sync-to-tm")[0], {"playgroundLogId": "t1"})

    def test_past_translations_listed_by_name_and_moved_by_folder_name(self) -> None:
        code, out = self.run_script("document-translation", "documents", "list")
        self.assertEqual((out["documents"][0]["name"], out["documents"][0]["memory"]), ("contract.docx", "Acme"))
        self.run_script("document-translation", "documents", "move", "--translation", "t1", "--folder", "Contracts")
        self.assertEqual(self.fake.sent("PATCH", f"{DOC}/logs/t1/folder")[0], {"folderId": "f-9"})


PG = "/v1/galaxy/playground"


class PlaygroundFollowUpsTest(SkillCase):
    routes = {("POST", f"{PG}/lip-sync/quote"): {"credits": 90, "balance": 50, "seconds": 45, "model": "sync-3"},
              ("GET", f"{PG}/voice-clone"): {"data": [{"id": "vc-1", "name": "Priya"}]},
              ("DELETE", f"{PG}/voice-clone/vc-1"): {"ok": True},
              ("POST", f"{PG}/tts/sessions/sess-1/save-to-assets"): {"data": {"name": "Welcome VO"}}}

    def test_lip_sync_quote_says_whether_the_balance_covers_it(self) -> None:
        code, out = self.run_script("lip-sync", "lipsyncs", "quote", "--seconds", "45")
        self.assertEqual((code, out["credits"], out["enough"]), (0, 90, False))

    def test_a_clone_is_deleted_by_name_after_a_yes(self) -> None:
        code, out = self.run_script("voice-cloning", "clones", "delete", "--voice", "priya")
        self.assertEqual(out["error"]["code"], "CONFIRM_NEEDED")
        self.assertEqual(self.fake.sent("DELETE", f"{PG}/voice-clone/vc-1"), [])
        code, out = self.run_script("voice-cloning", "clones", "delete", "--voice", "priya", "--confirm")
        self.assertEqual((code, out["status"]), (0, "deleted"))

    def test_speech_is_saved_to_the_drive(self) -> None:
        code, out = self.run_script("text-to-speech", "save_speech", "--speech", "sess-1", "--name", "Welcome VO")
        self.assertEqual((code, out["status"], out["file"]), (0, "saved", "Welcome VO"))


PLV = "/v1/galaxy/translate-video/process-log"


class JobToolsTest(SkillCase):
    routes = {("POST", f"{PLV}/job-1/cancel"): {"ok": True},
              ("POST", f"{PLV}/job-1/sync-to-tm"): {"operationId": None, "total": 42},
              ("GET", f"{PLV}/job-1/excel-data"): [{"Line": 1, "English": "Hi", "Hindi": "नमस्ते"}],
              ("GET", "/v1/folder"): [{"id": "f-2", "name": "Webinars"}],
              ("PATCH", f"{PLV}/job-1/folder"): {"ok": True}}

    def test_cancel_asks_first_and_sync_reports_counts(self) -> None:
        for skill in ("video-dubbing", "video-subtitles"):
            code, out = self.run_script(skill, "job_tools", "cancel", "--job-id", "job-1")
            self.assertEqual(out["error"]["code"], "CONFIRM_NEEDED")
        self.assertEqual(self.fake.sent("POST", f"{PLV}/job-1/cancel"), [])
        code, out = self.run_script("video-dubbing", "job_tools", "sync", "--job-id", "job-1", "--to-memory")
        self.assertEqual((code, out), (0, {"status": "synced_to_memory", "lines": 42}))

    def test_sheet_is_a_csv_excel_can_open_and_move_goes_by_folder_name(self) -> None:
        code, out = self.run_script("video-dubbing", "job_tools", "sheet", "--job-id", "job-1",
                                    "--out", str(self.dir / "lines.csv"))
        self.assertEqual((code, out["rows"]), (0, 1), out)
        self.assertIn("नमस्ते", (self.dir / "lines.csv").read_text(encoding="utf-8-sig"))
        self.run_script("video-subtitles", "job_tools", "move", "--job-id", "job-1", "--folder", "webinars")
        self.assertEqual(self.fake.sent("PATCH", f"{PLV}/job-1/folder")[0], {"folderId": "f-2"})


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
