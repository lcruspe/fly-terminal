"""Regression tests for uninterrupted MP3 packet ordering and bounded clients."""
import unittest
from unittest.mock import patch
from live_relay import LiveHub


class LiveRelayTests(unittest.TestCase):
    def test_ordered_bytes(self):
        hub = LiveHub()
        session = "a" * 32
        self.assertTrue(hub.ingest_packet(session, 0, b"ID3"))
        self.assertTrue(hub.ingest_packet(session, 1, b"frame1"))
        gen, seq = hub.subscribe()
        chunks, last = hub.read(gen, seq, wait=0)
        self.assertEqual(b"".join(packet for _, packet in chunks), b"ID3frame1")
        self.assertEqual(last, 2)
        hub.unsubscribe()

    def test_reject_missing_duplicate_and_invalid_packets(self):
        hub = LiveHub()
        session = "b" * 32
        self.assertFalse(hub.ingest_packet(session, 1, b"late"))
        self.assertFalse(hub.ingest_packet("invalid", 0, b"hello"))
        self.assertFalse(hub.ingest_packet(session, 0, b""))
        self.assertTrue(hub.ingest_packet(session, 0, b"start"))
        self.assertFalse(hub.ingest_packet(session, 0, b"duplicate"))
        self.assertFalse(hub.ingest_packet(session, 2, b"missing"))
        self.assertFalse(hub.ingest_packet(session, 1, b"x" * 65537))
        self.assertTrue(hub.ingest_packet(session, 1, b"next"))

    def test_source_change_closes_old_reader(self):
        hub = LiveHub()
        self.assertTrue(hub.ingest_packet("c" * 32, 0, b"old"))
        gen, seq = hub.subscribe()
        self.assertTrue(hub.ingest_packet("d" * 32, 0, b"new"))
        self.assertIsNone(hub.read(gen, seq, wait=0))
        self.assertEqual(hub.status()["listeners"], 1)
        hub.unsubscribe()

    def test_bounded_ring(self):
        hub = LiveHub(max_bytes=20)
        session = "e" * 32
        for i in range(20):
            self.assertTrue(hub.ingest_packet(session, i, bytes([i])*5))
        self.assertLessEqual(hub.status()["buffer_bytes"], 20)
        gen, seq = hub.subscribe()
        packets, _ = hub.read(gen, seq, wait=0)
        self.assertEqual(packets[-1][1], bytes([19])*5)
        hub.unsubscribe()

    def test_source_times_out(self):
        hub = LiveHub()
        with patch("live_relay.time.monotonic", return_value=100.0):
            self.assertTrue(hub.ingest_packet("f"*32, 0, b"ID3"))
            self.assertTrue(hub.status()["online"])
        with patch("live_relay.time.monotonic", return_value=109.0):
            self.assertFalse(hub.status()["online"])
            self.assertIsNone(hub.subscribe())
        with patch("live_relay.time.monotonic", return_value=110.0):
            self.assertFalse(hub.ingest_packet("f"*32, 1, b"old"))
            self.assertTrue(hub.ingest_packet("f"*32, 0, b"ID3new"))


if __name__ == "__main__":
    unittest.main()