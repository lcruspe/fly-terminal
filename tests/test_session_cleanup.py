import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "session-control.py"
spec = importlib.util.spec_from_file_location("session_control", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SessionCleanupTests(unittest.TestCase):
    def test_prunes_only_detached_expired_fly_terminal_sessions(self):
        listing = "\n".join([
            "fly-terminal-old|0|1000",
            "fly-terminal-recent|0|9500",
            "fly-terminal-live|1|1000",
            "personal-work|0|1000",
        ])
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if command[:2] == ["tmux", "list-sessions"]:
                return subprocess.CompletedProcess(command, 0, stdout=listing, stderr="")
            if command[:2] == ["tmux", "kill-session"]:
                return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
            raise AssertionError(command)

        with patch.object(module, "SESSION_IDLE_TTL_MINUTES", 120, create=True), patch.object(module.subprocess, "run", side_effect=fake_run):
            killed = module.prune_stale_tmux_sessions(now_epoch=10_000)

        self.assertEqual(killed, 1)
        self.assertIn(["tmux", "kill-session", "-t", "fly-terminal-old"], calls)
        self.assertNotIn(["tmux", "kill-session", "-t", "personal-work"], calls)

    def test_cleanup_disabled_when_ttl_is_zero(self):
        with patch.object(module, "SESSION_IDLE_TTL_MINUTES", 0, create=True), patch.object(module.subprocess, "run") as run_mock:
            self.assertEqual(module.prune_stale_tmux_sessions(now_epoch=10_000), 0)
        run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
