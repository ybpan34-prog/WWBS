import unittest
from unittest.mock import Mock

import app


def task(name: str, group: str, enabled: bool, action: str) -> app.WeeklyTask:
    return app.WeeklyTask(
        name=name,
        enabled=enabled,
        template_group=group,
        steps=[app.Step(action=action)],
    )


class TemplateTaskSwitchingTests(unittest.TestCase):
    def test_built_in_tasks_choose_templates_even_with_stale_saved_groups(self):
        cases = (
            ('幻梦游园', 'tap_image_cycle', 'default'),
            ('群声共振模拟域', 'move_to_visual_target', '群声共振模拟域'),
            ('4C刷取', 'combat_4c', '4c'),
            ('一键日常', 'daily_routine', 'daily'),
            ('凝素领域挑战', 'forgery_challenge', 'daily'),
            ('深塔挑战', 'tower_challenge', 'tower'),
            ('剧情跳过对话', 'story_skip', 'default'),
        )
        for name, action, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(app.App._task_template_group(task(name, 'stale', True, action)), expected)

    def test_legacy_custom_task_retains_its_own_template_group(self):
        custom = task('自定义', 'my_templates', True, 'tap_image')
        self.assertEqual(app.App._task_template_group(custom), 'my_templates')

    def test_packaged_default_template_is_dream_park(self):
        tasks = app.ConfigStore(app.DEFAULT_CONFIG).load()
        enabled = [item for item in tasks if item.enabled]
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].name, "幻梦游园")
        self.assertEqual(enabled[0].template_group, "default")

    def test_4c_launcher_forces_packaged_group_without_changing_selection(self):
        launcher = app.App.__new__(app.App)
        misconfigured = task("4C刷取", "default", False, "combat_4c")
        launcher.tasks = [misconfigured]
        launcher.target_mode = Mock()
        launcher.target_mode.get.return_value = "client"
        launcher.max_cycles = None
        launcher.dry_run = Mock()
        launcher._start_worker = Mock()

        launcher._start_named_task_real("4C刷取", 5, require_confirmation=False)

        launched = launcher._start_worker.call_args.args[0][0]
        self.assertEqual(launched.template_group, "4c")
        self.assertTrue(launched.enabled)
        self.assertEqual(misconfigured.template_group, "default")
        self.assertEqual(launcher.max_cycles, 5)


if __name__ == "__main__":
    unittest.main()
