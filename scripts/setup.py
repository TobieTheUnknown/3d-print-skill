#!/usr/bin/env python3
"""
One-time (or re-run anytime) setup: probe the printer on the network, detect its firmware,
match it to the right OrcaSlicer printer profile, and write it all into config.json.

Usage:
  setup.py probe --host 192.168.1.117
      # detects Moonraker/Klipper vs Mainsail vs webcam, prints what it found

  setup.py apply --host 192.168.1.117 --model "Flashforge Adventurer 5M Pro" --nozzle 0.4 \
      [--moonraker-port 7125] [--webcam-port 8080] [--mainsail-port 4000] \
      [--default-filament "Flashforge PLA Basic"] [--default-process-quality "0.20mm Standard"] \
      [--monitoring-mode auto_analysis|screenshot_only]
      # probes + writes config.json with resolved printer/process/filament names.
      # --monitoring-mode: ask the user which one during setup, don't assume --
      #   auto_analysis    : agent visually checks each snapshot itself against the
      #                      troubleshooting dictionary (needs a vision-capable model)
      #   screenshot_only  : agent just posts snapshots + status on the configured cadence
      #                      and lets the user judge (use this for non-vision/local models)
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import orca_slice as orca  # noqa: E402

CONFIG_PATH = Path(__file__).parent.parent / "config.json"


def _get(url: str, timeout=4):
    try:
        result = subprocess.run(["curl", "-sS", "-m", str(timeout), url], capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return result.stdout
    except Exception:
        return None


def probe(host: str, moonraker_port=7125, webcam_port=8080, mainsail_port=4000) -> dict:
    findings = {"host": host, "firmware": "unknown"}

    moon = _get(f"http://{host}:{moonraker_port}/printer/info")
    if moon:
        try:
            data = json.loads(moon)["result"]
            findings["firmware"] = "klipper"
            findings["moonraker_port"] = moonraker_port
            findings["hostname"] = data.get("hostname")
            findings["klipper_software_version"] = data.get("software_version")
            findings["state"] = data.get("state")
        except (json.JSONDecodeError, KeyError):
            pass

    mainsail = _get(f"http://{host}:{mainsail_port}/", timeout=3)
    if mainsail and ("Mainsail" in mainsail or "mainsail" in mainsail):
        findings["mainsail_port"] = mainsail_port
        findings["web_ui"] = "mainsail"

    webcam = _get(f"http://{host}:{webcam_port}/state", timeout=3)
    if webcam:
        findings["webcam_port"] = webcam_port
        findings["webcam_snapshot_url"] = f"http://{host}:{webcam_port}/snapshot"
        try:
            findings["webcam_info"] = json.loads(webcam)
        except json.JSONDecodeError:
            pass

    if findings["firmware"] == "unknown":
        findings["note"] = ("No Moonraker API found on this host/port. This skill currently supports "
                             "Klipper+Moonraker printers only (e.g. flashforge_ad5m_klipper_mod). "
                             "If this printer runs stock Flashforge firmware, network upload/monitoring "
                             "here will not work — slicing still works, but printing/monitoring must be done manually.")

    return findings


def resolve_printer_profile(model: str, nozzle: str) -> dict:
    printers = orca.list_printers()
    model_norm = model.lower().replace("flashforge", "").strip()
    candidates = [p for p in printers if model_norm in p["name"].lower() and f"{nozzle} nozzle" in p["name"].lower()]
    if not candidates:
        candidates = [p for p in printers if model_norm in p["name"].lower()]
    if not candidates:
        raise ValueError(f"No OrcaSlicer printer profile matched model='{model}' nozzle='{nozzle}'. "
                          f"Run 'orca_slice.py list-printers' to see available names.")
    return candidates[0]


def resolve_process_profile(printer_name: str, quality: str) -> dict:
    processes = orca.list_processes(printer=printer_name, vendor="Flashforge")
    quality_norm = quality.lower()
    candidates = [p for p in processes if quality_norm in p["name"].lower()]
    if not candidates:
        raise ValueError(f"No process profile matched quality='{quality}' for printer='{printer_name}'.")
    return candidates[0]


MONITORING_MODES = {
    "auto_analysis": "The agent looks at each webcam snapshot itself (vision) and compares it "
                      "against data/troubleshooting.json to catch defects early.",
    "screenshot_only": "The agent does NOT attempt visual defect analysis -- it just posts each "
                        "snapshot + status to the user on the configured cadence for them to judge. "
                        "Use this if the model running the skill has no/weak vision.",
}


def apply(host: str, model: str, nozzle: str, moonraker_port: int, webcam_port: int, mainsail_port: int,
          default_filament: str, default_process_quality: str, monitoring_mode: str) -> dict:
    findings = probe(host, moonraker_port, webcam_port, mainsail_port)
    printer_profile = resolve_printer_profile(model, nozzle)
    process_profile = resolve_process_profile(printer_profile["name"], default_process_quality)

    cfg = json.loads(CONFIG_PATH.read_text())
    cfg["printer"]["host"] = host
    cfg["printer"]["moonraker_port"] = moonraker_port
    cfg["printer"]["webcam_port"] = webcam_port
    cfg["printer"]["mainsail_port"] = mainsail_port
    cfg["printer"]["firmware"] = findings["firmware"]
    cfg["printer"]["name"] = f"{model} ({findings['firmware']})"
    cfg.setdefault("defaults", {}).update({
        "printer_profile": printer_profile["name"],
        "process_profile": process_profile["name"],
        "filament_profile": default_filament,
    })
    cfg.setdefault("monitoring", {})["mode"] = monitoring_mode
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2))

    return {"probe": findings, "resolved": cfg["defaults"], "monitoring_mode": monitoring_mode,
            "config_written_to": str(CONFIG_PATH)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_probe = sub.add_parser("probe")
    p_probe.add_argument("--host", required=True)
    p_probe.add_argument("--moonraker-port", type=int, default=7125)
    p_probe.add_argument("--webcam-port", type=int, default=8080)
    p_probe.add_argument("--mainsail-port", type=int, default=4000)
    p_probe.set_defaults(func=lambda a: probe(a.host, a.moonraker_port, a.webcam_port, a.mainsail_port))

    p_apply = sub.add_parser("apply")
    p_apply.add_argument("--host", required=True)
    p_apply.add_argument("--model", required=True, help='e.g. "Flashforge Adventurer 5M Pro"')
    p_apply.add_argument("--nozzle", default="0.4", help="nozzle diameter in mm, default 0.4")
    p_apply.add_argument("--moonraker-port", type=int, default=7125)
    p_apply.add_argument("--webcam-port", type=int, default=8080)
    p_apply.add_argument("--mainsail-port", type=int, default=4000)
    p_apply.add_argument("--default-filament", default="Flashforge PLA Basic")
    p_apply.add_argument("--default-process-quality", default="0.20mm Standard")
    p_apply.add_argument("--monitoring-mode", choices=list(MONITORING_MODES.keys()), default="auto_analysis",
                          help="auto_analysis: agent does vision defect-checking itself. "
                               "screenshot_only: agent just posts photos for the user to judge "
                               "(pick this if the model running the skill has no/weak vision).")
    p_apply.set_defaults(func=lambda a: apply(a.host, a.model, a.nozzle, a.moonraker_port, a.webcam_port,
                                               a.mainsail_port, a.default_filament, a.default_process_quality,
                                               a.monitoring_mode))

    args = parser.parse_args()
    print(json.dumps(args.func(args), indent=2))


if __name__ == "__main__":
    main()
