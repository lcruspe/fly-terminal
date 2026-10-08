"""Exercise lock transitions without importing platform-specific capture APIs."""
import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "macos/fly-mac-streamer.py"
TREE = ast.parse(SOURCE.read_text())
METHODS = {"monitor_lock_state", "_effective_display_name"}


class StreamerLockStateTests(unittest.TestCase):
    def test_unlock_is_reported_for_desktop_and_browser_clients(self):
        methods = [node for cls in TREE.body if isinstance(cls, ast.ClassDef)
                   for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and node.name in METHODS]
        for follow_main in (False, True):
            with self.subTest(follow_main_when_locked=follow_main):
                events = []
                state = SimpleNamespace(
                    follow_main_when_locked=follow_main, screen_locked=True,
                    running=True, requested_display_name="Fly Remote",
                    target_display_name="", clients={},
                )

                async def sleep(_seconds):
                    state.running = False

                async def broadcast(message):
                    events.append(message)

                namespace = {"asyncio": SimpleNamespace(sleep=sleep),
                             "logger": logging.getLogger(__name__),
                             "is_screen_locked": lambda: False}
                exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), "exec"), namespace)
                state._effective_display_name = lambda: namespace["_effective_display_name"](state)
                state.broadcast_json = broadcast
                asyncio.run(namespace["monitor_lock_state"](state))
                self.assertFalse(state.screen_locked)
                self.assertEqual(events[0]["state"], "host_unlocked")
                self.assertEqual(state.target_display_name, "Fly Remote")


if __name__ == "__main__":
    unittest.main()
