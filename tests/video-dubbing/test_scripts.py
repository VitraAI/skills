"""End-to-end tests of the skill's scripts against the fake Universe server.

Each test runs the REAL script as a subprocess (exactly as an agent would),
parses its one line of JSON, and checks both the output and what the server
received. Run from the skill folder:

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).parent))
from fake_server import JOB, PL, UPLOAD, FakeServer  # noqa: E402

SCRIPTS = Path(__file__).resolve().parents[2] / "video-dubbing" / "scripts"


class SkillTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer().__enter__()
        self.state_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.state_dir.cleanup)
        self.addCleanup(self.server.__exit__, None, None, None)

    @property
    def st(self) -> dict:
        return self.server.state

    def run_script(self, name: str, *args: str) -> tuple[int, dict, str]:
        env = {
            **os.environ,
            "VITRA_UNIVERSE_API_KEY": "uvk_test",
            "VITRA_UNIVERSE_BASE_URL": self.server.base,
            "VITRA_DUB_STATE_DIR": self.state_dir.name,
            "VITRA_DUB_FAST_POLL": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        proc = subprocess.run(
            [sys.executable, str(SCRIPTS / f"{name}.py"), *args],
            capture_output=True, text=True, env=env, timeout=60,
        )
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertLessEqual(len(lines), 1, f"{name} printed more than one JSON line:\n{proc.stdout}")
        out = json.loads(lines[0]) if lines else {}
        return proc.returncode, out, proc.stderr

    def manifest(self) -> dict:
        path = Path(self.state_dir.name) / f"{JOB}.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def calls(self, method: str, path: str) -> list:
        return [c for c in self.st["calls"] if c[0] == method and c[1] == path]


class PatchCardsTest(SkillTestCase):
    def test_text_timing_emotion_chain_revisions(self) -> None:
        edits = [{"card_id": "c1", "text": "नमस्ते दोस्त", "end": 2.5, "emotion": "calm"}]
        code, out, err = self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                                         "--revision", "3", "--edits", json.dumps(edits))
        self.assertEqual(code, 0, err)
        self.assertEqual(out["status"], "patched")
        self.assertEqual({c["field"] for c in out["changes"]}, {"text", "end", "emotion"})
        # New text: the server removed the audio (not stale — missing).
        self.assertEqual(out["audio_cleared"], ["c1"])
        self.assertEqual(out["audio_stale"], [])
        self.assertEqual(out["next_action"], "regenerate_cards")
        self.assertEqual(out["revision_after"], 5)  # two guarded writes chained
        card = self.server.card("c1")["hindi"]
        # tr and v sent WHOLE: confidence and rate survive the one-level merge.
        self.assertEqual(card["tr"]["c"], 0.9)
        self.assertEqual(card["tr"]["wc"], 2)
        self.assertEqual(card["v"], {"st": 0.0, "et": 2.5, "r": 1})
        self.assertEqual(card["emotion"], "calm")
        self.assertIsNone(card["a"])
        self.assertEqual(self.manifest()["audio_stale"]["hindi"], [])

    def test_emotion_change_keeps_audio_and_marks_it_stale(self) -> None:
        code, out, _ = self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                                       "--edits", '[{"card_id": "c1", "emotion": "calm"}]')
        self.assertEqual((code, out["audio_stale"], out["audio_cleared"]), (0, ["c1"], []))

    def test_old_server_keeping_audio_after_text_edit_is_still_caught(self) -> None:
        self.st["clear_audio_on_text"] = False
        code, out, _ = self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                                       "--edits", '{"c1": "नया"}')
        self.assertEqual((out["audio_stale"], out["audio_cleared"]), (["c1"], []))

    def test_stale_revision_is_refused_before_sending(self) -> None:
        code, out, _ = self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                                       "--revision", "2", "--edits", '{"c1": "x"}')
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "REVISION_CONFLICT")
        self.assertEqual(out["error"]["current_revision"], 3)
        self.assertEqual(out["request_id"], "req-test-1")
        self.assertEqual(self.calls("POST", f"{PL}/transcript/action"), [])

    def test_overlap_and_bad_values_change_nothing(self) -> None:
        for edits in ([{"card_id": "c1", "end": 3.5}],            # runs into c2
                      [{"card_id": "c2", "emotion": "sleepy"}],    # not a server emotion
                      [{"card_id": "c1", "rate": 3}],              # outside 0.5–2
                      [{"card_id": "c1", "text": "ok"}, {"card_id": "zz", "text": "no"}]):
            code, out, _ = self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                                           "--edits", json.dumps(edits))
            self.assertNotEqual(code, 0, edits)
            self.assertEqual(out["status"], "failed")
        self.assertEqual(self.calls("POST", f"{PL}/transcript/action"), [])

    def test_source_text_lists_affected_languages(self) -> None:
        code, out, _ = self.run_script("patch_cards", "--job-id", JOB, "--language", "english",
                                       "--edits", '{"c2": "How are you doing"}')
        self.assertEqual(code, 0)
        self.assertEqual(out["affected_languages"], ["hindi"])
        self.assertEqual(out["audio_stale"], [])
        code, out, _ = self.run_script("patch_cards", "--job-id", JOB, "--language", "english",
                                       "--edits", '[{"card_id": "c2", "emotion": "calm"}]')
        self.assertNotEqual(code, 0)

    def test_review_status_volume_and_flags(self) -> None:
        edits = [{"card_id": "c1", "review_status": "a", "volume": 0.5, "lip_sync": True}]
        code, out, err = self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                                         "--edits", json.dumps(edits))
        self.assertEqual(code, 0, err)
        blk = self.server.card("c1")["hindi"]
        self.assertEqual((blk["rs"], blk["a"]["volume"], blk["isLipSync"]), ("a", 0.5, True))
        self.assertEqual(out["next_action"], "list_issues")


class RegenerateTest(SkillTestCase):
    def test_missing_audio_is_regenerated_and_verified_by_hash(self) -> None:
        code, out, err = self.run_script("regenerate_cards", "--job-id", JOB, "--language", "hindi", "--missing")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["status"], "regenerated")
        self.assertEqual([c["card_id"] for c in out["cards"]], ["c3"])
        self.assertTrue(out["cards"][0]["audio_changed"])
        body = self.calls("POST", f"{PL}/{JOB}/generate-all")[0][2]
        self.assertEqual(body["transcriptIds"], ["c3"])

    def test_same_url_new_bytes_counts_as_changed(self) -> None:
        code, out, _ = self.run_script("regenerate_cards", "--job-id", JOB, "--language", "hindi",
                                       "--card-ids", "c1")
        self.assertEqual(code, 0)
        self.assertTrue(out["cards"][0]["audio_changed"])
        self.assertTrue(out["cards"][0]["verified"])

    def test_unchanged_audio_is_not_counted_as_fixed(self) -> None:
        self.st["on_child_done"] = lambda state, child: None  # job "succeeds", changes nothing
        code, out, _ = self.run_script("regenerate_cards", "--job-id", JOB, "--language", "hindi",
                                       "--card-ids", "c1")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["status"], "partial")
        self.assertFalse(out["cards"][0]["audio_changed"])


class AddLanguageTest(SkillTestCase):
    def test_reuses_each_speakers_clone(self) -> None:
        code, out, err = self.run_script("add_language", "--job-id", JOB, "--language", "tamil",
                                         "--voice-map", '{"2": {"*": "lib-voice-9"}}', "--expected-revision", "3")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["status"], "review_ready")
        body = self.st["last_add_body"]
        self.assertEqual(body["voices"]["1"]["voiceId"], "clone-1")
        self.assertEqual(body["voices"]["2"]["voiceId"], "lib-voice-9")
        self.assertEqual(body["expectedSourceRevision"], 3)
        self.assertTrue(self.calls("POST", f"{PL}/{JOB}/add-language")[0][3].get("Idempotency-Key"))

    def test_speaker_without_a_voice_needs_a_decision(self) -> None:
        code, out, _ = self.run_script("add_language", "--job-id", JOB, "--language", "tamil")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "VOICE_DECISION_NEEDED")
        self.assertEqual(out["error"]["speakers"], ["2"])
        self.assertEqual(self.calls("POST", f"{PL}/{JOB}/add-language"), [])

    def test_failure_is_rolled_back(self) -> None:
        self.st["child_outcome"] = "FAILED"
        code, out, _ = self.run_script("add_language", "--job-id", JOB, "--language", "tamil",
                                       "--voice-map", '{"2": {"*": "v"}}')
        self.assertNotEqual(code, 0)
        self.assertEqual(out["status"], "failed")
        self.assertEqual(self.st["rolled_back"], "tamil")

    def test_existing_language_is_not_added_twice(self) -> None:
        code, out, _ = self.run_script("add_language", "--job-id", JOB, "--language", "hindi")
        self.assertEqual((code, out["status"]), (0, "exists"))


class FixIssuesTest(SkillTestCase):
    def test_only_missing_audio_uses_scoped_regeneration(self) -> None:
        self.st["issues"]["hindi"] = {"errors": [{"transcriptId": "c3", "type": "No Audio Error", "msg": "no audio"}],
                                      "warnings": []}

        def done(state, child):
            state["cards"][2]["hindi"]["a"] = {"url": "u", "d": 2, "r": 1}
            state["issues"]["hindi"] = {"errors": [], "warnings": []}
        self.st["on_child_done"] = done
        code, out, err = self.run_script("fix_issues", "--job-id", JOB, "--language", "hindi")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["status"], "clean")
        self.assertEqual(self.calls("POST", f"{PL}/{JOB}/autofix-all"), [])
        self.assertEqual(self.calls("POST", f"{PL}/{JOB}/generate-all")[0][2]["transcriptIds"], ["c3"])

    def test_autofix_discloses_changes_to_approved_text(self) -> None:
        self.st["issues"]["hindi"] = {"errors": [{"transcriptId": "c2", "type": "Rate Error", "msg": "too fast"},
                                                 {"transcriptId": "c1", "type": "Start Time Error", "msg": "x"}],
                                      "warnings": []}

        def done(state, child):
            state["cards"][1]["hindi"]["tr"]["text"] = "कैसे हो"
            state["cards"][1]["hindi"]["a"]["r"] = 1.2
            state["issues"]["hindi"]["errors"] = [e for e in state["issues"]["hindi"]["errors"]
                                                  if e["type"] != "Rate Error"]
        self.st["on_child_done"] = done
        code, out, _ = self.run_script("fix_issues", "--job-id", JOB, "--language", "hindi", "--budget", "3")
        self.assertNotEqual(code, 0)  # a timing error remains: not autofixable
        self.assertEqual(out["status"], "partial")
        self.assertEqual(out["attempts"], 1)  # stopped: nothing left it can fix
        self.assertEqual(out["approved_text_changed"][0]["card_id"], "c2")
        self.assertEqual(out["remaining_errors"][0]["type"], "Start Time Error")
        self.assertEqual(out["next_action"], "patch_cards")


class CardOpsTest(SkillTestCase):
    def test_split_must_keep_the_words(self) -> None:
        code, out, _ = self.run_script("card_ops", "split", "--job-id", JOB, "--card-id", "c1",
                                       "--chunks", '["Hello", "friend"]')
        self.assertNotEqual(code, 0)
        code, out, err = self.run_script("card_ops", "split", "--job-id", JOB, "--card-id", "c1",
                                         "--chunks", '["Hello", "there"]')
        self.assertEqual(code, 0, err)
        self.assertEqual(out["next_action"], "retranslate")
        self.assertEqual(self.st["last_action"]["expectedRevision"], 3)

    def test_speaker_voice_reports_cleared_cards(self) -> None:
        code, out, err = self.run_script("card_ops", "speaker-voice", "--job-id", JOB, "--speaker-id", "1",
                                         "--language", "hindi", "--voice-id", "v2", "--voice-name", "Aria")
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(out["cards"]), ["c1", "c2", "c3"])
        self.assertEqual(out["next_action"], "regenerate_cards")
        self.assertEqual(self.manifest()["voice_map"]["1"]["hindi"], "v2")

    def test_add_must_fit_the_gap(self) -> None:
        code, _, _ = self.run_script("card_ops", "add", "--job-id", JOB, "--after", "c1",
                                     "--start", "1.5", "--end", "2.8")
        self.assertNotEqual(code, 0)
        code, out, err = self.run_script("card_ops", "add", "--job-id", JOB, "--after", "c1",
                                         "--start", "2.1", "--end", "2.9", "--text", "Wait")
        self.assertEqual(code, 0, err)
        added = self.st["cards"][1]
        self.assertEqual(added["english"]["speakerId"], "1")
        self.assertEqual(added["hindi"]["v"], {"st": 2.1, "et": 2.9, "r": 1})

    def test_speak_revoices_one_line(self) -> None:
        code, out, err = self.run_script("card_ops", "speak", "--job-id", JOB, "--card-id", "c3",
                                         "--language", "hindi", "--voice-id", "v7", "--voice-name", "Priya")
        self.assertEqual(code, 0, err)
        self.assertTrue(out["audio"]["changed"])
        body = self.calls("POST", f"{PL}/sync-services/action")[0][2]
        self.assertEqual(body["data"]["voice"], {"voiceId": "v7", "voiceName": "Priya"})

    def test_subtitle_merge_and_split(self) -> None:
        code, _, err = self.run_script("card_ops", "sub-merge", "--job-id", JOB, "--card-id", "c1",
                                       "--language", "hindi", "--subtitle-ids", "c1-s1,c1-s2")
        self.assertEqual(code, 0, err)
        merged = self.st["last_subtitle_action"]["data"]["merged"]
        self.assertEqual((merged["t"], merged["text"]), ({"st": 0.0, "et": 2.0}, "first half second half"))
        code, _, err = self.run_script("card_ops", "sub-split", "--job-id", JOB, "--card-id", "c1",
                                       "--language", "hindi", "--subtitle-id", "c1-s1", "--at-word", "1")
        self.assertEqual(code, 0, err)
        parts = self.st["last_subtitle_action"]["data"]["subtitles"]
        self.assertEqual([p["text"] for p in parts], ["first", "half"])


class LiveFindingsTest(SkillTestCase):
    """Regressions for what the devbox pilot exposed."""

    def test_saved_clone_is_sent_typed(self) -> None:
        # The gate profile lacks voiceType (as resume_dub used to write it).
        self.st["speakers"]["1"]["hindi"] = {"voiceId": "clone-1", "voiceName": ""}
        code, out, err = self.run_script("card_ops", "speak", "--job-id", JOB, "--card-id", "c1",
                                         "--language", "hindi")
        self.assertEqual(code, 0, err)
        body = self.calls("POST", f"{PL}/sync-services/action")[0][2]
        self.assertEqual(body["data"]["voice"]["voiceType"], "instant-clone")

    def test_resume_types_a_saved_clone(self) -> None:
        self.st["awaiting"] = True
        self.st["status"] = "running"
        code, out, err = self.run_script("resume_dub", "--job-id", JOB, "--voice-map", '{"1": {"*": "clone-1"}}')
        self.assertEqual((code, out["status"]), (0, "review_ready"), err)
        body = self.calls("POST", f"{PL}/{JOB}/human-validation")[0][2]
        self.assertEqual(body["speakers"]["1"]["hindi"]["voiceType"], "instant-clone")
        self.assertEqual(body["speakers"]["1"]["hindi"]["voiceName"], "Speaker 1")

    def test_reports_the_rate_actually_saved(self) -> None:
        code, out, _ = self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                                       "--edits", '[{"card_id": "c1", "rate": 1.1}]')
        self.assertEqual(code, 0)
        change = out["changes"][0]
        self.assertEqual((change["requested"], change["after"], change["adjusted_by_server"]), (1.1, 0.9041, True))

    def test_stale_list_is_pruned_for_removed_cards(self) -> None:
        self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                        "--edits", '[{"card_id": "c1", "emotion": "calm"}]')
        self.run_script("card_ops", "delete", "--job-id", JOB, "--card-id", "c1")
        code, out, err = self.run_script("export_dub", "--job-id", JOB, "--language", "hindi")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["status"], "exported")
        self.assertEqual(self.manifest()["audio_stale"]["hindi"], [])

    def test_add_language_recovers_after_a_lost_reply(self) -> None:
        self.st["targets"].append("tamil")
        self.st["children"].append({"id": "add-1", "operation": "ADD_LANGUAGE", "language": "tamil",
                                    "status": "DONE", "progress": 100, "errorMessage": None, "polls": 0})
        code, out, _ = self.run_script("add_language", "--job-id", JOB, "--language", "tamil")
        self.assertEqual((code, out["status"]), (0, "review_ready"))
        self.assertEqual(self.manifest()["languages"]["tamil"]["status"], "review_ready")


class GuidanceTest(SkillTestCase):
    """Progress, suggestions and the access check: what the agent relays."""

    def test_progress_matches_the_webapp_steps(self) -> None:
        self.st["status"] = "running"
        self.st["tasks"] = [
            {"taskIdentifier": "DOWNLOAD", "status": "completed", "progress": 100},
            {"taskIdentifier": "AUDIO-EXTRACTOR", "status": "completed", "progress": 100},
            {"taskIdentifier": "TRANSCRIPTION-ENGINE", "status": "running", "progress": 40},
        ]
        code, out, _ = self.run_script("inspect_process", "--job-id", JOB)
        progress = out["progress"]
        self.assertEqual([s["title"] for s in progress["steps"]][:2],
                         ["Analysing the video", "Transcribing the video"])
        self.assertEqual(progress["steps"][1], {"title": "Transcribing the video",
                                                "status": "in-progress", "percent": 40})
        self.assertEqual(progress["summary"], "Step 2 of 6: Transcribing the video, 40%")
        self.assertEqual(out["suggestions"][0]["run"].split(".py")[0], "inspect_process")

    def test_progress_marks_the_voice_step_as_waiting(self) -> None:
        self.st["status"], self.st["awaiting"] = "running", True
        self.st["tasks"] = [{"taskIdentifier": "INSTANT-VOICE-CLONING-ENGINE", "status": "running", "progress": 0}]
        _, out, _ = self.run_script("inspect_process", "--job-id", JOB)
        self.assertIn("waiting for your decision", out["progress"]["summary"])
        self.assertEqual(out["suggestions"][0]["run"].split(".py")[0], "resume_dub")

    def test_suggestions_put_blocking_work_before_export(self) -> None:
        self.st["issues"]["hindi"] = {"errors": [{"transcriptId": "c2", "type": "Rate Error", "msg": "x"}],
                                      "warnings": []}
        _, out, _ = self.run_script("inspect_process", "--job-id", JOB)
        runs = [s["run"].split(".py")[0] for s in out["suggestions"]]
        self.assertEqual(runs, ["regenerate_cards"])  # c3 has no audio: that comes first
        self.assertTrue(out["suggestions"][0]["spends_credits"])
        self.assertEqual(out["cards"]["hindi"], {"total": 3, "with_audio": 2, "unreviewed": 2})

    def test_clean_language_suggests_review_then_export(self) -> None:
        self.st["cards"][2]["hindi"]["a"] = {"url": "u", "d": 2, "r": 1}
        _, out, _ = self.run_script("inspect_process", "--job-id", JOB)
        runs = [s["run"].split(".py")[0] for s in out["suggestions"]]
        self.assertEqual(runs, ["inspect_process", "export_dub"])
        self.assertEqual(out["next_action"], "inspect_process")

    def test_access_check_blocks_on_a_missing_required_step(self) -> None:
        self.st["permissions"] = ["translate_video.process_log:read", "translate_video.upload:create",
                                  "translate_video.process_log:create", "translation_memory:read"]
        _, out, _ = self.run_script("check_access")
        self.assertEqual(out["status"], "blocked")
        missing = {c["step"] for c in out["cannot"] if not c["optional"]}
        self.assertIn("Export and download", missing)
        self.assertIsNone(out["next_action"])

    def test_access_check_names_the_plan_when_the_product_is_off(self) -> None:
        self.st["permissions"] = ["translation_memory:read"]
        self.st["entitlements"] = {"galaxies": {"translate_video": False}, "modules": {}, "resourceModules": {}}
        _, out, _ = self.run_script("check_access")
        self.assertIn("plan", out["cannot"][0]["reason"])

    def test_access_check_is_unknown_on_an_older_server(self) -> None:
        _, out, _ = self.run_script("check_access")
        self.assertEqual((out["status"], out["next_action"]), ("unknown", "collect_inputs"))


class ExportAndDownloadTest(SkillTestCase):
    def test_stale_audio_blocks_export(self) -> None:
        self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                        "--edits", '[{"card_id": "c1", "emotion": "calm"}]')
        code, out, _ = self.run_script("export_dub", "--job-id", JOB, "--language", "hindi")
        self.assertEqual((code, out["status"], out["reason"]), (0, "refused", "stale_audio"))
        self.assertEqual(self.calls("POST", f"{PL}/export-video"), [])

    def test_changed_revision_blocks_export(self) -> None:
        code, out, _ = self.run_script("export_dub", "--job-id", JOB, "--language", "hindi", "--revision", "1")
        self.assertEqual(out["reason"], "revision_changed")

    def test_export_then_download_with_basic_check(self) -> None:
        code, out, err = self.run_script("export_dub", "--job-id", JOB, "--language", "hindi", "--revision", "3")
        self.assertEqual(code, 0, err)
        self.assertEqual(out["status"], "exported")
        self.assertTrue(self.st["last_export_headers"].get("Idempotency-Key"))
        # Same revision again: reused, not re-rendered.
        code, again, _ = self.run_script("export_dub", "--job-id", JOB, "--language", "hindi", "--revision", "3")
        self.assertTrue(again.get("reused"))
        self.assertEqual(len(self.calls("POST", f"{PL}/export-video")), 1)

        dest = Path(self.state_dir.name) / "out" / "dub.mp4"
        env_path = os.environ.get("PATH", "")
        os.environ["PATH"] = "/nonexistent"  # force the no-ffmpeg path
        try:
            code, dl, err = self.run_script("download_export", "--export-id", out["export_id"], "--out", str(dest))
        finally:
            os.environ["PATH"] = env_path
        self.assertEqual(code, 0, err)
        self.assertEqual(dl["media_check"], "basic")
        self.assertTrue(dest.exists())
        self.assertFalse(dest.with_suffix(".mp4.partial").exists())

    def test_failed_render_is_reported_not_waited_on(self) -> None:
        self.st["export_should_fail"] = True
        code, out, _ = self.run_script("export_dub", "--job-id", JOB, "--language", "hindi", "--max-wait", "30")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "EXPORT_FAILED")


class RecoveryTest(SkillTestCase):
    def _video(self) -> Path:
        import hashlib

        path = Path(self.state_dir.name) / "talk.mp4"
        path.write_bytes(b"not really a video, but hashable")
        self.st["uploads"][0]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return path

    def test_dub_video_reuses_upload_and_run_instead_of_publishing(self) -> None:
        video = self._video()
        code, out, err = self.run_script("dub_video", "--file", str(video), "--source-language", "english",
                                         "--target-language", "hindi", "--tm-id", "tm-1")
        self.assertEqual(code, 0, err)
        self.assertEqual((out["status"], out["job_id"]), ("review_ready", JOB))
        self.assertEqual(self.calls("POST", f"{PL}/publish"), [])
        self.assertEqual(self.calls("POST", "/v1/galaxy/translate-video/upload"), [])
        self.assertEqual(self.manifest()["upload_id"], UPLOAD)
        self.assertTrue(self.manifest()["emotion_detection"])

    def test_dub_video_does_not_trust_a_server_that_ignores_the_filter(self) -> None:
        video = self._video()
        self.st["upload_filter"] = False
        self.st["processes"][0]["upload"] = "someone-else"
        code, out, _ = self.run_script("dub_video", "--file", str(video), "--source-language", "english",
                                       "--target-language", "hindi", "--tm-id", "tm-1")
        # Would have reused another video's run; instead it publishes (the fake
        # has no publish route, so the attempt itself is the proof).
        self.assertEqual(len(self.calls("POST", f"{PL}/publish")), 1)
        body = self.calls("POST", f"{PL}/publish")[0][2]
        self.assertTrue(body["inputData"]["emotionDetection"])

    def test_retry_resumes_to_review(self) -> None:
        self.st["status"] = "failed"
        code, out, err = self.run_script("retry_dub", "--job-id", JOB)
        self.assertEqual(code, 0, err)
        self.assertEqual(out["status"], "review_ready")

    def test_retry_refused_is_explained(self) -> None:
        self.st["retry_status"] = 409
        code, out, _ = self.run_script("retry_dub", "--job-id", JOB)
        self.assertNotEqual(code, 0)
        self.assertIn("Only a failed process", out["error"]["message"])

    def test_list_assets_finds_dubs_and_detects_old_servers(self) -> None:
        code, out, _ = self.run_script("list_assets", "--sha256", "a" * 64)
        self.assertEqual(out["assets"][0]["dubs"][0]["job_id"], JOB)
        self.st["upload_filter"] = False  # an older server ignores ?uploadId=
        code, out, _ = self.run_script("list_assets", "--sha256", "a" * 64)
        self.assertIsNone(out["assets"][0]["dubs"])
        self.assertFalse(out["dub_lookup_supported"])

    def test_manifest_validate_reports_drift(self) -> None:
        self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                        "--edits", '[{"card_id": "c1", "emotion": "calm"}]')
        self.st["targets"].append("tamil")
        self.st["revision"] += 5
        code, out, _ = self.run_script("run_manifest", "validate", "--job-id", JOB)
        self.assertEqual(out["status"], "drift")
        whats = {d["what"] for d in out["drift"]}
        self.assertIn("languages added elsewhere", whats)
        self.assertIn("transcript edited since this record", whats)

    def test_inspect_reports_settings_usage_and_stale(self) -> None:
        self.run_script("patch_cards", "--job-id", JOB, "--language", "hindi",
                        "--edits", '[{"card_id": "c1", "emotion": "calm"}]')
        code, out, err = self.run_script("inspect_process", "--job-id", JOB)
        self.assertEqual(code, 0, err)
        self.assertTrue(out["settings"]["emotion_detection"])
        self.assertEqual(out["usage"]["credit_balance"], 120.5)
        self.assertEqual(out["audio_stale"], {"hindi": ["c1"]})

    def test_card_media_separates_raw_from_playback(self) -> None:
        code, out, err = self.run_script("get_card_media", "--job-id", JOB, "--card-id", "c1",
                                         "--language", "hindi", "--download", self.state_dir.name)
        self.assertEqual(code, 0, err)
        self.assertTrue(out["raw_audio"]["available"])
        self.assertFalse(out["playback_audio"]["available"])
        self.assertEqual(out["source"]["start"], 0.0)
        self.assertTrue(Path(out["raw_audio"]["path"]).exists())


if __name__ == "__main__":
    unittest.main()
