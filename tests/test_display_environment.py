import ctypes as c
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from display_environment import (ColorInfo, ColorInfo2, DisplayPath, DisplayState,
                                 FILTER_GUIDANCE, Header, Mode, U32, WindowsDisplayReader,
                                 display_findings, interpret_color, read_game_display)


class DisplayEnvironmentTests(unittest.TestCase):
    def test_win32_layouts_use_fixed_width_fields(self):
        for structure, size in ((Header, 20), (ColorInfo, 32), (ColorInfo2, 36),
                                (DisplayPath, 72), (Mode, 64)):
            self.assertEqual(c.sizeof(structure), size)

    def test_only_active_hdr_is_reported_as_hdr(self):
        # HDR support/user preference alone is not evidence that HDR is active.
        for mode, expected in ((0, 'sdr'), (1, 'wcg'), (2, 'hdr'), (99, 'unknown')):
            state = interpret_color('game', ColorInfo2(flags=0xff, active_mode=mode), modern=True)
            self.assertEqual(state.mode, expected)

    def test_legacy_advanced_color_is_not_definite_hdr(self):
        state = interpret_color('game', ColorInfo(flags=3), modern=False)
        self.assertEqual(state.mode, 'advanced')
        self.assertFalse(any(level == 'error' for level, _ in display_findings([state])))
        self.assertEqual(interpret_color('game', ColorInfo(flags=1), modern=False).mode, 'sdr')

    def test_secondary_display_hdr_does_not_report_game_hdr(self):
        reader = Mock()
        reader.game_device.return_value = 'game'
        reader.paths.return_value = ['secondary', 'game']
        reader.source_name.side_effect = lambda path: path
        reader.color.side_effect = lambda path, device: DisplayState(device, 'hdr' if path == 'secondary' else 'sdr')
        states = read_game_display(123, reader=reader)
        self.assertEqual(states, (DisplayState('game', 'sdr'),))
        reader.color.assert_called_once_with('game', 'game')
        self.assertFalse(any(level == 'error' for level, _ in display_findings(states)))

    def test_cloned_game_target_hdr_is_reported_with_remedy(self):
        reader = Mock()
        reader.game_device.return_value = 'GAME'
        reader.paths.return_value = [1, 2]
        reader.source_name.return_value = 'game'
        reader.color.side_effect = [DisplayState('GAME', 'sdr'), DisplayState('GAME', 'hdr')]
        findings = display_findings(read_game_display(123, reader=reader))
        self.assertTrue(any(level == 'warning' and '已确认' in message and '关闭' in message
                            for level, message in findings))

    def test_api_failure_is_unknown_not_sdr_and_filters_require_manual_check(self):
        reader = Mock()
        reader.game_device.side_effect = OSError('unsupported')
        findings = display_findings(read_game_display(123, reader=reader))
        self.assertTrue(any('无法确认' in message for _, message in findings))
        self.assertFalse(any(level == 'ok' for level, _ in findings))
        self.assertIn(('info', FILTER_GUIDANCE), findings)
        self.assertIn(('info', FILTER_GUIDANCE), display_findings(()))
        for state in ((), (DisplayState('game', 'sdr'),), (DisplayState('game', 'advanced'),)):
            self.assertFalse(any(level in {'warning', 'error'} for level, _ in display_findings(state)))

    def test_modern_query_falls_back_to_legacy_read_only(self):
        reader = WindowsDisplayReader.__new__(WindowsDisplayReader)
        reader.get_info = Mock(side_effect=[87, 0])
        path = DisplayPath()
        self.assertEqual(reader.color(path, 'game').mode, 'sdr')
        self.assertEqual([call.args[1] for call in reader.get_info.call_args_list], [15, 9])

    def test_display_topology_change_retries_query_with_new_buffer(self):
        reader = WindowsDisplayReader.__new__(WindowsDisplayReader)
        def buffer_sizes(_flags, paths, modes):
            c.cast(paths, c.POINTER(U32))[0] = 1
            c.cast(modes, c.POINTER(U32))[0] = 1
            return 0
        reader.api = SimpleNamespace(GetDisplayConfigBufferSizes=Mock(side_effect=buffer_sizes),
                                     QueryDisplayConfig=Mock(side_effect=[122, 0]))
        self.assertEqual(len(reader.paths()), 1)
        self.assertEqual(reader.api.QueryDisplayConfig.call_count, 2)

    def test_no_stable_topology_is_bounded(self):
        reader = WindowsDisplayReader.__new__(WindowsDisplayReader)
        reader.api = SimpleNamespace(GetDisplayConfigBufferSizes=Mock(return_value=122))
        with self.assertRaises(OSError):
            reader.paths()
        self.assertEqual(reader.api.GetDisplayConfigBufferSizes.call_count, 3)


if __name__ == '__main__':
    unittest.main()
