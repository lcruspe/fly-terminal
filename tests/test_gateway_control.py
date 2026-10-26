import base64
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
from unittest.mock import patch, MagicMock
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location('gateway_control', Path(__file__).resolve().parents[1] / 'macos/gateway-control.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GatewayControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = module.ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.host = '127.0.0.1:%d' % cls.server.server_port
        cls.url = 'http://' + cls.host

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.env = patch.dict(os.environ, TERMINAL_USER='admin-test', TERMINAL_PASSWORD='password-test')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.headers = {
            'Authorization': 'Basic ' + base64.b64encode(b'admin-test:password-test').decode(),
            'Content-Type': 'application/json', 'Origin': self.url, 'X-Gateway-CSRF': module.CSRF,
        }

    def test_roomaudio_source_health_is_independent_of_silence(self):
        for online, expected in ((True, 'up'), (False, 'down'), (None, 'unknown')):
            response = MagicMock()
            response.__enter__.return_value.read.return_value = json.dumps(
                {'source_online': online, 'mic_silent': True}).encode()
            with patch.object(Path, 'read_text', return_value=json.dumps(
                    {'username': 'test', 'password': 'secret'})), \
                    patch.object(module, 'urlopen', return_value=response) as request:
                self.assertEqual(module.roomaudio_status(),
                                 {'roomaudio': 'up', 'roomaudio_source': expected})
                self.assertEqual(request.call_args.args[0].full_url,
                                 'http://127.0.0.1:8766/api/status')

    def test_roomaudio_failure_leaves_source_unknown(self):
        with patch.object(Path, 'read_text', side_effect=OSError):
            self.assertEqual(module.roomaudio_status(), {'roomaudio_source': 'unknown'})

    def post(self, data, headers=None):
        req = Request(self.url + '/gateway-control/action', data=json.dumps(data).encode(), headers=self.headers if headers is None else headers)
        try:
            with urlopen(req, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_terminal_and_gateway_cannot_be_stopped(self):
        for service in ('terminal', 'ttyd', 'gateway', 'caddy'):
            with patch.object(module, 'execute') as execute:
                self.assertEqual(self.post({'service': service, 'action': 'stop', 'confirmed': True})[0], 400)
                execute.assert_not_called()

    def test_authentication_required_even_on_loopback(self):
        with patch.object(module, 'execute') as execute:
            self.assertEqual(self.post({'service': 'yt', 'action': 'start'}, headers={})[0], 401)
            execute.assert_not_called()

    def test_secondary_account_is_rejected(self):
        headers = {**self.headers, 'Authorization': 'Basic ' + base64.b64encode(b'sprut-test:password-test').decode()}
        self.assertEqual(self.post({'service': 'yt', 'action': 'start'}, headers=headers)[0], 401)

    def test_cross_origin_or_missing_csrf_is_rejected(self):
        for extra in ({'Origin':'https://untrusted.example'}, {'X-Gateway-CSRF':''}):
            with patch.object(module, 'execute') as execute:
                self.assertEqual(self.post({'service':'yt','action':'start'}, {**self.headers, **extra})[0], 403)
                execute.assert_not_called()

    def test_confirmation_required_for_disruptive_actions(self):
        for service, action in (('yt','stop'), ('native','restart'), ('openwrt','vpn-disconnect')):
            with patch.object(module, 'execute') as execute:
                self.assertEqual(self.post({'service':service, 'action':action})[0], 400)
                execute.assert_not_called()

    def test_only_whitelisted_action_is_dispatched(self):
        with patch.object(module, 'execute') as execute:
            self.assertEqual(self.post({'service':'yt','action':'restart','confirmed':True})[0], 200)
            execute.assert_called_once_with('yt','restart')
        with patch.object(module, 'execute') as execute:
            self.assertEqual(self.post({'service':'yt;rm','action':'start'})[0], 400)
            execute.assert_not_called()

    def test_failure_releases_service_lock(self):
        with patch.object(module, 'execute', side_effect=RuntimeError('test')):
            self.assertEqual(self.post({'service':'yt','action':'start'})[0], 502)
        self.assertFalse(module.LOCKS['yt'].locked())

    def test_busy_service_is_not_dispatched(self):
        lock = module.LOCKS['yt']
        lock.acquire()
        try:
            with patch.object(module, 'execute') as execute:
                self.assertEqual(self.post({'service':'yt','action':'start'})[0], 409)
                execute.assert_not_called()
        finally:
            lock.release()

    def test_stop_uses_bootout_without_disabling_next_boot(self):
        with patch.object(module.Path, 'is_file', return_value=True), patch.object(module, 'loaded', return_value=True), patch.object(module, 'run') as run:
            module.execute('yt','stop')
        run.assert_called_once_with(['/bin/launchctl','bootout',module.DOMAIN+'/com.kruspe.yttranscriber'])

    def test_native_shutdown_order(self):
        with patch.object(module, 'agent') as agent:
            module.execute('native','stop')
        self.assertEqual([call.args[0] for call in agent.call_args_list], list(reversed(module.GROUPS['native'])))

    def test_router_controls_only_vpn(self):
        with patch.object(module, 'router', return_value=type('Result', (), {'stdout':'{}'})()) as router:
            module.execute('openwrt','vpn-disconnect')
            router.assert_called_once_with('disconnect')
        self.assertNotIn('restart', module.ACTIONS['openwrt'])


if __name__ == '__main__':
    unittest.main()
