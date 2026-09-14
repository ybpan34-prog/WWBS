import inspect
import unittest
from unittest.mock import Mock

from desktop_pet import DesktopPet
import jingran_persona


class DesktopPetLookTests(unittest.TestCase):
    def test_hidden_pet_feedback_changes_state_without_showing_window(self) -> None:
        pet = DesktopPet.__new__(DesktopPet)
        pet.frames = {"idle": [object()], "running": [object()]}
        pet.visible = False
        pet.state = "idle"
        pet.frame_index = 0
        pet.state_cycles = 0
        pet.show = Mock()

        pet.play("running")
        pet.say("任务开始")

        self.assertEqual(pet.state, "running")
        pet.show.assert_not_called()

    def test_look_frames_are_loaded_before_animation_starts(self) -> None:
        source = inspect.getsource(DesktopPet.__init__)
        self.assertLess(source.index("self.look_frames ="), source.index("self._animate()"))

    def test_sixteen_direction_mapping_starts_up_and_runs_clockwise(self) -> None:
        self.assertEqual(DesktopPet._look_direction_index(0, -100), 0)
        self.assertEqual(DesktopPet._look_direction_index(100, 0), 4)
        self.assertEqual(DesktopPet._look_direction_index(0, 100), 8)
        self.assertEqual(DesktopPet._look_direction_index(-100, 0), 12)

    def test_pointer_deadzone_uses_normal_idle_animation(self) -> None:
        self.assertIsNone(DesktopPet._look_direction_index(3, 4, deadzone=5))

    def test_jingran_chatter_selects_a_one_shot_action(self) -> None:
        jingran_persona._idle_action_bag.clear()
        dialogue = jingran_persona.idle_line()
        self.assertTrue(
            dialogue.text in jingran_persona.IDLE_LINES
            or dialogue.text.removeprefix("漂泊者，") in jingran_persona.IDLE_LINES
        )
        self.assertIn(dialogue.action, DesktopPet.CHATTER_ACTIONS)

    def test_jingran_jump_appears_in_every_random_action_round(self) -> None:
        jingran_persona._idle_action_bag.clear()
        actions = {jingran_persona.idle_line().action for _ in jingran_persona.IDLE_ACTIONS}
        self.assertEqual(actions, set(jingran_persona.IDLE_ACTIONS))


if __name__ == "__main__":
    unittest.main()
