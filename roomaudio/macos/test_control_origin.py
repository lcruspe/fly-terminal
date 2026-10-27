"""CSRF regressions across all Fly Terminal RoomAudio entrypoints."""
import unittest
from control_origin import permitted_origin


class ControlOriginTests(unittest.TestCase):
    def test_trusted_https_same_origin(self):
        for host in (
            "129-158-49-130.sslip.io",
            "home.tail1c55c5.ts.net",
            "mac-gateway.tail1c55c5.ts.net",
            "commander-hub.tail1c55c5.ts.net",
            "other-alias.tail1c55c5.ts.net",
        ):
            with self.subTest(host=host):
                self.assertTrue(permitted_origin("https://" + host, host))

    def test_local_direct_same_origin(self):
        for host in ("127.0.0.1:8766", "localhost:8766", "192.168.1.201:8766",
                     "kruspe-mac-mini.local:8766", "100.105.89.30:8766"):
            with self.subTest(host=host):
                self.assertTrue(permitted_origin("http://" + host, host))

    def test_other_origin_cannot_write_through_trusted_host(self):
        self.assertFalse(permitted_origin("https://home.tail1c55c5.ts.net",
                                          "commander-hub.tail1c55c5.ts.net"))
        self.assertFalse(permitted_origin("https://evil.example", "commander-hub.tail1c55c5.ts.net"))
        self.assertFalse(permitted_origin("http://127.0.0.1:8766", "192.168.1.201:8766"))

    def test_untrusted_host_is_not_accepted_even_when_same_origin(self):
        for origin in ("https://evil.example", "https://tail1c55c5.ts.net.evil.example",
                       "http://evil.local:8766", "https://129-158-49-130.sslip.io.evil.test",
                       "https://tail1c55c5.ts.net"):
            with self.subTest(origin=origin):
                self.assertFalse(permitted_origin(origin, origin.split('//')[1]))

    def test_reject_malformed_credentials_ports_and_insecure_transport(self):
        for origin, host in (
            ("", "commander-hub.tail1c55c5.ts.net"),
            ("null", "commander-hub.tail1c55c5.ts.net"),
            ("https://evil@commander-hub.tail1c55c5.ts.net", "evil@commander-hub.tail1c55c5.ts.net"),
            ("https://commander-hub.tail1c55c5.ts.net/a", "commander-hub.tail1c55c5.ts.net"),
            ("http://commander-hub.tail1c55c5.ts.net", "commander-hub.tail1c55c5.ts.net"),
            ("http://192.168.1.201:8080", "192.168.1.201:8080"),
            ("https://[broken", "[broken"),
        ):
            with self.subTest(origin=origin):
                self.assertFalse(permitted_origin(origin, host))

    def test_missing_host_and_unrelated_suffix(self):
        self.assertFalse(permitted_origin("https://commander-hub.tail1c55c5.ts.net", ""))
        self.assertFalse(permitted_origin("https://commander-hub.tail1c55c5.ts.net", "rogue.ts.net"))


if __name__ == "__main__":
    unittest.main()
