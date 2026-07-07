#!/usr/bin/env python3
"""
Create a new OrcaSlicer printer (machine) profile in the user profile directory,
inheriting from an existing system or user profile and overriding only what differs.

Usage:
  create_printer_profile.py --name "My Custom AD5M" --inherits "Flashforge Adventurer 5M Pro 0.4 Nozzle" \
      --set retraction_length=0.8 --set machine_max_speed_x=200

  create_printer_profile.py --list-bases [--vendor Flashforge]   # show valid --inherits targets
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import orca_slice as orca  # noqa: E402


def create_printer_profile(name: str, inherits: str, overrides: dict) -> Path:
    # Validates the base profile exists (raises FileNotFoundError otherwise)
    orca._resolve_profile_path("machine", inherits)

    profile = {
        "type": "machine",
        "from": "User",
        "inherits": inherits,
        "name": name,
        "printer_settings_id": name,
    }
    profile.update(overrides)

    dest_dir = orca.USER_PROFILES_DIR / "machine"
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
        print(json.dumps(orca.list_printers(args.vendor), indent=2))
        return

    if not args.name or not args.inherits:
        parser.error("--name and --inherits are required (or use --list-bases)")

    overrides = dict(kv.split("=", 1) for kv in args.overrides)
    dest = create_printer_profile(args.name, args.inherits, overrides)
    print(json.dumps({"created": str(dest), "name": args.name, "inherits": args.inherits}, indent=2))


if __name__ == "__main__":
    main()
