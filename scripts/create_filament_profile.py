#!/usr/bin/env python3
"""
Create a new OrcaSlicer filament profile in the user profile directory,
inheriting from an existing system or user filament and overriding only what differs.

Usage:
  create_filament_profile.py --name "My PLA Silk Red" --inherits "Flashforge PLA Basic" \
      --set nozzle_temperature=210 --set nozzle_temperature_initial_layer=215 \
      --set filament_max_volumetric_speed=12

  create_filament_profile.py --list-bases [--vendor Flashforge]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import orca_slice as orca  # noqa: E402


def create_filament_profile(name: str, inherits: str, overrides: dict) -> Path:
    orca._resolve_profile_path("filament", inherits)

    profile = {
        "type": "filament",
        "from": "User",
        "inherits": inherits,
        "name": name,
        "filament_settings_id": [name],
    }
    profile.update(overrides)

    dest_dir = orca.USER_PROFILES_DIR / "filament"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{name}.json"
    dest.write_text(json.dumps(profile, indent=4))
    return dest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name")
    parser.add_argument("--inherits")
    parser.add_argument("--set", action="append", default=[], dest="overrides",
                         help="key=value override, repeatable")
    parser.add_argument("--list-bases", action="store_true")
    parser.add_argument("--vendor")
    args = parser.parse_args()

    if args.list_bases:
        print(json.dumps(orca.list_filaments(args.vendor), indent=2))
        return

    if not args.name or not args.inherits:
        parser.error("--name and --inherits are required (or use --list-bases)")

    overrides = dict(kv.split("=", 1) for kv in args.overrides)
    dest = create_filament_profile(args.name, args.inherits, overrides)
    print(json.dumps({"created": str(dest), "name": args.name, "inherits": args.inherits}, indent=2))


if __name__ == "__main__":
    main()
