import ast
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from tasks.daily_154 import Daily154Navigation
from tasks.runner import TaskRunner


def source_digest(node):
    # ast.dump changed its empty-field defaults in Python 3.13.
    def stable(value):
        if isinstance(value, ast.AST):
            return {'node': type(value).__name__, **{key: stable(item) for key, item in ast.iter_fields(value)}}
        if isinstance(value, list):
            return [stable(item) for item in value]
        return value
    return hashlib.sha256(json.dumps(stable(node), sort_keys=True).encode()).hexdigest()


class Daily154Tests(unittest.TestCase):
    def test_restored_methods_match_the_published_154_source(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/daily154-method-hashes.json').read_text(encoding='utf-8'))
        module = ast.parse((Path(__file__).parents[1]/'tasks/daily_154.py').read_text(encoding='utf-8'))
        cls = next(n for n in module.body if isinstance(n, ast.ClassDef))
        methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
        for name, expected in fixture['methods'].items():
            if name in fixture.get('exceptions', [fixture['exception']]):
                continue
            node = methods[name]
            for child in ast.walk(node):
                if isinstance(child, ast.ImportFrom) and child.module == 'tasks.weekly_clicks':
                    child.module = 'weekly_clicks'  # Module layout changed after 1.5.4.
            self.assertEqual(source_digest(node), expected, name)

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
