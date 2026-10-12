"""Volume-based health checks for RoomAudio. No speech recognition on digital silence."""
from pathlib import Path
import re
import subprocess
import time

FFMPEG="/opt/homebrew/bin/ffmpeg"
ROOT=Path("/Volumes/WD/RoomAudio/silent-quarantine")
DB_RE=re.compile(r"(?:mean_volume|max_volume):\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB",re.I)
PEAK=re.compile(r"max_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB",re.I)
MEAN=re.compile(r"mean_volume:\s*(-?inf|-?\d+(?:\.\d+)?)\s*dB",re.I)

def measure(path,timeout=18):
    p=subprocess.run(
        [FFMPEG,"-hide_banner","-nostdin","-i",str(path),
         "-af","volumedetect","-f","null","-"],
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,text=True,
        timeout=timeout,errors="replace")
    mean=MEAN.search(p.stderr)
    peak=PEAK.search(p.stderr)
    if p.returncode!=0 or not mean or not peak:
        raise RuntimeError("Cannot measure audio level, refusing to classify")
    return float(mean.group(1)),float(peak.group(1))

def silent(mean,peak):
    # 20+ dB below normal quiet speech. Avoid removing faint audible material.
    return mean<=-78.0 and peak<=-60.0

def quarantine(path,source,root=ROOT):
    p=Path(path)
    target=root/source/p.parent.name/p.name
    target.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if target.exists():
        raise FileExistsError("Quarantine collision: "+str(target))
    p.replace(target)
    return target
