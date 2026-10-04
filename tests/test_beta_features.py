import hashlib
import json
import os
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import app
from chat_history import ChatHistory
from desktop_pet import DesktopPet
from local_agent import LocalAgentConfig, LocalCartethyiaAgent, list_service_models, service_base, discover_local_models
from update_manager import prepare_update, install_script


def response_context(payload):
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
    return response


class ApiTests(unittest.TestCase):
    def test_models_for_all_providers(self):
        for provider, base, suffix, payload in (
            ("ollama", "http://localhost:11434", "/api/tags", {"models": [{"name": "small:4b"}]}),
            ("openai", "http://localhost:1234/v1", "/models", {"data": [{"id": "local"}]}),
            ("deepseek", "https://api.deepseek.com", "/models", {"data": [{"id": "cloud"}]}),
        ):
            with self.subTest(provider=provider), patch("local_agent.urllib.request.urlopen", return_value=response_context(payload)) as request:
                names = list_service_models(LocalAgentConfig(provider=provider, endpoint=base, api_key="secret"))
                self.assertEqual(len(names), 1)
                self.assertEqual(request.call_args.args[0].full_url, base + suffix)
                self.assertEqual(request.call_args.args[0].get_header("Authorization"), None if provider == "ollama" else "Bearer secret")

    def test_api_reply_and_payload(self):
        for provider in ("deepseek", "openai"):
            config = LocalAgentConfig(True, "https://api.example.com/v1", "selected", provider, "secret")
            agent = LocalCartethyiaAgent(config, "persona")
            with patch("local_agent.urllib.request.urlopen", return_value=response_context({"choices": [{"message": {"content": "今天天气不错。"}}]})) as request:
                reply = agent.respond("我们聊聊今天的天气吧")
            self.assertEqual(reply.text, "今天天气不错。")
            body = json.loads(request.call_args.args[0].data)
            self.assertNotIn("keep_alive", body)
            self.assertNotIn("format", body)
            self.assertNotIn("/no_think", body["messages"][-1]["content"])
            self.assertEqual(request.call_args.args[0].full_url, "https://api.example.com/v1/chat/completions")

    def test_api_does_not_load_or_unload_local_models(self):
        agent = LocalCartethyiaAgent(LocalAgentConfig(True, "https://api.deepseek.com", "model", "deepseek"), "persona")
        with patch("local_agent.urllib.request.urlopen") as request:
            agent.warmup()
            agent.unload()
            request.assert_not_called()

    def test_key_not_saved_or_printed(self):
        config = LocalAgentConfig(True, "https://api.deepseek.com", "model", "deepseek", "private-key")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            config.save(path)
            self.assertNotIn("private-key", path.read_text())
            self.assertNotIn("private-key", repr(config))
            self.assertEqual(LocalAgentConfig.load(path).provider, "deepseek")
            self.assertEqual(LocalAgentConfig.load(path).api_key, "")

    def test_invalid_address(self):
        for url in ("file:///secret", "https://user:key@host/v1", "https://host?key=secret"):
            with self.assertRaises(ValueError):
                service_base(LocalAgentConfig(endpoint=url))

    def test_discovery_deduplicates_online_and_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "manifests/registry.ollama.ai/library/small/4b"
            manifest.parent.mkdir(parents=True)
            manifest.touch()
            with patch.dict("os.environ", {"OLLAMA_MODELS": tmp}), patch("local_agent.Path.home", return_value=Path(tmp)), patch("local_agent.list_service_models", side_effect=lambda config, **kw: ["small:4b"] if config.provider == "ollama" else []):
                models = discover_local_models()
            self.assertEqual(len(models), 1)
            self.assertTrue(models[0].available)


class InteractionTests(unittest.TestCase):
    def test_task_bindings_are_saved_without_button(self):
        instance = app.App.__new__(app.App)
        instance.combat_skill_key = Mock()
        instance.combat_skill_key.get.return_value = "Q"
        instance.combat_skill_key.set = Mock()
        instance.combat_ultimate_key = Mock()
        instance.combat_ultimate_key.get.return_value = "鼠标侧键2"
        instance.combat_ultimate_key.set = Mock()
        instance.status = Mock()
        instance._log = Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "COMBAT_CONFIG", Path(tmp) / "combat.json"):
            instance._autosave_combat_settings()
            saved = json.loads(app.COMBAT_CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved, {"skill_key": "Q", "ultimate_key": "XBUTTON2"})
        instance.status.set.assert_called_once_with("战斗键位已自动保存")

    def test_history_persists_and_separates_pets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            history = ChatHistory(path)
            history.append("cartethyia", "你", "你好")
            history.append("jingran", "你", "早上好")
            self.assertEqual(ChatHistory(path).messages("cartethyia")[0]["text"], "你好")
            self.assertEqual(len(history.messages("jingran")), 1)

    def test_bad_history_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text('{"pet": [null, {"speaker": 1}, {"speaker":"x", "text":"ok"}]}')
            self.assertEqual(len(ChatHistory(path).messages("pet")), 1)

    def test_speech_restores_after_agent_disabled(self):
        pet = DesktopPet.__new__(DesktopPet)
        enabled = True
        pet.allow_generated_speech = lambda: not enabled
        pet.idle_line_factory = Mock(return_value="hello")
        pet.say = Mock()
        pet.auto_jump_enabled = False
        pet.frames = {}
        pet._speak_generated_line()
        pet.idle_line_factory.assert_not_called()
        enabled = False
        pet._speak_generated_line()
        pet.say.assert_called_once_with("hello", 4600)

    def test_custom_count_remembers_and_preserves_other_settings(self):
        instance = app.App.__new__(app.App)
        instance.root = Mock()
        instance._start_named_task_real = Mock()
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, "APP_SETTINGS_CONFIG", Path(tmp) / "settings.json"):
            app.APP_SETTINGS_CONFIG.write_text('{"shutdown_after_task": true, "four_c_count": 47}')
            with patch.object(instance, "_ask_4c_count", return_value=53) as ask:
                instance._start_custom_4c()
            ask.assert_called_once_with(47)
            self.assertEqual(json.loads(app.APP_SETTINGS_CONFIG.read_text())["four_c_count"], 53)
            instance.auto_shutdown_enabled = Mock()
            instance.auto_shutdown_enabled.get.return_value = False
            instance._save_auto_shutdown_setting()
            self.assertEqual(json.loads(app.APP_SETTINGS_CONFIG.read_text())["four_c_count"], 53)
        instance._start_named_task_real.assert_called_once_with("4C刷取", 53)


class UpdateTests(unittest.TestCase):
    def test_stable_release_upgrades_same_version_beta(self):
        self.assertGreater(app.App._version_tuple("v1.5.1"), app.App._version_tuple("1.5.1 beta"))
        self.assertGreater(app.App._version_tuple("v1.5.1 beta 2"), app.App._version_tuple("1.5.1 beta"))
        self.assertGreater(app.App._version_tuple("v1.5.1 beta"), app.App._version_tuple("v1.5.0"))

    @unittest.skipUnless(os.name == "nt", "Windows PowerShell integration")
    def test_powershell_install_and_rollback_with_chinese_paths(self):
        # Temporary fixture files only; process commands never launch the app.
        for early_exit in (False, True):
            with self.subTest(early_exit=early_exit), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                target = root / "中文 安装目录'测试"
                staged = root / "新版本"
                for directory, content in ((target, "old"), (staged, "new")):
                    (directory / "_internal").mkdir(parents=True)
                    (directory / "wwbs.exe").write_text(content)
                    (directory / "_internal/python312.dll").write_text(content)
                (target / "pet-chat-history.json").write_text("keep")
                preamble = "function Get-Process { return $null }\nfunction Start-Sleep {}\n"
                preamble += "function Start-Process { [IO.File]::WriteAllText($env:WWBS_UPDATE_READY,$env:WWBS_UPDATE_TOKEN); return [pscustomobject]@{HasExited=$" + str(early_exit).lower() + "} }\n"
                script = root / "update.ps1"
                script.write_text(preamble + install_script(staged, target, root, 123, notify_failure=False), encoding="utf-8-sig")
                result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)], capture_output=True, timeout=20)
                self.assertEqual(result.returncode, 1 if early_exit else 0, result.stderr)
                self.assertEqual((target / "wwbs.exe").read_text(), "old" if early_exit else "new")
                self.assertEqual((target / "_internal/python312.dll").read_text(), "old" if early_exit else "new")
                self.assertEqual((target / "pet-chat-history.json").read_text(), "keep")
                self.assertTrue((root / "update.log").is_file())

    def make_package(self, path, prefix=""):
        with zipfile.ZipFile(path, "w") as package:
            for name in ("wwbs.exe", "_internal/python312.dll", "_internal/base_library.zip"):
                package.writestr(prefix + name, b"fixture")

    def test_flat_and_wrapped_releases(self):
        for prefix in ("", "WWBS/"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "update.zip"
                self.make_package(path, prefix)
                digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
                staged = prepare_update(path, root / "extract", path.stat().st_size, digest)
                self.assertTrue((staged / "_internal/python312.dll").exists())

    def test_incomplete_and_bad_hash_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "update.zip"
            self.make_package(path)
            with self.assertRaises(ValueError):
                prepare_update(path, root / "extract", 1)
            with self.assertRaises(ValueError):
                prepare_update(path, root / "extract", digest="sha256:" + "0" * 64)
            self.assertFalse((root / "extract").exists())

    def test_missing_runtime_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with zipfile.ZipFile(root / "update.zip", "w") as package:
                package.writestr("wwbs.exe", b"fixture")
            with self.assertRaises(ValueError):
                prepare_update(root / "update.zip", root / "extract")

    def test_zip_traversal_rejected(self):
        for name in ("../outside", "C:/outside", "/outside", "_internal/../../outside", "bad:stream"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with zipfile.ZipFile(root / "update.zip", "w") as package:
                    package.writestr(name, "bad")
                with self.assertRaises(ValueError):
                    prepare_update(root / "update.zip", root / "extract")
                self.assertFalse((root / "extract").exists())

    def test_script_preserves_user_files_and_backups(self):
        script = install_script(Path("暂存"), Path("用户目录'带空格"), Path("临时"), 123)
        self.assertIn("用户目录''带空格", script)
        self.assertIn("@('wwbs.exe', '_internal')", script)
        self.assertIn("Original files restored", script)
        self.assertNotIn("Remove-Item", script)
        self.assertIn("-WindowStyle Hidden", script)


if __name__ == "__main__":
    unittest.main()
