#!/usr/bin/env python3
"""
Headless OrcaSlicer CLI wrapper.

Usage:
  orca_slice.py list-printers [--vendor Flashforge]
  orca_slice.py list-filaments [--vendor Flashforge] [--printer "Flashforge Adventurer 5M Pro 0.4 Nozzle"]
  orca_slice.py list-processes [--printer "Flashforge Adventurer 5M Pro 0.4 Nozzle"]
  orca_slice.py slice <model.stl> --printer NAME --filament NAME --process NAME
      --outdir DIR
      [--infill 20] [--layer-height 0.2] [--supports auto|tree|none] [--brim 0]
      [--extra key=value ...]     # any raw OrcaSlicer setting override, e.g. seam_position=aligned
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ORCA_BIN = "/Applications/OrcaSlicer.app/Contents/MacOS/OrcaSlicer"
RESOURCES_PROFILES = Path("/Applications/OrcaSlicer.app/Contents/Resources/profiles")
USER_DATA_DIR = Path.home() / "Library/Application Support/OrcaSlicer"
USER_PROFILES_DIR = USER_DATA_DIR / "user/default"

SUPPORT_TYPE_MAP = {
    "auto": "normal(auto)",
    "normal": "normal",
    "tree": "tree(auto)",
    "tree-manual": "tree",
    "none": None,
}


def _vendor_index(vendor: str) -> dict:
    path = RESOURCES_PROFILES / f"{vendor}.json"
    if not path.exists():
        raise FileNotFoundError(f"No vendor profile index for '{vendor}' at {path}")
    return json.loads(path.read_text())


def _vendor_dir(vendor: str) -> Path:
    return RESOURCES_PROFILES / vendor


def list_vendors():
    return sorted(p.stem for p in RESOURCES_PROFILES.glob("*.json"))


def list_printers(vendor: str = None):
    out = []
    vendors = [vendor] if vendor else list_vendors()
    for v in vendors:
        try:
            idx = _vendor_index(v)
        except FileNotFoundError:
            continue
        for m in idx.get("machine_list", []):
            if m.get("instantiation") == "false":
                continue
            out.append({"vendor": v, "name": m["name"], "sub_path": m["sub_path"], "path": str(RESOURCES_PROFILES / v / m["sub_path"])})
    # user-defined printers on top
    machine_dir = USER_PROFILES_DIR / "machine"
    if machine_dir.exists():
        for f in sorted(machine_dir.glob("*.json")):
            out.append({"vendor": "user", "name": f.stem, "sub_path": str(f)})
    return out


def list_filaments(vendor: str = None, printer: str = None):
    out = []
    vendors = [vendor] if vendor else list_vendors()
    for v in vendors:
        try:
            idx = _vendor_index(v)
        except FileNotFoundError:
            continue
        for f in idx.get("filament_list", []):
            if printer and printer.split(" 0.")[0].strip() not in f["name"] and printer not in f["name"]:
                pass  # filament names don't reliably encode printer; don't over-filter here
            out.append({"vendor": v, "name": f["name"], "sub_path": f["sub_path"], "path": str(RESOURCES_PROFILES / v / f["sub_path"])})
    filament_dir = USER_PROFILES_DIR / "filament"
    if filament_dir.exists():
        for f in sorted(filament_dir.glob("*.json")):
            out.append({"vendor": "user", "name": f.stem, "sub_path": str(f)})
    return out


def list_processes(printer: str = None, vendor: str = None):
    out = []
    vendors = [vendor] if vendor else list_vendors()
    for v in vendors:
        try:
            idx = _vendor_index(v)
        except FileNotFoundError:
            continue
        for p in idx.get("process_list", []):
            data_path = RESOURCES_PROFILES / v / p["sub_path"]
            compat = []
            if data_path.exists():
                try:
                    compat = json.loads(data_path.read_text()).get("compatible_printers", [])
                except json.JSONDecodeError:
                    pass
            if printer and compat and printer not in compat:
                continue
            if not compat and "fdm_process_" in p["name"]:
                continue  # skip abstract base presets, not directly usable
            out.append({"vendor": v, "name": p["name"], "sub_path": p["sub_path"], "path": str(data_path), "compatible_printers": compat})
    process_dir = USER_PROFILES_DIR / "process"
    if process_dir.exists():
        for f in sorted(process_dir.glob("*.json")):
            out.append({"vendor": "user", "name": f.stem, "sub_path": str(f)})
    return out


def _resolve_profile_path(kind: str, name: str, vendor: str = None) -> Path:
    """kind: machine|filament|process. Looks in user dir first, then vendor bundles."""
    user_path = USER_PROFILES_DIR / kind / f"{name}.json"
    if user_path.exists():
        return user_path
    if Path(name).exists():
        return Path(name)
    vendors = [vendor] if vendor else list_vendors()
    key = {"machine": "machine_list", "filament": "filament_list", "process": "process_list"}[kind]
    for v in vendors:
        try:
            idx = _vendor_index(v)
        except FileNotFoundError:
            continue
        for entry in idx.get(key, []):
            if entry["name"] == name:
                return RESOURCES_PROFILES / v / entry["sub_path"]
    raise FileNotFoundError(f"Could not find {kind} profile named '{name}' (searched user dir + all vendors)")


SCRATCH_DIR = Path.home() / "Library/Caches/3d-print-skill"


def _ensure_klipper_layer_reset(process_path: Path) -> Path:
    """Klipper printers using relative-E need 'G92 E0' in layer_change_gcode, or OrcaSlicer
    refuses to slice ('Relative extruder addressing requires resetting the extruder position').
    Patches a scratch copy of the process preset rather than mutating the original."""
    data = json.loads(process_path.read_text())
    if data.get("layer_change_gcode"):
        return process_path
    data["layer_change_gcode"] = "G92 E0"
    SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
    patched = SCRATCH_DIR / f"_patched_{process_path.stem}.json"
    patched.write_text(json.dumps(data, indent=2))
    return patched


def slice_model(stl_path: str, printer: str, filament: str, process: str, outdir: str,
                 infill: int = None, layer_height: float = None, supports: str = None,
                 brim: float = None, extra: dict = None) -> dict:
    machine_path = _resolve_profile_path("machine", printer)
    filament_path = _resolve_profile_path("filament", filament)
    process_path = _ensure_klipper_layer_reset(_resolve_profile_path("process", process))

    out_dir = Path(outdir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        ORCA_BIN,
        "--datadir", str(USER_DATA_DIR),
        "--load-settings", f"{machine_path};{process_path}",
        "--load-filaments", str(filament_path),
        "--allow-newer-file",
        "--outputdir", str(out_dir),
    ]

    if infill is not None:
        cmd += [f"--sparse-infill-density={infill}%"]
    if layer_height is not None:
        cmd += [f"--layer-height={layer_height}"]
    if brim is not None:
        cmd += [f"--brim-width={brim}"]
    if supports is not None:
        support_type = SUPPORT_TYPE_MAP.get(supports, supports)
        if support_type is None:
            cmd += ["--enable-support=0"]
        else:
            cmd += ["--enable-support=1", "--support-type", support_type]
    for k, v in (extra or {}).items():
        # bool-typed OrcaSlicer settings must use --flag=value; --flag value mis-parses "0"/"1"
        # as a stray positional file argument. Using '=' is safe for every setting type.
        cmd += [f"--{k.replace('_', '-')}={v}"]

    cmd += ["--slice", "0", stl_path]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

    gcode_files = sorted(out_dir.glob("plate_*.gcode"))
    info = {
        "command": cmd,
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-2000:],
        "stderr_tail": result.stderr[-2000:],
        "gcode_files": [str(g) for g in gcode_files],
    }
    if gcode_files:
        info["estimate"] = parse_gcode_estimate(gcode_files[0])
    return info


TIME_RE = re.compile(r"estimated printing time.*?=\s*(.+)", re.IGNORECASE)
FILAMENT_RE = re.compile(r"total filament used \[g\]\s*=\s*([\d.]+)", re.IGNORECASE)
FILAMENT_M_RE = re.compile(r"filament used \[mm\]\s*=\s*([\d.]+)", re.IGNORECASE)
FILAMENT_CM3_RE = re.compile(r"filament used \[cm3\]\s*=\s*([\d.]+)", re.IGNORECASE)


def parse_gcode_estimate(gcode_path: Path) -> dict:
    text = gcode_path.read_text(errors="ignore")
    header = text[:20000] + text[-80000:]
    out = {}
    m = TIME_RE.search(header)
    if m:
        out["estimated_time"] = m.group(1).strip()
    m = FILAMENT_RE.search(header)
    if m:
        out["filament_grams"] = float(m.group(1))
    m = FILAMENT_M_RE.search(header)
    if m:
        out["filament_mm"] = float(m.group(1))
    m = FILAMENT_CM3_RE.search(header)
    if m:
        out["filament_cm3"] = float(m.group(1))
    if not out.get("filament_grams") and out.get("filament_cm3"):
        out["filament_grams_estimate"] = round(out["filament_cm3"] * 1.24, 1)  # approx PLA density
    out["file_size_bytes"] = gcode_path.stat().st_size
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_lp = sub.add_parser("list-printers")
    p_lp.add_argument("--vendor")
    p_lp.set_defaults(func=lambda a: print(json.dumps(list_printers(a.vendor), indent=2)))

    p_lf = sub.add_parser("list-filaments")
    p_lf.add_argument("--vendor")
    p_lf.add_argument("--printer")
    p_lf.set_defaults(func=lambda a: print(json.dumps(list_filaments(a.vendor, a.printer), indent=2)))

    p_lpr = sub.add_parser("list-processes")
    p_lpr.add_argument("--vendor")
    p_lpr.add_argument("--printer")
    p_lpr.set_defaults(func=lambda a: print(json.dumps(list_processes(a.printer, a.vendor), indent=2)))

    p_s = sub.add_parser("slice")
    p_s.add_argument("stl_path")
    p_s.add_argument("--printer", required=True)
    p_s.add_argument("--filament", required=True)
    p_s.add_argument("--process", required=True)
    p_s.add_argument("--outdir", required=True)
    p_s.add_argument("--infill", type=int)
    p_s.add_argument("--layer-height", type=float)
    p_s.add_argument("--supports", choices=list(SUPPORT_TYPE_MAP.keys()))
    p_s.add_argument("--brim", type=float)
    p_s.add_argument("--extra", action="append", default=[], help="key=value, repeatable")

    def _do_slice(a):
        extra = dict(kv.split("=", 1) for kv in a.extra)
        info = slice_model(a.stl_path, a.printer, a.filament, a.process, a.outdir,
                            a.infill, a.layer_height, a.supports, a.brim, extra)
        print(json.dumps(info, indent=2))
        if info["returncode"] != 0 or not info["gcode_files"]:
            sys.exit(1)

    p_s.set_defaults(func=_do_slice)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
