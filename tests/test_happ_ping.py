import importlib.util
import json
from pathlib import Path
import socket
import threading
import time
import unittest
from unittest.mock import patch

import happ_ping

spec = importlib.util.spec_from_file_location("session_control_ping_test", Path(__file__).resolve().parents[1] / "session-control.py")
control = importlib.util.module_from_spec(spec)
spec.loader.exec_module(control)


def subscription():
    return {"id": "sub-a", "label": "A", "locations": [
        {"id": "one", "label": "First", "_pingTarget": ("private.example", 443)},
        {"id": "two", "label": "Second", "_pingTarget": ("private.example", 443)},
    ]}


class PingTests(unittest.TestCase):
    def test_real_tcp_connect_and_refused_connection(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            target = server.getsockname()
            server.listen()
            result = happ_ping.tcp_ping(target)
            self.assertEqual(result["status"], "ok")
            self.assertGreaterEqual(result["rttMs"], 0)
        with patch.object(happ_ping.socket, "create_connection", side_effect=ConnectionRefusedError()):
            self.assertEqual(happ_ping.tcp_ping(("127.0.0.1", 1))["status"], "unreachable")

    def test_timeout_and_missing_target_never_leak_network_error_text(self):
        with patch.object(happ_ping.socket, "create_connection", side_effect=TimeoutError("private-host-and-token")):
            result = happ_ping.tcp_ping(("private.example", 443))
        self.assertEqual(result, {"status": "timeout", "rttMs": None})
        self.assertEqual(happ_ping.tcp_ping(None), {"status": "unsupported", "rttMs": None})

    def test_cache_deduplicates_targets_and_expires_at_180_seconds(self):
        measurements = happ_ping.Measurements()
        clock = [1000.0]
        sub = subscription()
        with patch.object(happ_ping.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(happ_ping, "tcp_ping", return_value={"status": "ok", "rttMs": 12.3}) as probe:
            results = measurements.measure(sub)
            self.assertEqual(probe.call_count, 1)
            self.assertEqual(len(results), 2)
            self.assertNotIn("private", json.dumps(results))
            self.assertEqual(results[0]["expiresInMs"], 180000)
            clock[0] += 179
            self.assertEqual(measurements.latest(sub["id"], sub["locations"][0])["expiresInMs"], 1000)
            clock[0] += 1
            self.assertIsNone(measurements.latest(sub["id"], sub["locations"][0]))

    def test_results_are_scoped_to_subscription_and_changed_endpoints_are_rejected(self):
        measurements = happ_ping.Measurements()
        sub = subscription()
        with patch.object(happ_ping, "tcp_ping", return_value={"status": "ok", "rttMs": 10}):
            measurements.measure(sub)
        self.assertIsNone(measurements.latest("another-sub", sub["locations"][0]))
        changed = dict(sub["locations"][0], _pingTarget=("changed.example", 443))
        self.assertIsNone(measurements.latest(sub["id"], changed))

    def test_new_measurement_replaces_previous_result_and_resets_its_expiry(self):
        measurements = happ_ping.Measurements()
        clock = [0.0]
        sub = subscription()
        with patch.object(happ_ping.time, "monotonic", side_effect=lambda: clock[0]), \
             patch.object(happ_ping, "tcp_ping", side_effect=[{"status": "ok", "rttMs": 10}, {"status": "timeout", "rttMs": None}]):
            measurements.measure(sub)
            clock[0] = 150
            measurements.measure(sub)
            clock[0] = 180
            latest = measurements.latest(sub["id"], sub["locations"][0])
            self.assertEqual(latest["status"], "timeout")
            self.assertEqual(latest["expiresInMs"], 150000)

    def test_workers_are_bounded_and_simultaneous_batches_are_rejected(self):
        measurements = happ_ping.Measurements()
        guard = threading.Lock()
        active, maximum = 0, 0
        def probe(target):
            nonlocal active, maximum
            with guard:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.01)
            with guard:
                active -= 1
            return {"status": "ok", "rttMs": 1}
        sub = {"id": "many", "locations": [{"id": str(i), "_pingTarget": ("example.test", i + 1)} for i in range(20)]}
        with patch.object(happ_ping, "tcp_ping", side_effect=probe):
            self.assertEqual(len(measurements.measure(sub)), 20)
        self.assertGreater(maximum, 1)
        self.assertLessEqual(maximum, happ_ping.MAX_WORKERS)
        measurements._batch_lock.acquire()
        try:
            with self.assertRaises(happ_ping.PingBusyError):
                measurements.measure(sub)
        finally:
            measurements._batch_lock.release()

    def test_endpoint_probes_only_selected_subscription_and_ignores_client_targets(self):
        handler = object.__new__(control.SessionControlHandler)
        handler._read_json_body = lambda: ({"subscriptionId": "sub-a", "host": "client-override.test", "port": 1}, None)
        catalog = {"canPing": True, "subscriptions": [subscription(), {"id": "other", "locations": []}]}
        with patch.object(control, "happ_ui_catalog", return_value=catalog), \
             patch.object(control, "HAPP_PING_MEASUREMENTS", happ_ping.Measurements()), \
             patch.object(happ_ping, "tcp_ping", return_value={"status": "ok", "rttMs": 10}) as probe, \
             patch.object(control, "send_json") as send:
            handler._handle_happ_ping()
            self.assertEqual(send.call_args.args[1], 200)
            self.assertNotIn("private.example", json.dumps(send.call_args.args[2]))
            probe.assert_called_once_with(("private.example", 443))

    def test_endpoint_reports_unknown_subscription_and_busy_batch(self):
        handler = object.__new__(control.SessionControlHandler)
        handler._read_json_body = lambda: ({"subscriptionId": "missing"}, None)
        catalog = {"canPing": True, "subscriptions": [subscription()]}
        with patch.object(control, "happ_ui_catalog", return_value=catalog), patch.object(control, "send_json") as send:
            handler._handle_happ_ping()
            self.assertEqual(send.call_args.args[1], 404)
            handler._read_json_body = lambda: ({"subscriptionId": "sub-a"}, None)
            with patch.object(control.HAPP_PING_MEASUREMENTS, "measure", side_effect=happ_ping.PingBusyError()):
                handler._handle_happ_ping()
                self.assertEqual(send.call_args.args[1], 409)


if __name__ == "__main__":
    unittest.main()
