"""Run Megan's read-only discovery workers together."""
from __future__ import annotations

import logging
import signal
import subprocess
import sys
import time

LOG = logging.getLogger("megan.runner")
WORKERS = ("megan_watcher", "megan_research", "social_discovery")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    children: list[subprocess.Popen] = []
    stopping = False

    def stop(*_args):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        for module in WORKERS:
            LOG.info("Starting %s", module)
            children.append(subprocess.Popen([sys.executable, "-m", module]))
        while not stopping:
            stopped = next((child for child in children if child.poll() is not None), None)
            if stopped is not None:
                LOG.error("A Megan worker exited with status %s", stopped.returncode)
                return int(stopped.returncode or 1)
            time.sleep(1)
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
