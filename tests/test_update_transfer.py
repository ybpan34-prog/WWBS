import hashlib
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from update_manager import download_asset
from update_transfer import download_ranges


DATA = b'PK\x03\x04'+bytes(range(256))*(32768)+b'end'


class Server:
    def __init__(self, data=DATA, *, ranges=True, corrupt=False, redirect=None):
        self.data, self.ranges, self.corrupt, self.redirect = data, ranges, corrupt, redirect
        self.requests = []
        self.lock = threading.Lock()
        self.active = self.maximum = 0

    def __call__(self, request, timeout):
        value = request.get_header('Range') if self.ranges else None
        start, end = (map(int, value.removeprefix('bytes=').split('-')) if value else (0, len(self.data)-1))
        body = self.data[start:end+1]
        if self.corrupt and start > 0:
            body = bytes([body[0]^1])+body[1:]
        server = self
        class Response(io.BytesIO):
            status = 206 if value else 200
            headers = {'Content-Range':f'bytes {start}-{end}/{len(server.data)}'}
            def geturl(self):
                return server.redirect or 'https://release-assets.githubusercontent.com/immutable-test'
            def __enter__(self):
                with server.lock:
                    server.active += 1
                    server.maximum = max(server.maximum, server.active)
                return self
            def __exit__(self, *_args):
                with server.lock:
                    server.active -= 1
                self.close()
            def read1(self, size):
                time.sleep(.001)
                return self.read(size)
        with self.lock:
            self.requests.append(value)
        return Response(body)


def asset(data=DATA):
    return {'id':123, 'name':'wwbs-exe.zip', 'size':len(data),
            'digest':'sha256:'+hashlib.sha256(data).hexdigest(),
            'browser_download_url':'https://github.com/ybpan34-prog/WWBS/releases/download/v1.5.5/wwbs-exe.zip'}


class TransferTests(unittest.TestCase):
    def transfer(self, directory, server, *, destination='update.zip', cancelled=lambda:False, progress=lambda *_:None):
        target = Path(directory)/destination
        returned = download_ranges(asset(server.data), target, version='1.5.5', progress=progress,
            cancelled=cancelled, opener=server, cache_dir=Path(directory)/'cache', status=Mock(), sleep=Mock())
        return returned, target

    def test_four_concurrent_ranges_assemble_verified_bytes_and_reuse_complete_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Server()
            result, target = self.transfer(directory, server)
            self.assertTrue(result)
            self.assertEqual(target.read_bytes(), DATA)
            self.assertGreaterEqual(server.maximum, 2)
            self.assertEqual(len(server.requests), 5)  # One capability request, four disjoint chunks.
            server.requests.clear()
            _, second = self.transfer(directory, server, destination='retry.zip')
            self.assertEqual(second.read_bytes(), DATA)
            self.assertEqual(server.requests, [])

    def test_cancel_preserves_parts_and_new_destination_resumes_them(self):
        with tempfile.TemporaryDirectory() as directory:
            stop = threading.Event()
            server = Server()
            def progress(received, _total):
                if received >= 1024*1024:
                    stop.set()
            with self.assertRaises(InterruptedError):
                self.transfer(directory, server, cancelled=stop.is_set, progress=progress)
            parts = list((Path(directory)/'cache').glob('*/part-*'))
            self.assertTrue(parts)
            self.assertGreater(sum(p.stat().st_size for p in parts), 0)
            old_lengths = {int(p.name[-1]):p.stat().st_size for p in parts}
            server.requests.clear()
            _, target = self.transfer(directory, server, destination='next-attempt.zip')
            self.assertEqual(target.read_bytes(), DATA)
            starts = [int(value.split('=')[1].split('-')[0]) for value in server.requests[1:]]
            self.assertTrue(any(len(DATA)*index//4+length in starts for index, length in old_lengths.items() if length))

    def test_server_ignoring_ranges_falls_back_to_verified_single_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Server(ranges=False)
            target = Path(directory)/'update.zip'
            download_asset(asset(), target, version='1.5.5', opener=server, sleep=Mock())
            self.assertEqual(target.read_bytes(), DATA)
            self.assertEqual(server.requests, [None, None])

    def test_wrong_range_cannot_mix_unrelated_bytes_and_falls_back(self):
        server = Server()
        def invalid(request, timeout):
            response = server(request, timeout)
            if request.get_header('Range'):
                response.headers = {'Content-Range':'bytes 1-2/3'}
            return response
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)/'update.zip'
            download_asset(asset(), target, version='1.5.5', opener=invalid, sleep=Mock())
            self.assertEqual(target.read_bytes(), DATA)

    def test_corrupt_parts_are_cleared_and_never_returned_as_an_update(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                self.transfer(directory, Server(corrupt=True))
            self.assertFalse((Path(directory)/'update.zip').exists())
            self.assertFalse(list((Path(directory)/'cache').glob('*/part-*')))
            _, target = self.transfer(directory, Server())
            self.assertEqual(target.read_bytes(), DATA)

    def test_replaced_asset_uses_another_cache_key(self):
        with tempfile.TemporaryDirectory() as directory:
            self.transfer(directory, Server())
            changed = DATA[:-1]+b'X'
            server = Server(changed)
            _, target = self.transfer(directory, server, destination='new-build.zip')
            self.assertEqual(target.read_bytes(), changed)
            self.assertEqual(len(server.requests), 5)

    def test_unofficial_redirect_is_rejected_before_parallel_connections(self):
        with tempfile.TemporaryDirectory() as directory:
            server = Server(redirect='https://untrusted.example/download')
            with self.assertRaisesRegex(ValueError, '官方地址'):
                self.transfer(directory, server)
            self.assertEqual(len(server.requests), 1)


if __name__ == '__main__':
    unittest.main()
