from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app as app_module
from app import App


class ThemePetBindingTests(unittest.TestCase):
    @staticmethod
    def _app(theme_id: str, pet_id: str) -> App:
        instance = App.__new__(App)
        instance.root = object()
        instance.theme_id = theme_id
        instance.pet_id = pet_id
        instance._theme_pack_valid = Mock(return_value=True)
        instance._restart_app = Mock()
        return instance

    def test_character_theme_writes_matching_pet(self) -> None:
        instance = self._app("daniya", "daniya")
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            pet_config = Path(directory) / "pet.json"
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(app_module, "PET_CONFIG", pet_config),
                patch.object(app_module.messagebox, "askyesno", return_value=False),
            ):
                instance._select_theme("aemeath")
            self.assertEqual(json.loads(theme_config.read_text(encoding="utf-8"))["theme"], "aemeath")
            self.assertTrue(json.loads(theme_config.read_text(encoding="utf-8"))["explicit"])
            self.assertEqual(json.loads(pet_config.read_text(encoding="utf-8"))["pet"], "aemeath")

    def test_pet_selection_keeps_current_theme(self) -> None:
        instance = self._app("simple", "daniya")
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            pet_config = Path(directory) / "pet.json"
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(app_module, "PET_CONFIG", pet_config),
                patch.object(app_module.messagebox, "askyesno", return_value=False),
            ):
                instance._select_pet("aemeath")
            self.assertFalse(theme_config.exists())
            self.assertEqual(json.loads(pet_config.read_text(encoding="utf-8"))["pet"], "aemeath")

    def test_jingran_theme_and_pet_are_bound(self) -> None:
        instance = self._app("simple", "daniya")
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            pet_config = Path(directory) / "pet.json"
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(app_module, "PET_CONFIG", pet_config),
                patch.object(app_module.messagebox, "askyesno", return_value=False),
            ):
                instance._select_theme("jingran")
            self.assertEqual(json.loads(theme_config.read_text(encoding="utf-8"))["theme"], "jingran")
            self.assertEqual(json.loads(pet_config.read_text(encoding="utf-8"))["pet"], "jingran")

    def test_simple_theme_keeps_current_pet(self) -> None:
        instance = self._app("aemeath", "aemeath")
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            pet_config = Path(directory) / "pet.json"
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(app_module, "PET_CONFIG", pet_config),
                patch.object(app_module.messagebox, "askyesno", return_value=False),
            ):
                instance._select_theme("simple")
            self.assertEqual(json.loads(theme_config.read_text(encoding="utf-8"))["theme"], "simple")
            self.assertTrue(json.loads(theme_config.read_text(encoding="utf-8"))["explicit"])
            self.assertFalse(pet_config.exists())

    def test_legacy_character_theme_does_not_replace_simple_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            theme_config.write_text(json.dumps({"theme": "daniya"}), encoding="utf-8")
            with patch.object(app_module, "THEME_CONFIG", theme_config):
                self.assertEqual(App._load_theme_preference(), "simple")

    def test_old_explicit_character_binding_does_not_replace_simple_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            theme_config.write_text(
                json.dumps({"theme": "jingran", "explicit": True}),
                encoding="utf-8",
            )
            with patch.object(app_module, "THEME_CONFIG", theme_config):
                self.assertEqual(App._load_theme_preference(), "simple")

    def test_theme_picker_choice_is_restored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            theme_config = Path(directory) / "theme.json"
            theme_config.write_text(
                json.dumps(
                    {"theme": "jingran", "explicit": True, "source": "theme-picker"}
                ),
                encoding="utf-8",
            )
            with (
                patch.object(app_module, "THEME_CONFIG", theme_config),
                patch.object(App, "_theme_pack_valid", return_value=True),
            ):
                self.assertEqual(App._load_theme_preference(), "jingran")


if __name__ == "__main__":
    unittest.main()
