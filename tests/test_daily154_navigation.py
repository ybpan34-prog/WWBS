import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from tasks.daily_154 import Daily154Navigation
from tasks.runner import TaskRunner


class Daily154Tests(unittest.TestCase):
    def test_restored_methods_match_the_published_154_source(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/daily154-method-hashes.json').read_text(encoding='utf-8'))
        module = ast.parse((Path(__file__).parents[1]/'tasks/daily_154.py').read_text(encoding='utf-8'))
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef))
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        for name, expected in fixture['methods'].items():
            if name == fixture['exception']:
                continue
            node = methods[name]
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module == 'tasks.weekly_clicks':
                    child.module = 'weekly_clicks'  # Module layout changed after 1.5.4.
            self.assertEqual(hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest(), expected, name)

    def test_combat_and_collection_stay_on_the_current_runner(self):
        runner = TaskRunner(Mock(), Mock())
        runner._run_daily_battle = Mock()
        runner._collect_daily_reward = Mock(return_value=True)
        nav = Daily154Navigation(runner)
        nav._run_daily_battle('step', 'E', 'R', 1)
        self.assertFalse(runner._daily_restart_pending)
        nav._run_daily_battle('step', 'E', 'R', 2)
        self.assertTrue(runner._daily_restart_pending)
        runner._run_daily_battle.assert_called_with('step', 'E', 'R', 2)
        self.assertTrue(nav._collect_daily_reward(2))
        runner._collect_daily_reward.assert_called_once_with(2)

    def test_reported_activity_screen_is_the_only_retained_navigation_guard(self):
        self.assertFalse(Daily154Navigation._guide_tacet_section_selected(
            Path(__file__).parent/'fixtures/daily-guide-activity-wrong-category.png', round(899*.73)))
