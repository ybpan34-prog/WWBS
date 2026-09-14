from __future__ import annotations

import unittest

import jingran_persona as persona


class JingranPersonaTests(unittest.TestCase):
    def test_signature_line_is_preserved(self) -> None:
        self.assertIn(
            "行于阴阳未判之处，踏遍祸福未卜之途，借阴路而行，自也向死地而生。",
            persona.IDLE_LINES,
        )

    def test_required_events_render(self) -> None:
        required = {
            "task_start",
            "task_complete",
            "check_start",
            "check_success",
            "check_failure",
            "diagnose_start",
            "diagnose_error",
            "diagnose_warning",
            "diagnose_ok",
            "stop_requested",
            "mouse_move_failed",
        }
        self.assertTrue(required.issubset(persona.EVENT_LINES))
        for event in required:
            values = {"detail": "测试原因"} if event in {"diagnose_error", "diagnose_warning"} else {}
            self.assertTrue(persona.event_line(event, **values).strip())


if __name__ == "__main__":
    unittest.main()
