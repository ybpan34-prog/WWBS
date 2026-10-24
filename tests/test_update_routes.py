from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from test_update_transfer import DATA, Server, asset
from update_routes import DownloadRoutes, relay_url
from update_transfer import download_ranges


class RouteTests(unittest.TestCase):
    def test_fastest_successful_route_is_selected_and_switch_is_shared(self):
        status = Mock()
        routes = DownloadRoutes(['direct', 'relay'], {}, 100, None, lambda: False, status)
        routes._probe = lambda url: (url, 2 if url == 'direct' else .1)
        self.assertEqual(routes.select(), 'relay')
        self.assertEqual(routes.switch('relay'), 'direct')
        self.assertEqual(routes.switch('relay'), 'direct')  # A late failed worker cannot switch it back.

    def test_relay_is_only_generated_for_the_project_installer(self):
        current = asset()
        self.assertIn('wwbs-seed-library.netlify.app', relay_url(current, '1.5.6'))
        self.assertIsNone(relay_url(dict(current, browser_download_url='https://github.com/other/project/releases/download/v1/wwbs.zip'), '1.5.6'))

    def test_bad_redirect_during_probe_is_never_accepted(self):
        routes = DownloadRoutes(['https://github.com/test'], {}, len(DATA),
                                Server(redirect='https://untrusted.example/file'), lambda: False, Mock())
        with self.assertRaises(OSError):
            routes.select()

    def test_large_parts_use_bounded_chunks_and_keep_full_checksum(self):
        data = DATA*3
        server = Server(data)
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'out.zip'
            self.assertTrue(download_ranges(asset(data), target, version='1.5.6', progress=Mock(),
                cancelled=lambda: False, opener=server, cache_dir=Path(directory)/'cache', status=Mock()))
            self.assertEqual(target.read_bytes(), data)
        for value in server.requests:
            start, end = map(int, value.removeprefix('bytes=').split('-'))
            self.assertLessEqual(end-start+1, 4*1024*1024)

    def test_failed_connection_switches_route_and_resumes_written_bytes(self):
        server = Server()
        direct = 'https://release-assets.githubusercontent.com/direct'
        relay = 'https://wwbs-seed-library.netlify.app/relay'
        routes = Mock(current=direct)
        routes.select.return_value = direct
        def switch(_failed):
            routes.current = relay
            return relay
        routes.switch.side_effect = switch
        requests = []
        def opener(request, timeout):
            requests.append((request.full_url, request.get_header('Range')))
            response = server(request, timeout)
            if request.full_url == direct:
                original = response.read1
                reads = [0]
                def interrupted(size):
                    reads[0] += 1
                    if reads[0] > 1:
                        raise OSError('connection stalled')
                    return original(size)
                response.read1 = interrupted
            return response
        with tempfile.TemporaryDirectory() as directory, patch('update_transfer.DownloadRoutes', return_value=routes):
            target = Path(directory)/'out.zip'
            self.assertTrue(download_ranges(dict(asset(), _wwbs_relay=relay), target, version='1.5.6',
                progress=Mock(), cancelled=lambda: False, opener=opener,
                cache_dir=Path(directory)/'cache', status=Mock(), sleep=Mock()))
            self.assertEqual(target.read_bytes(), DATA)
        boundaries = {len(DATA)*i//4 for i in range(4)}
        self.assertTrue(any(url == relay and int(value.split('=')[1].split('-')[0]) not in boundaries
                            for url, value in requests))
