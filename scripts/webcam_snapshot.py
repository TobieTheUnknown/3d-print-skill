#!/usr/bin/env python3
"""
Grab a JPEG snapshot from the printer's µStreamer webcam.

Usage:
  webcam_snapshot.py [--outdir DIR] [--label mylabel]

Prints the path to the saved JPEG on stdout.
"""
import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
CFG = json.loads(CONFIG_PATH.read_text())["printer"]
SNAPSHOT_URL = f"http://{CFG['host']}:{CFG['webcam_port']}{CFG['webcam_snapshot_path']}"


def snapshot(outdir: str, label: str = None) -> Path:
    out_dir = Path(outdir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"snapshot-{ts}{'-' + label if label else ''}.jpg"
    dest = out_dir / name
    subprocess.run(["curl", "-sS", "-m", "10", SNAPSHOT_URL, "-o", str(dest)], check=True)
    if dest.stat().st_size < 1000:
        print(f"Warning: snapshot suspiciously small ({dest.stat().st_size} bytes) — webcam may be offline", file=sys.stderr)
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--outdir", default=str(Path.home() / "Documents/3D-Prints/_monitoring"))
    parser.add_argument("--label")
    args = parser.parse_args()
    dest = snapshot(args.outdir, args.label)
    print(str(dest))


if __name__ == "__main__":
    main()
