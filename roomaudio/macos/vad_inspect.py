"""Conservative voice-presence checker for a single archived MP3.

Runs in a dedicated Python 3.9 venv with webrtcvad.
Emits exactly one JSON object. Never classifies uncertain loud audio as no voice.
"""
import json
import math
import pathlib
import subprocess
import sys
import webrtcvad
import numpy as np

FFMPEG="/opt/homebrew/bin/ffmpeg"
RATE=16000
FRAME=320  # 20 ms
def analyze(path):
    cmd=[FFMPEG,"-hide_banner","-nostdin","-loglevel","error",
         "-i",str(path),"-af","highpass=f=90,lowpass=f=7500",
         "-ac","1","-ar",str(RATE),"-f","s16le","pipe:1"]
    r=subprocess.run(cmd,capture_output=True,timeout=23)
    if r.returncode!=0:
        raise RuntimeError("decode failed: "+r.stderr.decode(errors="replace")[-130:])
    samples=np.frombuffer(r.stdout,dtype="<i2")
    if len(samples)<RATE:
        return {"status":"uncertain","reason":"too_short","mean_db":None,"peak_db":None}
    pcm=samples.astype(np.float64)/32768.0
    rms=float(np.sqrt(np.mean(pcm*pcm)))
    peak=float(np.max(np.abs(pcm)))
    db=lambda x:round(20*math.log10(max(x,1e-12)),1)
    avg=db(rms);maximum=db(peak)
    # Detect speech with the lenient WebRTC VAD setting as well as mode 2.
    # A few isolated false positives in ambient noise do not establish speech.
    count=len(samples)//FRAME
    frames=[samples[i*FRAME:(i+1)*FRAME].tobytes() for i in range(count)]
    flags=[]
    for mode in (0,1,2):
        classifier=webrtcvad.Vad(mode)
        active=[classifier.is_speech(f,RATE) for f in frames]
        hits=sum(active)
        # Required continuous run to protect even brief genuine utterances.
        longest=run=0
        for present in active:
            run=run+1 if present else 0
            longest=max(longest,run)
        flags.append((hits,longest))
    result={"mean_db":avg,"peak_db":maximum,"speech_frames":[x[0] for x in flags],
            "longest_voice_frames":[x[1] for x in flags],"duration":round(len(samples)/RATE,2)}
    if avg<=-68 and maximum<=-50:
        result.update(status="no_voice",reason="digital_silence")
    elif (all(hits<=2 and longest<=2 for hits,longest in flags)
          and avg<=-48 and maximum<=-34):
        result.update(status="no_voice",reason="no_vad_and_very_quiet")
    elif any(longest>=6 for _,longest in flags) or any(hits>=20 for hits,_ in flags):
        result.update(status="voice",reason="voice_detected")
    else:
        result.update(status="uncertain",reason="ambiguous_audio")
    return result
try:
    print(json.dumps(analyze(pathlib.Path(sys.argv[1]))))
except Exception as exc:
    print(json.dumps({"status":"error","reason":str(exc)[:180]}))
