"""RoomAudio voice-only capture: native WDM-KS microphone, 15-s files only if speech detected."""
import argparse
import datetime as dt
import json
import logging
from pathlib import Path
import queue
import subprocess
import time
import numpy as np
import sounddevice as sd
from capture_ks import select_device,CONFIG,BASE,SAMPLE_RATE,CHANNELS
from speech_activity import detect_float

LOG=BASE/"capture-voice.log"
logging.basicConfig(filename=str(LOG),level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",encoding="utf-8")
BUFFER_SECONDS=15
BUFFER_FRAMES=BUFFER_SECONDS*SAMPLE_RATE

def store(samples,begin,destination):
    if samples.size < SAMPLE_RATE*2:
        return False
    spans=detect_float(samples)
    if not spans:
        logging.info("No voice %s, discarded %.1f seconds",begin,len(samples)/SAMPLE_RATE)
        return False
    name=begin.strftime("%Y%m%dT%H%M%S")+".mp3"
    outfile=destination/name
    temp=destination/(name+".pending")
    command=[
        CONFIG["ffmpeg_path"],"-hide_banner","-nostdin","-loglevel","error","-y",
        "-f","f32le","-ar","48000","-ac","1","-i","pipe:0",
        "-c:a","libmp3lame","-b:a","96k","-f","mp3",str(temp)
    ]
    try:
        result=subprocess.run(command,input=np.asarray(samples,dtype="<f4").tobytes(),
                              stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=25)
        if result.returncode or not temp.is_file() or temp.stat().st_size<1000:
            raise RuntimeError("FFmpeg encoding failed: "+result.stderr[-200:].decode(errors="replace"))
        temp.replace(outfile)
        marker=outfile.with_suffix(".speech.json")
        marker.write_text(json.dumps(spans),encoding="utf-8")
        logging.info("VOICE %s (%.2f seconds) regions=%s",name,len(samples)/SAMPLE_RATE,spans)
        print("Voice segment stored:",name,"speech windows",spans,flush=True)
        return True
    finally:
        temp.unlink(missing_ok=True)

def capture(folder,seconds=None):
    folder.mkdir(parents=True,exist_ok=True)
    device=select_device()
    buffers=queue.Queue(maxsize=180)
    overruns=[0]
    def callback(data,frames,ts,status):
        if status:logging.warning("PortAudio %s",status)
        mono=np.mean(data,axis=1,dtype=np.float32)
        try:buffers.put_nowait(np.ascontiguousarray(mono).copy())
        except queue.Full:overruns[0]+=1
    started=time.monotonic()
    parts=[]
    frames=0
    first=None
    with sd.InputStream(device=device,samplerate=SAMPLE_RATE,channels=CHANNELS,
                        dtype="float32",callback=callback,blocksize=0,latency="high"):
        logging.info("Voice-trigger recording active on WDM-KS input %d",device)
        print("WDM-KS voice-trigger mode active",flush=True)
        while seconds is None or time.monotonic()-started<seconds:
            try:
                data=buffers.get(timeout=4)
            except queue.Empty:
                raise RuntimeError("No microphone input for 4 seconds")
            if first is None:first=dt.datetime.now()
            position=0
            while position<len(data):
                take=min(BUFFER_FRAMES-frames,len(data)-position)
                parts.append(data[position:position+take])
                position+=take
                frames+=take
                if frames>=BUFFER_FRAMES:
                    chunk=np.concatenate(parts)
                    store(chunk,first,folder)
                    parts=[];frames=0;first=dt.datetime.now()
    # Finish a partial fragment on graceful stop, if it contains speech.
    if parts and first is not None and frames>=SAMPLE_RATE*2:
        store(np.concatenate(parts),first,folder)
    logging.info("Voice-trigger exited; callback overruns=%d",overruns[0])

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--seconds",type=int)
    parser.add_argument("--output-dir",type=Path,default=Path(CONFIG["buffer"]))
    o=parser.parse_args()
    capture(o.output_dir,o.seconds)