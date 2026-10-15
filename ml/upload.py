"""Upload the cleaned data to the Modal Volume 'bellwether-data'.

Run from the repo root after ml/prepare.py:
    PYTHONUTF8=1 python -I ml/upload.py
(PowerShell: $env:PYTHONUTF8=1; python -I ml/upload.py)
"""

from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
FILES = ["companies.csv", "investors.json", "investor_index.json"]


def main() -> None:
    vol = modal.Volume.from_name("bellwether-data", create_if_missing=True)
    with vol.batch_upload(force=True) as batch:
        for name in FILES:
            src = ROOT / "data" / name
            if not src.exists():
                raise SystemExit(f"Missing {src}. Run ml/prepare.py first.")
            batch.put_file(str(src), f"/{name}")
            print(f"put {src} -> bellwether-data:/{name} ({src.stat().st_size:,} bytes)")
    print("Volume now holds:", sorted(e.path for e in vol.listdir("/")))


if __name__ == "__main__":
    main()
