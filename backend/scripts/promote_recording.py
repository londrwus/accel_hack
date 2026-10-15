"""Make a live run the new demo recording, on purpose.

Live runs are saved to data/cache/replay/live/<fund>-<run_id>.jsonl and never replace the recording that
DEMO_MODE=replay plays (data/cache/replay/<fund>.jsonl). Run this when a rehearsal went well:

    cd backend
    python -m uv run python scripts/promote_recording.py --list                # show live recordings
    python -m uv run python scripts/promote_recording.py localglobe            # newest live run of a fund
    python -m uv run python scripts/promote_recording.py run_localglobe_...    # a run id
    python -m uv run python scripts/promote_recording.py path/to/file.jsonl [--fund localglobe]

The previous recording is kept next to it as <fund>.jsonl.bak.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import runs  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Copy a live recording to the replay slot for its fund.")
    ap.add_argument("source", nargs="?", help="a .jsonl file, a run id, or a fund id (its newest live run)")
    ap.add_argument("--fund", help="fund id to promote it as (default: read from the file name)")
    ap.add_argument("--list", action="store_true", help="list live recordings and stop")
    args = ap.parse_args(argv)

    if args.list or not args.source:
        files = runs.list_live_recordings()
        if not files:
            print("No live recordings yet.")
        for f in files:
            print(f.name)
        return 0
    try:
        dest = runs.promote_recording(args.source, args.fund)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Promoted. Replay now plays {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
