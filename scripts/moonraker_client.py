#!/usr/bin/env python3
"""
Moonraker REST client for the Flashforge AD5M (Klipper mod).
No third-party deps: shells out to curl, parses JSON with stdlib.

Usage:
  moonraker_client.py upload <gcode_path> [--start]
  moonraker_client.py start <filename>
  moonraker_client.py status
  moonraker_client.py pause
  moonraker_client.py resume
  moonraker_client.py cancel
  moonraker_client.py list
  moonraker_client.py delete <filename>
  moonraker_client.py history [--limit 10]
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
CFG = json.loads(CONFIG_PATH.read_text())["printer"]
BASE = f"http://{CFG['host']}:{CFG['moonraker_port']}"


def _curl_json(method: str, path: str, **kwargs) -> dict:
    cmd = ["curl", "-sS", "-m", "15", "-X", method, f"{BASE}{path}"]
    if "json_body" in kwargs and kwargs["json_body"] is not None:
        cmd += ["-H", "Content-Type: application/json", "-d", json.dumps(kwargs["json_body"])]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    if not result.stdout.strip():
        return {}
    return json.loads(result.stdout)


def upload(gcode_path: str, start: bool = False) -> dict:
    path = Path(gcode_path).expanduser()
    cmd = ["curl", "-sS", "-m", "60", "-X", "POST", f"{BASE}/server/files/upload",
           "-F", f"file=@{path};filename={path.name}"]
    if start:
        cmd += ["-F", "print=true"]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def start_print(filename: str) -> dict:
    return _curl_json("POST", f"/printer/print/start?filename={filename}")


def status() -> dict:
    objects = "print_stats&display_status&virtual_sdcard&extruder&heater_bed"
    data = _curl_json("GET", f"/printer/objects/query?{objects}")
    result = data.get("result", {}).get("status", {})
    ps = result.get("print_stats", {})
    vsd = result.get("virtual_sdcard", {})
    ds = result.get("display_status", {})
    return {
        "state": ps.get("state"),
        "filename": ps.get("filename"),
        "print_duration_s": ps.get("print_duration"),
        "progress_pct": round((ds.get("progress") or vsd.get("progress") or 0) * 100, 1),
        "current_layer": (ps.get("info") or {}).get("current_layer"),
        "total_layer": (ps.get("info") or {}).get("total_layer"),
        "extruder_temp": result.get("extruder", {}).get("temperature"),
        "extruder_target": result.get("extruder", {}).get("target"),
        "bed_temp": result.get("heater_bed", {}).get("temperature"),
        "bed_target": result.get("heater_bed", {}).get("target"),
        "message": ps.get("message"),
    }


def pause() -> dict:
    return _curl_json("POST", "/printer/print/pause")


def resume() -> dict:
    return _curl_json("POST", "/printer/print/resume")


def cancel() -> dict:
    return _curl_json("POST", "/printer/print/cancel")


def list_files() -> dict:
    return _curl_json("GET", "/server/files/list?root=gcodes")


def delete_file(filename: str) -> dict:
    return _curl_json("DELETE", f"/server/files/gcodes/{filename}")


def history(limit: int = 10) -> dict:
    return _curl_json("GET", f"/server/history/list?limit={limit}&order=desc")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_up = sub.add_parser("upload")
    p_up.add_argument("gcode_path")
    p_up.add_argument("--start", action="store_true")
    p_up.set_defaults(func=lambda a: upload(a.gcode_path, a.start))

    p_st = sub.add_parser("start")
    p_st.add_argument("filename")
    p_st.set_defaults(func=lambda a: start_print(a.filename))

    sub.add_parser("status").set_defaults(func=lambda a: status())
    sub.add_parser("pause").set_defaults(func=lambda a: pause())
    sub.add_parser("resume").set_defaults(func=lambda a: resume())
    sub.add_parser("cancel").set_defaults(func=lambda a: cancel())
    sub.add_parser("list").set_defaults(func=lambda a: list_files())

    p_del = sub.add_parser("delete")
    p_del.add_argument("filename")
    p_del.set_defaults(func=lambda a: delete_file(a.filename))

    p_hist = sub.add_parser("history")
    p_hist.add_argument("--limit", type=int, default=10)
    p_hist.set_defaults(func=lambda a: history(a.limit))

    args = parser.parse_args()
    print(json.dumps(args.func(args), indent=2))


if __name__ == "__main__":
    main()
