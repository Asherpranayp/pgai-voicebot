"""
One command to run the whole thing: starts the agent worker, places each
scenario's call one after another (waiting for each call to finish and its
recording to be saved), then stops the worker.

Usage:
    python -m app.run_calls                          # every scenario
    python -m app.run_calls simple_scheduling insurance_question
"""
import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

from app.dispatch_call import dispatch
from app.scenarios import list_scenarios

ROOT = Path(__file__).resolve().parent.parent
RECORDINGS = ROOT / "recordings"
TRANSCRIPTS = ROOT / "transcripts"
CALL_TIMEOUT_S = 420  # the agent caps a call at 5 min; allow time to save


def _wait_for_call(room: str) -> bool:
    """A call is finished once its mixed MP3 is written (or, if audio failed,
    once its transcript exists and nothing more has arrived for a while)."""
    deadline = time.time() + CALL_TIMEOUT_S
    transcript_seen_at = None
    while time.time() < deadline:
        if (RECORDINGS / f"{room}.mp3").exists():
            return True
        if (TRANSCRIPTS / f"{room}.txt").exists():
            transcript_seen_at = transcript_seen_at or time.time()
            if time.time() - transcript_seen_at > 30:
                return True
        time.sleep(3)
    return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenarios", nargs="*", help="scenario ids (default: all)")
    args = parser.parse_args()
    scenario_ids = args.scenarios or [s.id for s in list_scenarios()]

    log_path = ROOT / "agent_worker.log"
    print(f"Starting agent worker (log: {log_path})")
    worker = subprocess.Popen(
        [sys.executable, "-m", "app.agent", "start"],
        cwd=ROOT, stdout=open(log_path, "w"), stderr=subprocess.STDOUT,
    )
    try:
        time.sleep(12)  # let the worker register with LiveKit
        if worker.poll() is not None:
            sys.exit(f"Worker exited early; see {log_path}")

        results = []
        for i, sid in enumerate(scenario_ids, 1):
            print(f"\n[{i}/{len(scenario_ids)}] {sid}")
            room = asyncio.run(dispatch(sid))
            ok = _wait_for_call(room)
            results.append((sid, room, ok))
            print(f"  -> {'done' if ok else 'TIMED OUT'}: {room}")
            time.sleep(5)  # small gap so calls never overlap on the test line

        print("\nSummary:")
        for sid, room, ok in results:
            print(f"  {'OK ' if ok else 'ERR'} {sid:<28} recordings/{room}.mp3")
    finally:
        worker.terminate()
        worker.wait(timeout=15)


if __name__ == "__main__":
    main()
