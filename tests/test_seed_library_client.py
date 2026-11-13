import io
import json
import unittest
from unittest.mock import Mock
import urllib.error

from combat_rotation import default_store, new_module
from combat_seed import decode_seed, export_seed, import_seed
from seed_library import upload_seed,search_seeds,download_seed


def response(data):
    return io.BytesIO(json.dumps(data,ensure_ascii=False).encode())


class SeedLibraryClientTests(unittest.TestCase):
    def test_download_edit_rename_and_share_uses_the_library_title_on_redownload(self):
        source = default_store()['presets'][0]
        original = export_seed(source, seed_name='A轴')
        store, original_id = import_seed(default_store(), original, from_library=True)
        edited = next(p for p in store['presets'] if p['id'] == original_id)
        self.assertEqual(edited['name'], 'A轴')
        edited['name'] = 'B轴'
        edited['modules'].append(new_module('dodge', 2))
        shared = export_seed(edited)
        self.assertEqual(decode_seed(shared)['seed_name'], 'B轴')
        downloaded, _ = import_seed(default_store(), shared, from_library=True)
        self.assertEqual(downloaded['presets'][-1]['name'], 'B轴')
        self.assertTrue(any(m['kind'] == 'dodge' and m['slot'] == 2 for m in downloaded['presets'][-1]['modules']))
        downloaded, _ = import_seed(downloaded, shared, from_library=True)
        self.assertEqual([p['name'] for p in downloaded['presets'][-2:]], ['B轴', 'B轴（2）'])
        self.assertEqual(decode_seed(original)['seed_name'], 'A轴')

    def test_upload_sends_seed_only_without_local_configuration(self):
        seed=export_seed(default_store()['presets'][0])
        opened=Mock(return_value=response({'item':{'id':'a'*24,'name':'默认战斗轴'}}))
        upload_seed(seed,opener=opened)
        body=json.loads(opened.call_args.args[0].data)
        self.assertEqual(body,{'seed':seed})
        self.assertEqual(opened.call_args.args[0].method,'POST')

    def test_search_names_are_encoded_and_search_limit_enforced(self):
        opened=Mock(return_value=response({'items':[{'id':'a'*24,'name':'测试&名称'}],'truncated':False}))
        items,truncated=search_seeds('测试&名称',opener=opened)
        self.assertEqual(items[0]['name'],'测试&名称')
        self.assertFalse(truncated)
        self.assertIn('%26',opened.call_args.args[0].full_url)
        with self.assertRaises(ValueError):
            search_seeds('一'*11,opener=opened)

    def test_download_requires_correct_id_valid_seed_and_same_name(self):
        seed=export_seed(default_store()['presets'][0])
        opened=Mock(return_value=response({'item':{'id':'a'*24,'name':'默认战斗轴','seed':seed}}))
        self.assertEqual(download_seed('a'*24,opener=opened),seed)
        for item in ({'id':'b'*24,'name':'默认战斗轴','seed':seed},
                     {'id':'a'*24,'name':'其他名称','seed':seed},
                     {'id':'a'*24,'name':'默认战斗轴','seed':'run a command'}):
            with self.assertRaises(ValueError):
                download_seed('a'*24,opener=Mock(return_value=response({'item':item})))

    def test_network_failure_is_a_user_readable_error(self):
        with self.assertRaisesRegex(RuntimeError,'检查网络'):
            search_seeds(opener=Mock(side_effect=urllib.error.URLError('timeout')))


if __name__=='__main__':
    unittest.main()
