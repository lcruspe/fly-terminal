import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "session-control.py"
spec = importlib.util.spec_from_file_location("session_control_gateway", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class GatewayStatusTests(unittest.TestCase):
    def test_probes_are_parallel_and_include_all_cards(self):
        with patch.dict(module.os.environ, {
            "FLY_NATIVE_BROWSER_ENABLED": "1",
            "FLY_BROWSER_ENABLED": "1",
            "FLY_SPRUTHUB_ENABLED": "1",
            "TERMINAL_USER": "test",
            "TERMINAL_PASSWORD": "test",
        }), patch.object(module, "_gateway_http_probe", return_value=True) as probe:
            statuses = module.gateway_service_statuses()
        self.assertEqual(set(statuses), {"terminal", "native", "fallback", "roomaudio", "yt", "spruthub"})
        self.assertTrue(all(value == "up" for value in statuses.values()))
        self.assertEqual(probe.call_count, 6)

    def test_disabled_services_do_not_get_probed(self):
        with patch.dict(module.os.environ, {
            "FLY_NATIVE_BROWSER_ENABLED": "0",
            "FLY_BROWSER_ENABLED": "0",
            "FLY_SPRUTHUB_ENABLED": "0",
            "TERMINAL_USER": "",
            "TERMINAL_PASSWORD": "",
        }), patch.object(module, "_gateway_http_probe", return_value=True) as probe:
            statuses = module.gateway_service_statuses()
        for key in ("native", "fallback", "spruthub", "roomaudio"):
            self.assertEqual(statuses[key], "down")
        self.assertEqual(statuses["terminal"], "up")
        self.assertEqual(statuses["yt"], "up")
        self.assertEqual(probe.call_count, 2)

    def test_roomaudio_rejects_gateway_catch_all(self):
        class Response:
            status = 200
            def read(self, _):
                return b'<html><title>Gateway</title><strong>Fly Terminal</strong></html>'
        class Connection:
            def __init__(self, *args, **kwargs):
                pass
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return Response()
            def close(self):
                pass
        with patch.object(module.http.client, "HTTPConnection", Connection):
            self.assertFalse(module._gateway_http_probe(8080, "/roomaudio/", gateway_page=True))
            self.assertTrue(module._gateway_http_probe(8080, "/"))


    def test_roomaudio_own_basic_auth_counts_as_up(self):
        class Response:
            status = 401
        class Connection:
            def __init__(self, *args, **kwargs):
                pass
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return Response()
            def close(self):
                pass
        with patch.object(module.http.client, "HTTPConnection", Connection):
            self.assertTrue(module._gateway_http_probe(
                8080, "/roomaudio/", headers={"Authorization": "Basic test"}, gateway_page=True
            ))

    def test_native_websocket_rejection_means_listener_is_up(self):
        class Response:
            status = 426
        class Connection:
            def __init__(self, *args, **kwargs):
                pass
            def request(self, *args, **kwargs):
                pass
            def getresponse(self):
                return Response()
            def close(self):
                pass
        with patch.object(module.http.client, "HTTPConnection", Connection):
            self.assertTrue(module._gateway_http_probe(5906, websocket=True))
            self.assertFalse(module._gateway_http_probe(5906))


if __name__ == "__main__":
    unittest.main()
