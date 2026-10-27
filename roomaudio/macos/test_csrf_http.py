"""HTTP-level CSRF integration using isolated fake credentials and scheduler state."""
import importlib.util
import json
import shutil
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener


class CsrfHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.source = Path(__file__).resolve().parent
        shutil.copy2(cls.source / 'server.py', cls.root / 'server.py')
        (cls.root / 'archive').mkdir()
        (cls.root / 'config.json').write_text(json.dumps({
            'archive': str(cls.root / 'archive'), 'ingest_key':'fake-ingest-key',
            'username':'test-operator', 'password':'fake-password', 'port':0,
            'retention_days':30,
        }))
        spec = importlib.util.spec_from_file_location('roomaudio_test_http_server', cls.root / 'server.py')
        cls.module = importlib.util.module_from_spec(spec)
        # Test fixture has no external drive; production disk guard remains untouched.
        with patch('os.path.ismount', return_value=True):
            spec.loader.exec_module(cls.module)
        cls.original_settings_path = cls.module.recording_settings.PATH
        cls.module.recording_settings.PATH = cls.root / 'capture_settings.json'
        cls.module.recording_settings.PATH.write_text(json.dumps({'mode':'voice'}))
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), cls.module.Handler)
        cls.httpd.daemon_threads = True
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:%d' % cls.httpd.server_port
        cls.opener = build_opener(ProxyHandler({}))

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        cls.module.recording_settings.PATH = cls.original_settings_path
        cls.tmp.cleanup()

    @classmethod
    def call(cls, path, *, cookie=None, token=None, payload=None, origin=None):
        headers = {'Content-Type':'application/json'}
        if cookie: headers['Cookie'] = cookie
        if token: headers['X-RoomAudio-CSRF'] = token
        if origin: headers['Origin'] = origin
        request = Request(cls.url + path, headers=headers,
                          data=json.dumps(payload).encode() if payload is not None else None,
                          method='POST' if payload is not None else 'GET')
        try:
            with cls.opener.open(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            error.close()
            return error.code, None

    def test_cookie_bound_token_allows_schedule_over_any_proxy_origin(self):
        cookie = self.module.SESSION_COOKIE + '=' + self.module.Handler.cookie_value()
        code, result = self.call('/api/csrf-token', cookie=cookie)
        self.assertEqual(code, 200)
        token = result['token']
        self.assertRegex(token, r'^[0-9a-f]{64}$')
        existing = {'enabled':False,'mode':'voice','rules':[]}
        # Simulate reverse-proxy rewriting Host independent of browser Origin.
        code, state = self.call('/api/recording-schedule', cookie=cookie, token=token,
                                origin='https://new-user-gateway.example', payload=existing)
        self.assertEqual(code, 200)
        self.assertEqual(state['mode'], 'voice')
        self.assertFalse(state['schedule']['enabled'])
        self.assertEqual(self.module.recording_settings.mode(), 'voice')

    def test_reject_cross_site_without_readable_token(self):
        cookie = self.module.SESSION_COOKIE + '=' + self.module.Handler.cookie_value()
        good_code, data = self.call('/api/csrf-token', cookie=cookie)
        self.assertEqual(good_code, 200)
        payload = {'enabled':False,'mode':'voice','rules':[]}
        self.assertEqual(self.call('/api/recording-schedule', cookie=cookie, payload=payload)[0], 403)
        self.assertEqual(self.call('/api/recording-schedule', cookie=cookie,
                                   token='0'*64, payload=payload)[0], 403)
        other_cookie = self.module.SESSION_COOKIE + '=' + self.module.Handler.cookie_value()
        self.assertEqual(self.call('/api/recording-schedule', cookie=other_cookie,
                                   token=data['token'], payload=payload)[0], 403)

    def test_unauthenticated_requests(self):
        self.assertEqual(self.call('/api/csrf-token')[0], 401)
        self.assertEqual(self.call('/api/recording-schedule',
                                   token='0'*64, payload={'enabled':False,'mode':'voice','rules':[]})[0], 401)

    def test_json_only_and_other_controls(self):
        cookie = self.module.SESSION_COOKIE + '=' + self.module.Handler.cookie_value()
        _, token_data = self.call('/api/csrf-token', cookie=cookie)
        token = token_data['token']
        self.assertEqual(self.call('/api/recording-mode', cookie=cookie,
                                   token=token,payload={'mode':'voice'})[0], 200)
        self.assertEqual(self.call('/api/recording-mode', cookie=cookie,
                                   payload={'mode':'off'})[0], 403)
        self.assertEqual(self.module.recording_settings.mode(),'voice')


if __name__ == '__main__':
    unittest.main()
