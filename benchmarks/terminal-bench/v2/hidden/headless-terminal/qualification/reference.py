import subprocess
import time
import uuid
from pathlib import Path

from base_terminal import BaseTerminal


class HeadlessTerminal(BaseTerminal):
    def __init__(self):
        self._session_id = str(uuid.uuid4())
        subprocess.run(
            [
                "tmux",
                "new-session",
                "-d",
                "-s",
                self._session_id,
                "bash",
                "--noprofile",
                "--rcfile",
                str(Path.home() / ".bashrc"),
                "-i",
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def send_keystrokes(self, keystrokes: str, wait_sec: float = 0.0) -> None:
        subprocess.run(
            ["tmux", "send-keys", "-t", self._session_id, keystrokes],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(wait_sec)
