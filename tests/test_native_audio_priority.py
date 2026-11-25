import ast
import pathlib
import time
import unittest
from collections import deque
from types import SimpleNamespace
from dataclasses import dataclass

source = pathlib.Path(__file__).resolve().parents[1] / "macos/fly-mac-streamer.py"
tree = ast.parse(source.read_text())
server = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "StreamServer")
methods = [n for n in server.body if isinstance(n, ast.FunctionDef) and n.name in ("_queue_audio", "_next_outbound")]
message = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "OutboundMessage")
namespace = {"time": time, "dataclass": dataclass}
exec(compile(ast.Module(body=[message]+methods,type_ignores=[]),str(source),"exec"),namespace)
queue_audio=namespace["_queue_audio"]
next_outbound=namespace["_next_outbound"]
Message=namespace["OutboundMessage"]

class AudioPriorityTests(unittest.TestCase):
    def state(self, priority):
        return SimpleNamespace(media_priority=priority,audio_mode="both",queue=deque(),audio_dropped=0,queue_event=SimpleNamespace(set=lambda:None))
    def test_audio_bypasses_video_without_reordering_audio(self):
        state=self.state("audio")
        state.queue.append(Message("video",b"v",0))
        queue_audio(None,state,b"a")
        queue_audio(None,state,b"b")
        self.assertEqual([next_outbound(None,state).payload for _ in range(3)],[b"a",b"b",b"v"])
    def test_video_priority_fifo_and_bounded_audio(self):
        state=self.state("video")
        state.queue.append(Message("video",b"v",0))
        for i in range(10): queue_audio(None,state,bytes([i]))
        self.assertEqual(state.audio_dropped,2)
        self.assertEqual(next_outbound(None,state).payload,b"v")
        self.assertEqual(next_outbound(None,state).payload,b"\x02")
