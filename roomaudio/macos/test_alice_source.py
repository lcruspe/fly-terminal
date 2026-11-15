"""Source lifecycle must not affect Mate or start without a listener."""
import threading
import time
import unittest
from unittest.mock import patch

from alice_source import AliceSource
from live_relay import LiveHub

class FakeAlice(AliceSource):
    def __init__(self):
        super().__init__({}, '/unused')
        self.spawned=threading.Event()
        self.allow_audio=threading.Event()
        self.finished=threading.Event()
    def _run(self, stop):
        generation=self.hub.begin()
        self.spawned.set()
        while not self.allow_audio.wait(.01):
            if stop.is_set(): break
        if not stop.is_set(): self.hub.publish(generation,b'ID3sample')
        with self.lock: self.lock.notify_all()
        stop.wait(2)
        self.hub.end(generation)
        with self.lock: self.running=False;self.lock.notify_all()
        self.finished.set()

class AliceSourceTests(unittest.TestCase):
    def test_zero_listeners_never_starts(self):
        source=FakeAlice()
        self.assertFalse(source.status()['online'])
        self.assertIsNone(source.worker)

    def test_first_audio_required_and_stop_after_last_listener(self):
        source=FakeAlice(); ready=[]
        t=threading.Thread(target=lambda:ready.append(source.acquire(timeout=2)));t.start()
        self.assertTrue(source.spawned.wait(1));self.assertFalse(source.status()['online'])
        source.allow_audio.set();t.join(2)
        self.assertEqual(ready,[True]);self.assertTrue(source.acquire(timeout=1))
        source.release();self.assertFalse(source.stop_event.is_set())
        source.release();self.assertTrue(source.finished.wait(2));self.assertFalse(source.status()['online'])

    def test_cancelled_listener_stops_without_audio(self):
        source=FakeAlice()
        self.assertFalse(source.acquire(timeout=1,cancelled=lambda:True))
        self.assertTrue(source.finished.wait(2))
        self.assertEqual(source.status()['listeners'],0)

    def test_alice_hub_does_not_replace_mate(self):
        source=FakeAlice();mate=LiveHub();self.assertTrue(mate.ingest_packet('a'*32,0,b'mate'))
        generation,seq=mate.subscribe();t=threading.Thread(target=lambda:source.acquire(timeout=2));t.start()
        source.spawned.wait(1);source.allow_audio.set();t.join(2)
        self.assertEqual(mate.read(generation,seq,wait=0)[0][0][1],b'mate')
        source.release();mate.unsubscribe()

if __name__=='__main__':unittest.main()
