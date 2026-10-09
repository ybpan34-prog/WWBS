import base64
from copy import deepcopy
import hashlib
import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch
import zlib

import app
from combat_rotation import ACTION_SPECS, default_store, load_store, new_module, validate_store
from combat_seed import MAX_PAYLOAD_BYTES, SHORT_DICT, decode_seed, export_seed, import_seed
from ui_controls import RoundedButton


def wrap_payload(payload):
    raw = json.dumps(payload, ensure_ascii=False).encode()
    compressed = zlib.compress(raw)
    return "WWBS1." + base64.urlsafe_b64encode(compressed).decode().rstrip("=") + "." + hashlib.sha256(compressed).hexdigest()[:16]


def payload_from_seed(seed):
    if seed.startswith(("WWBS2.", "WWBS3.")):
        preset = decode_seed(seed)
        return {"v": 1, "uid": preset["share_id"], "n": preset["name"],
                "o": preset["slot_order"], "t": [preset["slot_times"][str(n)] for n in (1, 2, 3)],
                "m": [[m["kind"], m["slot"], m["value"], m["interval"]] for m in preset["modules"]]}
    content = seed.split(".")[1]
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(content + "=" * (-len(content) % 4))))


def content(preset):
    return {k: v for k, v in preset.items() if k in ("name", "slot_times", "slot_order")} | {
        "modules": [{k: v for k, v in m.items() if k != "id"} for m in preset["modules"]]}


class CombatSeedTests(unittest.TestCase):
    def setUp(self):
        self.store = default_store()
        self.preset = self.store["presets"][0]
        self.preset["slot_order"] = [3, 1, 2]
        self.preset["slot_times"]["1"] = 31.5
        self.seed = export_seed(self.preset)

    def test_roundtrip_all_actions_parameters_order_and_unicode_name(self):
        self.preset["name"] = "今汐／漂泊者 · 自定义轴"
        self.preset["modules"] = [new_module(kind, 1) for kind in ACTION_SPECS]
        decoded = decode_seed(export_seed(self.preset))
        self.assertEqual(content(decoded), content(self.preset))
        self.assertNotEqual(decoded["id"], self.preset["id"])
        self.assertTrue(all(a["id"] != b["id"] for a, b in zip(decoded["modules"], self.preset["modules"])))

    def test_exports_have_distinct_identifiers_but_represent_same_axis(self):
        codes = [export_seed(self.preset) for _ in range(10)]
        self.assertEqual(len(set(codes)), 10)
        decoded = [decode_seed(code) for code in codes]
        self.assertEqual(len({p["share_id"] for p in decoded}), 10)
        self.assertTrue(all(content(p) == content(self.preset) for p in decoded))

    def test_line_wrapping_and_whitespace_survive_chat_copy(self):
        wrapped = "\n".join(self.seed[i:i+70] for i in range(0, len(self.seed), 70))
        self.assertEqual(content(decode_seed(" \n" + wrapped + "\t ")), content(self.preset))

    def test_corruption_truncation_and_unknown_version_are_rejected(self):
        for seed in (self.seed[:-3], self.seed[:-1]+("1" if self.seed[-1] != "1" else "0"),
                     self.seed.replace("WWBS3", "WWBS9"), "", "not a code", "WWBS1.a.0123456789abcdef"):
            with self.subTest(seed=seed[:40]), self.assertRaises(ValueError):
                decode_seed(seed)

    def test_payload_limits_unknown_actions_and_invalid_parameters_are_rejected(self):
        payload = payload_from_seed(self.seed)
        variants = []
        for key, value in (("v", 2), ("o", [1, 1, 3]), ("t", [1, 2]), ("t", [True, 2, 3]),
                           ("t", [0, 2, 3]), ("uid", "bad"), ("m", [])):
            changed = deepcopy(payload)
            changed[key] = value
            variants.append(changed)
        for row in (("shell_command", 1, 1, 0), ("wait", 1, 999, 0),
                    ("wait", 1, float("nan"), 0), ("skill", 1, 1, 0), ("wait", True, 1, 0)):
            changed = deepcopy(payload)
            changed["m"] = [list(row)]
            variants.append(changed)
        bomb = deepcopy(payload)
        bomb["n"] = "x" * (MAX_PAYLOAD_BYTES + 1)
        variants.append(bomb)
        for changed in variants:
            with self.subTest(changed=str(changed)[:70]), self.assertRaises(ValueError):
                decode_seed(wrap_payload(changed))

    def test_export_whitelists_axis_and_excludes_local_configuration(self):
        self.preset.update(api_key="PRIVATE_VALUE", filename="PRIVATE_PATH", modes={"daily": "secret"})
        self.preset["modules"][0]["private"] = "PRIVATE_VALUE"
        payload = payload_from_seed(export_seed(self.preset))
        self.assertEqual(set(payload), {"v", "uid", "n", "o", "t", "m"})
        self.assertNotIn("PRIVATE", json.dumps(payload))

    def test_repeated_import_never_overwrites_and_assigns_only_selected_modes(self):
        before = deepcopy(self.store)
        store, first = import_seed(self.store, self.seed)
        store, second = import_seed(store, self.seed, modes=("daily",))
        self.assertEqual(self.store, before)
        self.assertEqual(store["presets"][0], validate_store(before)["presets"][0])
        self.assertNotEqual(first, second)
        self.assertEqual(len({p["name"] for p in store["presets"]}), 3)
        self.assertEqual(store["presets"][1]["name"], self.preset["name"] + "（导入）")
        self.assertEqual(store["presets"][2]["name"], self.preset["name"] + "（导入）（2）")
        self.assertEqual(store["modes"], {"daily": second, "combat_4c": "default", "tower": "default"})
        self.assertEqual(store["active"], second)
        ids = [m["id"] for p in store["presets"] for m in p["modules"]]
        self.assertEqual(len(ids), len(set(ids)))

    def test_max_modules_and_name_length_roundtrip_and_full_store_is_unchanged(self):
        self.preset["modules"] = [new_module("wait", n % 3 + 1) for n in range(100)]
        self.preset["name"] = "轴" * 40
        seed = export_seed(self.preset)
        store, _ = import_seed(self.store, seed, modes=("daily", "combat_4c"))
        self.assertEqual(store["presets"][-1]["name"], self.preset["name"] + "（导入）")
        self.assertEqual(len(store["presets"][-1]["modules"]), 100)
        while len(store["presets"]) < 30:
            store, _ = import_seed(store, seed)
        before = deepcopy(store)
        with self.assertRaisesRegex(ValueError, "数量已满"):
            import_seed(store, seed)
        self.assertEqual(store, before)

    def test_reexport_does_not_accumulate_import_tags(self):
        first, _ = import_seed(self.store, self.seed)
        shared_again = export_seed(first["presets"][-1])
        second, _ = import_seed(default_store(), shared_again)
        self.assertEqual(second["presets"][-1]["name"], self.preset["name"] + "（导入）")

    def test_short_default_seed_and_legacy_compatibility(self):
        legacy = wrap_payload(payload_from_seed(self.seed))
        self.assertLess(len(self.seed), len(legacy)*.6)
        self.assertEqual(content(decode_seed(legacy)), content(self.preset))
        store, _ = import_seed(self.store, legacy)
        self.assertEqual(store['presets'][-1]['name'], self.preset['name']+'（导入）')

    def test_compact_default_and_second_generation_seed_compatibility(self):
        original = default_store()['presets'][0]
        seed = export_seed(original)
        self.assertLessEqual(len(seed), 45)
        self.assertEqual(content(decode_seed(seed)), content(original))
        body = b'\x00' + b'\x01'*16 + SHORT_DICT
        old = 'WWBS2.' + base64.urlsafe_b64encode(body+hashlib.sha256(body).digest()[:8]).decode().rstrip('=')
        self.assertEqual(content(decode_seed(old)), content(original))

    def test_short_format_preserves_arbitrary_decimal_values(self):
        self.preset['slot_times'] = {'1': 12.345678901, '2': .23456789, '3': 9.87654321}
        for item in self.preset['modules']:
            if item['kind'] in ('skill', 'ultimate', 'echo'):
                item['interval'] = 5.123456789
            if item['kind'] == 'wait':
                item['value'] = .3456789123
        decoded = decode_seed(export_seed(self.preset))
        self.assertEqual(content(decoded), content(self.preset))

    def test_short_format_rejects_invalid_binary_and_decompression_bomb(self):
        def packed(body):
            return 'WWBS2.' + base64.urlsafe_b64encode(body+hashlib.sha256(body).digest()[:8]).decode().rstrip('=')
        raw = (b'\x00'*16 + b'\x00\x01a' + b'\x00\x05'*3 + b'\x01\x0f')
        for body in (b'\x00'+raw, b'\x00'+raw[:19], b'\x02'+raw,
                     b'\x01'+zlib.compress(b'x'*(MAX_PAYLOAD_BYTES+1))):
            with self.assertRaises(ValueError):
                decode_seed(packed(body))


def walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from walk(child)


class CombatSeedUiTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.geometry("1050x900+20+20")
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "combat.json"
        self.config_patch = patch.object(app, "COMBAT_PRESETS_CONFIG", self.path)
        self.config_patch.start()
        self.ui = app.App.__new__(app.App)
        self.ui.root = self.root
        self.ui.rotation_store = default_store()
        self.ui.rotation_choice = tk.StringVar()
        self.ui.rotation_tab = tk.Frame(self.root)
        self.ui.rotation_tab.pack(fill=tk.BOTH, expand=True)
        self.ui._build_rotation_tab()
        self.root.update()

    def tearDown(self):
        self.root.destroy()
        self.config_patch.stop()
        self.tmp.cleanup()

    def button(self, dialog, title):
        return next(w for w in walk(dialog) if isinstance(w, RoundedButton) and w.cget("text") == title)

    def textbox(self, dialog):
        return next(w for w in walk(dialog) if isinstance(w, tk.Text))

    def test_export_commits_pending_times_and_copies_the_displayed_snapshot(self):
        self.ui._rotation_time_fields[1].set("42")
        dialog = self.ui._rotation_export_seed()
        self.root.update()
        seed = self.textbox(dialog).get("1.0", "end-1c")
        self.assertEqual(decode_seed(seed)["slot_times"]["1"], 42)
        with patch.object(self.root, "clipboard_clear"), patch.object(self.root, "clipboard_append") as append:
            self.button(dialog, "复制种子").invoke()
            self.button(dialog, "复制种子").invoke()
        self.assertEqual([call.args[0] for call in append.call_args_list], [seed, seed])

    def test_import_after_preview_uses_current_seed_without_another_preview(self):
        seed = export_seed(self.ui._rotation_current_preset())
        dialog = self.ui._rotation_import_seed()
        text = self.textbox(dialog)
        self.assertEqual(self.button(dialog, "导入预设").cget("state"), "disabled")
        text.insert("1.0", seed)
        self.root.update()
        self.button(dialog, "预览种子").invoke()
        self.assertEqual(self.button(dialog, "导入预设").cget("state"), "normal")
        text.insert("end", "bad")
        self.root.update()
        self.assertEqual(self.button(dialog, "导入预设").cget("state"), "normal")
        self.button(dialog, "导入预设").invoke()
        self.assertEqual(len(self.ui.rotation_store["presets"]), 1)
        other = deepcopy(self.ui._rotation_current_preset())
        other['name'] = '新的轴'
        other['slot_order'] = [3, 1, 2]
        other['slot_times']['1'] = 12.5
        text.delete("1.0", "end")
        text.insert("1.0", export_seed(other))
        self.root.update()
        picker = next(w for w in walk(dialog) if getattr(w, "_is_rounded_picker", False))
        picker.event_generate("<MouseWheel>", delta=-120)  # 4C
        self.root.update()
        self.button(dialog, "导入预设").invoke()
        self.root.update()
        saved = load_store(self.path)
        self.assertEqual(len(saved["presets"]), 2)
        self.assertEqual(saved["modes"], {"daily": "default", "combat_4c": saved["active"], "tower": "default"})
        self.assertEqual(self.ui.rotation_choice.get(), saved["presets"][-1]["name"])
        self.assertEqual(saved['presets'][-1]['name'], '新的轴（导入）')
        self.assertEqual(saved['presets'][-1]['slot_order'], [3, 1, 2])
        self.assertEqual(saved['presets'][-1]['slot_times']['1'], 12.5)
        self.assertFalse(dialog.winfo_exists())

    def test_direct_import_and_centered_dialogs(self):
        export = self.ui._rotation_export_seed()
        self.root.update()
        for dialog in (export, self.ui._rotation_import_seed()):
            self.root.update()
            self.assertLess(abs((dialog.winfo_rootx()+dialog.winfo_width()/2) -
                                (self.root.winfo_rootx()+self.root.winfo_width()/2)), 40)
            self.assertLess(abs((dialog.winfo_rooty()+dialog.winfo_height()/2) -
                                (self.root.winfo_rooty()+self.root.winfo_height()/2)), 40)
        text = self.textbox(dialog)
        text.insert('1.0', export_seed(self.ui._rotation_current_preset()))
        self.root.update()
        self.button(dialog, '导入预设').invoke()
        self.assertEqual(len(load_store(self.path)['presets']), 2)


if __name__ == "__main__":
    unittest.main()
