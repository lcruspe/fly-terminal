#!/usr/bin/env python
"""RoomAudio: capture real Intel Smart Sound microphone via PortAudio WDM-KS."""
import argparse
import json
import logging
from pathlib import Path
import queue
import subprocess
import time

import numpy as np
import sounddevice as sd

BASE=Path(__file__).resolve().parent
CONFIG=json.loads((BASE/"client.json").read_text(encoding="utf-8-sig"))
SAMPLE_RATE=48000
CHANNELS=4
LOG=BASE/"capture-ks.log"
logging.basicConfig(filename=str(LOG),level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s",encoding="utf-8")

def select_device():
    apis=sd.query_hostapis()
    found=[]
    for n,d in enumerate(sd.query_devices()):
        if apis[d["hostapi"]]["name"]!="Windows WDM-KS":
            continue
        if int(d["max_input_channels"])!=4 or int(d["default_samplerate"])!=SAMPLE_RATE:
            continue
        label=d["name"].lower()
        if "microphone" not in label and "микрофон" not in label:
            continue
        priority=0 if "микрофонов 2" in label else 1
        found.append((priority,n,d["name"]))
    for _,device,name in sorted(found):
        try:
            # sd.rec uses the callback API (WDM-KS does NOT support blocking reads).
            sample=sd.rec(SAMPLE_RATE//2,samplerate=SAMPLE_RATE,channels=4,device=device,
                          dtype="float32",blocking=True)
            rms=float(np.sqrt(np.mean(sample*sample,dtype=np.float64)))
            if np.isfinite(rms) and rms>0.00001:
                logging.info("Selected WDM-KS device=%s (%s), RMS=%f",device,name,rms)
                print("Selected WDM-KS pin",device,"RMS",round(rms,6),flush=True)
                return device
            logging.warning("WDM-KS input %s has no PCM signal, RMS %.8f",device,rms)
        except Exception as exc:
            logging.warning("WDM-KS input %s unavailable: %s",device,exc)
    raise RuntimeError("No usable WDM-KS microphone array pin was found")

def run(outdir,seconds=None):
    outdir.mkdir(parents=True,exist_ok=True)
    chosen=select_device()
    commands=[
      CONFIG["ffmpeg_path"],"-hide_banner","-nostdin","-loglevel","error",
      "-f","f32le","-ar","48000","-ac","1","-i","pipe:0",
      "-vn","-ar","48000","-c:a","libmp3lame","-b:a","96k",
      "-f","segment","-segment_time","15","-reset_timestamps","1",
      "-strftime","1",str(outdir/"%Y%m%dT%H%M%S.mp3")
    ]
    buffers=queue.Queue(maxsize=160)
    errors=[0]
    def on_audio(indata,frames,time_info,status):
        if status:
            logging.warning("PortAudio: %s",status)
        mono=np.mean(indata,axis=1,dtype=np.float32)
        try:
            buffers.put_nowait(np.ascontiguousarray(mono,dtype="<f4").tobytes())
        except queue.Full:
            errors[0]+=1

    with open(LOG,"a",encoding="utf-8") as stderr:
        ff=subprocess.Popen(commands,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=stderr,bufsize=0)
        start=time.monotonic()
        written=0
        try:
            with sd.InputStream(device=chosen,samplerate=SAMPLE_RATE,channels=CHANNELS,
                                dtype="float32",callback=on_audio,blocksize=0,latency="high"):
                logging.info("Recording began; ffmpeg PID %s, pin %s, folder %s",ff.pid,chosen,outdir)
                print("WDM-KS microphone capturing; FFmpeg PID",ff.pid,flush=True)
                while seconds is None or time.monotonic()-start<seconds:
                    try:
                        payload=buffers.get(timeout=4)
                    except queue.Empty:
                        raise RuntimeError("No microphone data received for 4 seconds")
                    ff.stdin.write(payload)
                    written+=len(payload)
                    if ff.poll() is not None:
                        raise RuntimeError("FFmpeg unexpectedly stopped: "+str(ff.returncode))
        finally:
            if ff.stdin:
                try:ff.stdin.close()
                except OSError:pass
            try:ff.wait(timeout=12)
            except subprocess.TimeoutExpired:
                ff.terminate()
                try:ff.wait(timeout=5)
                except subprocess.TimeoutExpired:ff.kill()
            logging.info("Capture stopped, sent_pcm_bytes=%d, dropped_buffers=%d, ffmpeg_rc=%s",
                         written,errors[0],ff.returncode)
            print("Audio bytes",written,"queue drops",errors[0],"ffmpeg exit",ff.returncode,flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--seconds",type=int,default=None)
    p.add_argument("--output-dir",type=Path,default=Path(CONFIG["buffer"]))
    a=p.parse_args()
    run(a.output_dir,a.seconds)