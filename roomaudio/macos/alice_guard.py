"""Restore the station when the RoomAudio server loses its capture lease.

The server owns the only write end of stdin. EOF therefore also arrives if the
server crashes or is killed, independently of its cleanup threads.
"""
import json
import subprocess
import sys


def main():
    try:
        command = json.loads(sys.stdin.buffer.readline())
        if not isinstance(command, list) or not command or any(not isinstance(x, str) for x in command):
            return 2
        # Keep the lease open until the capture worker ends or its parent dies.
        while sys.stdin.buffer.read(4096):
            pass
        subprocess.run(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=20, check=False)
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired):
        # The station's separate watchdog is the final fallback.
        return 1


if __name__ == '__main__':
    sys.exit(main())
