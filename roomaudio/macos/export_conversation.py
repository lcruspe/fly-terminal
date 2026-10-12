#!/usr/bin/env python3
"""Build one chronological MP3 per conversation from RoomAudio's 15-second sources.

Timeline gaps are silent rather than removed; duplicate or overlapping sources
are placed at their original timestamps, never blindly concatenated.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import py_compile

APP = Path.home() / "Library" / "Application Support" / "RoomAudio"
REPORTS = Path.home() / "Documents" / "RoomAudio-reports" / "audio"
SEGMENT_RE = re.compile(r"^\d{8}T\d{6}\.mp3$")
SLUG_RE = re.compile(r"^[a-z0-9_-]{1,80}$")
FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2


def list_recordings(root, start, end):
    day = (start - dt.timedelta(seconds=15)).date()
    while day <= end.date():
        folder = root / day.strftime("%Y%m%d")
        if folder.is_dir():
            for path in folder.glob("*.mp3"):
                if not SEGMENT_RE.fullmatch(path.name):
                    continue
                timestamp = dt.datetime.strptime(path.stem, "%Y%m%dT%H%M%S")
                if start - dt.timedelta(seconds=15) < timestamp < end:
                    yield timestamp, path
        day += dt.timedelta(days=1)


def total_coverage(intervals):
    if not intervals:
        return 0.0
    intervals.sort()
    lo, hi = intervals[0]
    total = 0
    for a, b in intervals[1:]:
        if a > hi:
            total += hi - lo
            lo, hi = a, b
        else:
            hi = max(hi, b)
    return (total + hi - lo) / SAMPLE_RATE


def main():
    if sys.argv[1:] == ["--install"]:
        target = APP / "export_conversation.py"
        shutil.copyfile(__file__, target)
        target.chmod(0o700)
        py_compile.compile(str(target), doraise=True)
        print("INSTALLED", target)
        return
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, help="Local YYYY-MM-DDTHH:MM:SS")
    ap.add_argument("--end", required=True, help="Local YYYY-MM-DDTHH:MM:SS")
    ap.add_argument("--slug", required=True, help="Short safe Latin label for filename")
    ap.add_argument("--output-dir", default=str(REPORTS))
    args = ap.parse_args()
    start, end = (dt.datetime.fromisoformat(x) for x in (args.start, args.end))
    seconds = (end - start).total_seconds()
    if not 0 < seconds <= 4 * 3600 or start.tzinfo or end.tzinfo:
        ap.error("Duration must be 0..4 hours, using local timestamps without timezone")
    if not SLUG_RE.fullmatch(args.slug):
        ap.error("Slug must be lowercase Latin letters, digits, - or _, up to 80 characters")
    cfg = json.loads((APP / "config.json").read_text(encoding="utf-8"))
    archive = Path(cfg["archive"])
    if not archive.is_dir():
        ap.error("RoomAudio archive is unavailable")
    out = Path(args.output_dir)
    out.mkdir(parents=True, exist_ok=True)
    out.chmod(0o700)
    # File naming matches RoomAudio's authenticated report-audio GET endpoint.
    name = f"RoomAudio_{start:%Y-%m-%d_%H%M}-{end:%H%M}_{args.slug}.mp3"
    dest = out / name
    total_samples = round(seconds * SAMPLE_RATE)
    recordings = sorted(list_recordings(archive, start, end))
    if not recordings:
        ap.error("No source files within the requested interval")
    intervals = []
    failed = []
    with tempfile.TemporaryDirectory(prefix="roomaudio-export-") as d:
        raw = Path(d) / "timeline.pcm"
        with raw.open("wb+") as f:
            f.truncate(total_samples * BYTES_PER_SAMPLE)
            for timestamp, path in recordings:
                proc = subprocess.run(
                    [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin",
                     "-i", str(path), "-vn", "-f", "s16le", "-c:a", "pcm_s16le",
                     "-ar", str(SAMPLE_RATE), "-ac", "1", "pipe:1"],
                    capture_output=True, timeout=40,
                )
                if proc.returncode or not proc.stdout:
                    failed.append(path.name)
                    continue
                offset = round((timestamp - start).total_seconds() * SAMPLE_RATE)
                payload = proc.stdout
                first_sample = max(0, offset)
                source_start = max(0, -offset)
                length = min(len(payload) // BYTES_PER_SAMPLE - source_start,
                             total_samples - first_sample)
                if length <= 0:
                    continue
                f.seek(first_sample * BYTES_PER_SAMPLE)
                f.write(payload[source_start * BYTES_PER_SAMPLE:
                                (source_start + length) * BYTES_PER_SAMPLE])
                intervals.append((first_sample, first_sample + length))
        tmp_mp3 = Path(d) / name
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
               "-f", "s16le", "-ar", str(SAMPLE_RATE), "-ac", "1",
               "-i", str(raw), "-c:a", "libmp3lame", "-b:a", "96k",
               "-metadata", "comment=Chronological RoomAudio source, timestamp gaps preserved as silence",
               str(tmp_mp3)]
        subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        os.chmod(tmp_mp3, 0o600)
        os.replace(tmp_mp3, dest)
    print(json.dumps({
        "path": str(dest), "filename": name,
        "url_path": "/roomaudio/api/reports/audio/" + name,
        "file_bytes": dest.stat().st_size,
        "duration_sec": seconds,
        "covered_sec": round(total_coverage(intervals), 1),
        "silent_gaps_sec": round(seconds - total_coverage(intervals), 1),
        "source_count": len(recordings), "decode_failures": failed
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
