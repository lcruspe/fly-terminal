"""Regression tests for timestamp-aware audio exports."""
import datetime as dt
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from export_conversation import list_recordings, total_coverage


class ConversationExportTests(unittest.TestCase):
    def test_coverage_merges_overlapping_recordings(self):
        intervals = [(0, 16000), (8000, 32000), (48000, 64000)]
        self.assertEqual(total_coverage(intervals), 3.0)

    def test_coverage_empty(self):
        self.assertEqual(total_coverage([]), 0.0)

    def test_sources_cross_midnight_in_timestamp_order(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name in ("20261012T235950", "20261013T000005", "20261013T000020"):
                folder = root/name[:8]
                folder.mkdir(exist_ok=True)
                (folder/(name+".mp3")).write_bytes(b"fake mp3")
            begin=dt.datetime(2026,10,13,0,0,0)
            end=dt.datetime(2026,10,13,0,0,25)
            rows=sorted(list_recordings(root, begin, end))
            self.assertEqual([p.name for _,p in rows], [
                "20261012T235950.mp3", "20261013T000005.mp3",
                "20261013T000020.mp3"
            ])

    def test_invalid_names_not_counted(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            folder=root/"20261012";folder.mkdir()
            (folder/"recording.mp3").write_bytes(b"bad")
            rows=list(list_recordings(root, dt.datetime(2026,10,12,12,0),dt.datetime(2026,10,12,13,0)))
            self.assertEqual(rows,[])


if __name__ == "__main__":
    unittest.main()
