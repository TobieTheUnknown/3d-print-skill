# 3d-print-skill

A Claude Code skill that runs the whole 3D printing pipeline end to end:

**printables.com model → OrcaSlicer (headless) → Flashforge AD5M/AD5M Pro over Moonraker → webcam-monitored print → post-print retrospective that tunes profiles for next time.**

See [`SKILL.md`](./SKILL.md) for the full workflow Claude follows. Everything else in this repo is
plain, dependency-free Python (stdlib + `curl` only) meant to be called from that skill:

```
scripts/
  setup.py                    probe the printer, detect firmware, write config.json
  printables_fetch.py         download STLs + read the model's "Details" instructions
  orca_slice.py                headless OrcaSlicer CLI wrapper (list profiles, slice)
  create_printer_profile.py   generate a custom printer profile from a base
  create_filament_profile.py  generate a custom filament profile from a base
  moonraker_client.py         upload/start/pause/cancel/status/history over Moonraker
  webcam_snapshot.py          grab a JPEG from the printer's µStreamer webcam
data/
  troubleshooting.json        14 FDM defects -> visual ID, causes, OrcaSlicer fixes
config.json                   printer host/ports + default profile names
```

## Requirements

- macOS with [OrcaSlicer](https://github.com/OrcaSlicer/OrcaSlicer) installed at
  `/Applications/OrcaSlicer.app` (bundles the Flashforge vendor profiles).
- A printer running Klipper + [Moonraker](https://moonraker.readthedocs.io/) — this was built and
  tested against a Flashforge AD5M running
  [xblax/flashforge_ad5m_klipper_mod](https://github.com/xblax/flashforge_ad5m_klipper_mod)
  (Mainsail on :4000, Moonraker on :7125, a µStreamer webcam on :8080). Stock Flashforge firmware
  is not supported for upload/print/monitor — slicing alone still works.
- No pip installs required.

## Quickstart

```bash
python3 scripts/setup.py probe --host <printer-ip>
python3 scripts/setup.py apply --host <printer-ip> --model "Flashforge Adventurer 5M Pro" --nozzle 0.4

python3 scripts/printables_fetch.py info "https://www.printables.com/model/<id>-<slug>"
python3 scripts/printables_fetch.py download "https://www.printables.com/model/<id>-<slug>" ~/Documents/3D-Prints/<slug>

python3 scripts/orca_slice.py slice ~/Documents/3D-Prints/<slug>/model.stl \
  --printer "Flashforge Adventurer 5M Pro 0.4 Nozzle" \
  --filament "Flashforge PLA Basic" \
  --process "0.20mm Standard @Flashforge AD5M Pro 0.4 Nozzle" \
  --outdir ~/Documents/3D-Prints/<slug> --infill 15 --supports none

python3 scripts/moonraker_client.py upload ~/Documents/3D-Prints/<slug>/plate_1.gcode --start
python3 scripts/moonraker_client.py status
python3 scripts/webcam_snapshot.py --outdir ~/Documents/3D-Prints/<slug>/snapshots
```

Used directly like this it's just a CLI toolkit. Used as a Claude Code skill (`SKILL.md`), Claude
handles profile selection, the pre-print confirmation, webcam-based monitoring with vision, and
the post-print Q&A that turns feedback into tuned profiles.
