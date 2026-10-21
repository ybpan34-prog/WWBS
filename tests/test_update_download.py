import io
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import urllib.error

from update_manager import download_asset, signal_update_ready, refresh_release_asset


class DownloadTests(unittest.TestCase):
    def asset(self, size=10):
        return {'browser_download_url':'https://github.com/ybpan34-prog/WWBS/releases/download/v1.5.4/wwbs-exe.zip',
                'url':'https://api.github.com/repos/ybpan34-prog/WWBS/releases/assets/123','size':size}

    def test_partial_download_retries_from_clean_file_and_renews_redirect(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'update.zip'
            data=b'PK\x03\x04abcdef'
            opened=Mock(side_effect=[io.BytesIO(data[:6]),io.BytesIO(data)])
            sleep=Mock()
            progress=Mock()
            download_asset(self.asset(),path,version='1.5.4',opener=opened,sleep=sleep,progress=progress)
            self.assertEqual(path.read_bytes(),data)
            self.assertIn('wwbs_update=',opened.call_args_list[0].args[0].full_url)
            self.assertTrue(opened.call_args_list[1].args[0].full_url.startswith(self.asset()['url']+'?wwbs_update='))
            self.assertEqual(progress.call_args.args,(10,10))

    def test_html_and_failed_network_do_not_reach_install(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'update.zip'
            opened=Mock(side_effect=[urllib.error.URLError('network'),io.BytesIO(b'<html>bad'),io.BytesIO(b'PK\x03\x04abcdef')])
            download_asset(self.asset(),path,version='1.5.4',opener=opened,sleep=Mock())
            self.assertEqual(opened.call_count,3)
            opened=Mock(side_effect=urllib.error.URLError('network'))
            with self.assertRaisesRegex(RuntimeError,'重试3次'):
                download_asset(self.asset(),path,version='1.5.4',opener=opened,sleep=Mock())

    def test_cancel_keeps_original_files_and_stops_before_request(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old=root/'wwbs.exe'
            old.write_bytes(b'old')
            opener=Mock()
            with self.assertRaises(InterruptedError):
                download_asset(self.asset(),root/'update.zip',version='1.5.4',opener=opener,cancelled=lambda:True)
            opener.assert_not_called()
            self.assertEqual(old.read_bytes(),b'old')

    def test_small_network_fragments_do_not_reject_a_valid_zip_signature(self):
        data=b'PK\x03\x04abcdef'
        class Fragmented(io.BytesIO):
            def read1(self, size):
                return super().read(1)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'update.zip'
            download_asset(self.asset(), path, version='1.5.5', opener=Mock(return_value=Fragmented(data)))
            self.assertEqual(path.read_bytes(), data)

    def test_truncated_http_stream_resumes_from_the_last_written_byte(self):
        data=b'PK\x03\x04abcdef'
        class Broken(io.BytesIO):
            def read(self,_size):
                if self.tell():
                    raise http.client.IncompleteRead(b'',4)
                return super().read(6)
            read1 = read
        class Partial(io.BytesIO):
            status=206
            headers={'Content-Range':'bytes 6-9/10'}
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'update.zip'
            opened=Mock(side_effect=[Broken(data),Partial(data[6:])])
            download_asset(self.asset(),target,version='1.5.5 beta1',opener=opened,sleep=Mock())
            self.assertEqual(target.read_bytes(),data)
            self.assertEqual(opened.call_args_list[1].args[0].get_header('Range'),'bytes=6-')

    def test_checksum_failure_retries_from_zero_and_never_returns_corrupt_data(self):
        data=b'PK\x03\x04abcdef'
        asset=self.asset()|{'digest':'sha256:'+hashlib.sha256(data).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'update.zip'
            opened=Mock(side_effect=[io.BytesIO(data[:-1]+b'x'),io.BytesIO(data)])
            download_asset(asset,target,version='1.5.5 beta1',opener=opened,sleep=Mock())
            self.assertEqual(target.read_bytes(),data)
            self.assertIsNone(opened.call_args_list[1].args[0].get_header('Range'))

    def test_replaced_release_asset_refreshes_size_id_and_checksum_before_retry(self):
        data=b'PK\x03\x04abcdef'
        old=self.asset(size=9)|{'id':1}
        fresh=self.asset()|{'id':2,'digest':'sha256:'+hashlib.sha256(data).hexdigest()}
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'update.zip'
            returned=download_asset(old,target,version='1.5.5 beta1',
                opener=Mock(side_effect=[io.BytesIO(data),io.BytesIO(data)]),refresh=Mock(return_value=fresh),sleep=Mock())
            self.assertEqual(returned,fresh)
            self.assertEqual(target.read_bytes(),data)

    def test_refresh_uses_the_selected_release_tag_and_uncached_metadata(self):
        fresh=self.asset()|{'id':2,'name':'wwbs-exe.zip','state':'uploaded'}
        opened=Mock(return_value=io.BytesIO(json.dumps({'tag_name':'v1.5.5-beta1','assets':[fresh]}).encode()))
        self.assertEqual(refresh_release_asset(self.asset(),'v1.5.5-beta1',opener=opened),fresh)
        self.assertIn('/releases/tags/v1.5.5-beta1?wwbs_update=',opened.call_args.args[0].full_url)
        wrong=Mock(return_value=io.BytesIO(json.dumps({'tag_name':'v9.0.0','assets':[fresh]}).encode()))
        with self.assertRaisesRegex(RuntimeError,'版本信息不一致'):
            refresh_release_asset(self.asset(),'v1.5.5-beta1',opener=wrong)

    def test_invalid_resume_range_cannot_append_unrelated_bytes(self):
        data=b'PK\x03\x04abcdef'
        class Partial(io.BytesIO):
            status=206
            headers={'Content-Range':'bytes 5-9/10'}
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'update.zip'
            opened=Mock(side_effect=[io.BytesIO(data[:6]),Partial(data[5:]),io.BytesIO(data)])
            download_asset(self.asset(),target,version='1.5.5 beta1',opener=opened,sleep=Mock())
            self.assertEqual(target.read_bytes(),data)

    def test_startup_acknowledgement_accepts_update_work_beside_executable(self):
        import update_manager as manager
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            folder=root/('.wwbs-update-work-'+'a'*32)
            folder.mkdir()
            ready=folder/'ready'
            with patch.object(manager.sys,'frozen',True,create=True), \
                    patch.object(manager.sys,'executable',str(root/'wwbs.exe')), \
                    patch.dict(manager.os.environ,{'WWBS_UPDATE_READY':str(ready),'WWBS_UPDATE_TOKEN':'b'*32}):
                signal_update_ready()
            self.assertEqual(ready.read_text(),'b'*32)


if __name__=='__main__':
    unittest.main()
