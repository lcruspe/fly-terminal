"""RoomAudio capture supervisor. Remotely selectable: continuous, voice-only, off."""
from pathlib import Path
import json
import logging
import subprocess
import sys
import time
from urllib.parse import urlencode
from urllib.request import Request,urlopen

ROOT=Path(__file__).resolve().parent
CONF=json.loads((ROOT/"client.json").read_text(encoding="utf-8-sig"))
SERVER=CONF["server"].rstrip("/")
PYTHON=sys.executable
LOG=ROOT/"capture-manager.log"
logging.basicConfig(filename=str(LOG),level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",encoding="utf-8")
VALID={"continuous","voice","off"}

class Manager:
    def __init__(self):
        self.proc=None
        self.active="starting"
        self.last_ok=0.0
        self.last_start=0.0
        self.child_output=None

    def poll(self):
        uri=SERVER+"/client/recording-mode?"+urlencode({"active":self.active})
        req=Request(uri,headers={"X-Ingest-Key":CONF["ingest_key"]})
        with urlopen(req,timeout=6) as response:
            doc=json.load(response)
        selected=doc.get("mode")
        if selected not in VALID:
            raise ValueError("Unknown mode from server")
        self.last_ok=time.monotonic()
        return selected

    def stop(self):
        proc=self.proc
        self.proc=None
        if proc is None:return
        if proc.poll() is None:
            # Kill the complete capture tree, including FFmpeg, to free the microphone.
            subprocess.run(["taskkill.exe","/PID",str(proc.pid),"/T","/F"],
                           capture_output=True,text=True,timeout=12)
            try:proc.wait(timeout=6)
            except subprocess.TimeoutExpired:proc.kill()
        logging.info("Capture subprocess stopped (PID=%d, exit=%s)",proc.pid,proc.poll())
        if self.child_output is not None:
            self.child_output.close()
            self.child_output=None

    def start(self,mode):
        self.stop()
        if mode=="off":
            self.active="off"
            print("Microphone capture DISABLED (no active microphone process)",flush=True)
            logging.info("Capture is OFF: no microphone input opened")
            return
        script="capture_ks.py" if mode=="continuous" else "capture_voice.py"
        outfile=ROOT/"capture-managed-output.log"
        self.child_output=outfile.open("a",encoding="utf-8")
        self.proc=subprocess.Popen(
           [PYTHON,"-u",str(ROOT/script)],
           stdin=subprocess.DEVNULL,stdout=self.child_output,stderr=subprocess.STDOUT,
           cwd=str(ROOT),creationflags=subprocess.CREATE_NO_WINDOW)
        self.active=mode
        self.last_start=time.monotonic()
        logging.info("Started mode %s via PID %d",mode,self.proc.pid)
        print("Mode",mode,"running PID",self.proc.pid,flush=True)

    def loop(self):
        print("RoomAudio capture manager online",flush=True)
        while True:
            try:
                requested=self.poll()
                if requested!=self.active:
                    self.start(requested)
                elif self.proc is not None and self.proc.poll() is not None:
                    self.stop()
                    self.active="starting"
                    if time.monotonic()-self.last_start >= 6:
                        self.start(requested)
                    else:
                        logging.warning("Capture exited too quickly; retry pending")
                elif requested=="off" and self.proc is not None:
                    self.stop()
                time.sleep(3)
            except KeyboardInterrupt:
                self.stop()
                raise
            except Exception as exc:
                logging.error("Mode control unavailable: %s",exc)
                # Fail closed: no uncontrolled microphone activity when remote control is lost.
                if time.monotonic()-self.last_ok>15:
                    self.stop()
                    self.active="error"
                time.sleep(3)

if __name__=="__main__":
    manager=Manager()
    try:manager.loop()
    finally:manager.stop()