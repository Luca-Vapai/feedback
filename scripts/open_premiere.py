#!/usr/bin/env python3
"""
open_premiere.py — Open the Premiere project for a given project ID.

Reads the project's `premiere_project_path` from a small registry file
(`scripts/premiere_projects.json`) and launches Premiere Pro with that
.prproj. Once Premiere is open, the modified MCP Bridge plugin (CEP)
will auto-connect after ~500 ms (see Adobe_Premiere_Pro_MCP/cep-plugin/
bridge-cep.js, "SOUTS patch").

Usage:
    python3 open_premiere.py <project_id>
    python3 open_premiere.py cend

The registry file is a flat JSON map of project_id → absolute path:

    {
      "cend": "/Users/luca/.../CEND Nuevo/Proyecto/Cend I/Cend I.prproj"
    }
"""

import json
import subprocess
import sys
from pathlib import Path

REGISTRY = Path(__file__).resolve().parent / 'premiere_projects.json'


def load_registry():
    if not REGISTRY.exists():
        print(f"Registry not found: {REGISTRY}", file=sys.stderr)
        print("Create it with the format:", file=sys.stderr)
        print('  { "cend": "/absolute/path/to/Cend I.prproj" }', file=sys.stderr)
        sys.exit(1)
    return json.loads(REGISTRY.read_text())


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <project_id>", file=sys.stderr)
        print("Available project IDs:", file=sys.stderr)
        try:
            for k in load_registry():
                print(f"  - {k}", file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)

    project_id = sys.argv[1]
    registry = load_registry()
    if project_id not in registry:
        print(f"Project '{project_id}' not in registry. Known: {list(registry.keys())}", file=sys.stderr)
        sys.exit(1)

    prproj = Path(registry[project_id]).expanduser()
    if not prproj.exists():
        print(f"Project file not found: {prproj}", file=sys.stderr)
        sys.exit(1)

    print(f"Opening {prproj}")
    subprocess.run(['open', str(prproj)], check=True)
    print("Premiere is launching. The MCP Bridge auto-starts after the panel loads.")
    print("If the bridge does not connect, reload the panel from Window → Extensions → MCP Bridge.")


if __name__ == '__main__':
    main()
