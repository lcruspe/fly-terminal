"""Offline WebRTC voice-activity indexing for RoomAudio MP3 segments."""
from pathlib import Path
import json
import subprocess
import numpy as np
import webrtcvad

FRAME=960  # 20 ms at 48 kHz
RATE=48000
BOOST=8.0

def detect_float(samples):
    """Return speech windows in seconds from 48 kHz mono floating-point PCM."""
    from scipy.signal import butter, sosfilt
    samples=np.asarray(samples,dtype=np.float32)
    samples=sosfilt(butter(2,90,btype="highpass",fs=RATE,output="sos"),samples)
    samples=sosfilt(butter(2,7500,btype="lowpass",fs=RATE,output="sos"),samples)
    raw=np.clip(samples*32767,-32767,32767).astype("<i2")
    duration=len(raw)/RATE
    vad=webrtcvad.Vad(2)
    flags=[]
    for i in range(len(raw)//FRAME):
        frame=raw[i*FRAME:(i+1)*FRAME]
        boosted=np.clip(frame.astype(np.float32)*BOOST,-32767,32767).astype("<i2")
        rms=np.sqrt(np.mean(np.square(frame.astype(np.float32))))
        flags.append(bool(rms>=9.0 and vad.is_speech(boosted.tobytes(),RATE)))
    spans=[]
    first=last=None
    for i,active in enumerate(flags):
        if active:
            if first is None:first=i
            last=i
        elif first is not None and i-last>12:
            if last-first+1>=10:
                spans.append([round(max(0,first*.02-.18),2),
                              round(min(duration,(last+1)*.02+.30),2)])
            first=last=None
    if first is not None and last-first+1>=10:
        spans.append([round(max(0,first*.02-.18),2),
                      round(min(duration,(last+1)*.02+.30),2)])
    return spans

def detect_file(path,ffmpeg):
    cmd=[ffmpeg,"-hide_banner","-nostdin","-loglevel","error",
         "-i",str(path),"-af","highpass=f=90,lowpass=f=7500",
         "-ac","1","-ar","48000","-f","s16le","pipe:1"]
    r=subprocess.run(cmd,capture_output=True,timeout=22)
    if r.returncode:
        raise RuntimeError("Audio decode failure: "+r.stderr[-180:].decode(errors="replace"))
    raw=np.frombuffer(r.stdout,dtype="<i2")
    duration=len(raw)/RATE
    count=len(raw)//FRAME
    vad=webrtcvad.Vad(2)
    speech=[]
    for i in range(count):
        frame=raw[i*FRAME:(i+1)*FRAME]
        # Scale for VAD only; the archived MP3 remains unaltered.
        boosted=np.clip(frame.astype(np.float32)*BOOST,-32767,32767).astype("<i2")
        rms=np.sqrt(np.mean(np.square(frame.astype(np.float32))))
        active=rms>=9.0 and vad.is_speech(boosted.tobytes(),RATE)
        speech.append(active)
    # Merge positives separated by up to 240 ms; reject tiny isolated bursts.
    spans=[]
    first=None;last=None
    for i,active in enumerate(speech):
        if active:
            if first is None:first=i
            last=i
        elif first is not None and i-last>12:
            if last-first+1>=10:
                spans.append([round(max(0,first*.02-.18),2),
                              round(min(duration,(last+1)*.02+.30),2)])
            first=last=None
    if first is not None and last-first+1>=10:
        spans.append([round(max(0,first*.02-.18),2),
                      round(min(duration,(last+1)*.02+.30),2)])
    return spans,duration

def text_ranges(spans):
    return ",".join(f"{a:.2f}-{b:.2f}" for a,b in spans)

if __name__=="__main__":
    import sys
    settings=json.loads((Path(__file__).resolve().parent/"client.json").read_text(encoding="utf-8-sig"))
    for path in sys.argv[1:]:
        segments,duration=detect_file(Path(path),settings["ffmpeg_path"])
        print(path, "duration",duration,"speech",segments,flush=True)