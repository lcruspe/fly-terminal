"""On-demand, bounded live capture from the dedicated Alice SSH helper."""
import datetime as dt
import os
from pathlib import Path
import subprocess
import json
import sys
import threading
import time

from live_relay import LiveHub

class AliceSource:
    def __init__(self, config, archive):
        self.config=config
        self.archive=Path(archive)/'_alice'
        self.hub=LiveHub()
        self.lock=threading.Condition()
        self.consumers=0
        self.worker=None
        self.stop_event=None
        self.error=None
        self.running=False

    def status(self):
        with self.lock:
            return {'online':self._ready(), 'connecting':self.running and not self._ready(),
                    'listeners':self.consumers, 'error':self.error}

    def _ready(self):
        status=self.hub.status()
        return status["online"] and status["buffer_bytes"] > 0

    def acquire(self, timeout=50, cancelled=None):
        with self.lock:
            self.consumers+=1
            if self.worker is None or not self.worker.is_alive():
                self.error=None
                self.running=True
                self.stop_event=threading.Event()
                self.worker=threading.Thread(target=self._run,args=(self.stop_event,),daemon=True)
                self.worker.start()
            deadline=time.monotonic()+timeout
            while not self._ready() and self.running:
                remaining=deadline-time.monotonic()
                if remaining<=0 or (cancelled and cancelled()): break
                self.lock.wait(min(remaining,0.5))
            if self._ready(): return True
            self.consumers-=1
            if not self.consumers and self.stop_event: self.stop_event.set()
            return False

    def release(self):
        with self.lock:
            self.consumers=max(0,self.consumers-1)
            if not self.consumers and self.stop_event: self.stop_event.set()

    def _run(self, stop):
        ssh=encoder=guard=watch_thread=None
        generation=self.hub.begin()
        try:
            cfg=self.config.get('alice_source',{})
            host=cfg.get('host','');key=cfg.get('identity_file','');known=cfg.get('known_hosts','')
            if not host or not key or not known or '"' in known or '\n' in known: raise RuntimeError('Источник Алиса не настроен')
            if not os.path.ismount('/Volumes/WD'): raise RuntimeError('Диск архива недоступен')
            day=dt.datetime.now().strftime('%Y%m%d');folder=self.archive/day;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
            ssh_cmd=['/usr/bin/ssh','-T','-i',key,'-o','IdentitiesOnly=yes','-o','BatchMode=yes',
                 '-o','StrictHostKeyChecking=yes','-o','UserKnownHostsFile="'+known+'"','-o','ConnectTimeout=8',
                 '-o','ServerAliveInterval=5','-o','ServerAliveCountMax=2','-p','2222','root@'+host]
            guard=subprocess.Popen([sys.executable,str(Path(__file__).with_name('alice_guard.py'))],
                                   stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            guard.stdin.write((json.dumps(ssh_cmd+['/data/opt/roomaudio-alice/profile.sh stop'])+'\n').encode())
            guard.stdin.flush()
            ssh=subprocess.Popen(ssh_cmd+['exec /data/opt/roomaudio-alice/profile.sh stream'],
                                 stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            encoder=subprocess.Popen(['/opt/homebrew/bin/ffmpeg','-hide_banner','-loglevel','error',
                '-probesize','32','-analyzeduration','0','-f','s16le','-ar','16000','-ac','1','-i','pipe:0',
                '-map','0:a','-c:a','libmp3lame','-b:a','64k','-flush_packets','1','-f','mp3','pipe:1',
                '-map','0:a','-c:a','libmp3lame','-b:a','64k','-f','segment','-segment_time','15',
                '-segment_atclocktime','1','-strftime','1','-reset_timestamps','1',str(folder/'%Y%m%dT%H%M%S.mp3')],
                stdin=ssh.stdout,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            ssh.stdout.close()
            def watcher():
                stop.wait()
                if guard and guard.stdin:
                    try: guard.stdin.close()
                    except OSError: pass
                if guard:
                    try: guard.wait(timeout=22)
                    except subprocess.TimeoutExpired: guard.kill(); guard.wait()
                for process in (ssh,encoder):
                    if process and process.poll() is None: process.terminate()
            watch_thread=threading.Thread(target=watcher,daemon=True)
            watch_thread.start()
            while not stop.is_set():
                chunk=os.read(encoder.stdout.fileno(),8192)
                if not chunk: break
                self.hub.publish(generation,chunk)
                with self.lock: self.lock.notify_all()
                if dt.datetime.now().strftime('%Y%m%d')!=day: break
            if not stop.is_set(): raise RuntimeError('Поток Алисы прерван')
        except (OSError,RuntimeError) as exc:
            with self.lock: self.error=str(exc)
        finally:
            stop.set()
            if watch_thread: watch_thread.join(timeout=24)
            elif guard and guard.stdin:
                try: guard.stdin.close()
                except OSError: pass
            if guard:
                try: guard.wait(timeout=22)
                except subprocess.TimeoutExpired: guard.kill();guard.wait()
            for process in (ssh,encoder):
                if process and process.poll() is None:
                    process.terminate()
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill();process.wait()
            self.hub.end(generation)
            with self.lock: self.running=False;self.lock.notify_all()
