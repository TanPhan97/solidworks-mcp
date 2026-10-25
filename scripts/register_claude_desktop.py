"""
Register (or remove) this SolidWorks MCP server in Claude Desktop.

    .venv\\Scripts\\python.exe scripts\\register_claude_desktop.py            # add / update
    .venv\\Scripts\\python.exe scripts\\register_claude_desktop.py --remove   # remove
    .venv\\Scripts\\python.exe scripts\\register_claude_desktop.py --dry-run  # show only

- Merges into the existing claude_desktop_config.json; other servers
  (e.g. autocad-mcp) and settings are kept untouched.
- Writes a timestamped backup next to the config before changing it.
- Uses absolute paths to THIS repo and the Python running this script
  (run it with the venv python so the venv is what Claude Desktop launches).
- Handles both the standard install (%APPDATA%\\Claude) and the
  Microsoft Store / MSIX install (%LOCALAPPDATA%\\Packages\\Claude_*\\...).
"""

import os
import sys
import glob
import json
import shutil
import argparse
import datetime

SERVER_NAME = "solidworks"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ENTRY = os.path.join(REPO, "solidworks_mcp_server.py")


def config_candidates():
    paths = []
    appdata = os.environ.get("APPDATA")
    if appdata:
        paths.append(os.path.join(appdata, "Claude", "claude_desktop_config.json"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths += glob.glob(os.path.join(local, "Packages", "Claude_*", "LocalCache",
                                        "Roaming", "Claude", "claude_desktop_config.json"))
    return paths


def pick_configs():
    cands = config_candidates()
    existing = [p for p in cands if os.path.isfile(p)]
    if existing:
        return existing
    # Nothing yet: create the standard one if its folder exists
    for p in cands:
        if os.path.isdir(os.path.dirname(p)):
            return [p]
    sys.exit("Claude Desktop config folder not found. Open Claude Desktop once, then retry.")


def load(path):
    if not os.path.isfile(path):
        return {}
    with open(path, "r", encoding="utf-8-sig") as f:
        text = f.read().strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        sys.exit(f"{path} is not valid JSON ({e}). Fix it manually first; nothing was changed.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--remove", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    python = os.path.abspath(sys.executable)
    if not args.remove:
        if not os.path.isfile(ENTRY):
            sys.exit(f"Entry point not found: {ENTRY}")
        if ".venv" not in python.lower():
            print(f"WARNING: running with {python}, not the repo .venv. "
                  f"Claude Desktop will launch this interpreter.")
        try:
            import win32com.client  # noqa: F401
            import mcp  # noqa: F401
        except ImportError as e:
            sys.exit(f"{python} is missing a dependency ({e}). Run: pip install -r requirements.txt")

    entry = {
        "command": python,
        "args": [ENTRY],
        "env": {"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
    }

    for path in pick_configs():
        cfg = load(path)
        servers = cfg.setdefault("mcpServers", {})
        others = [k for k in servers if k != SERVER_NAME]

        if args.remove:
            if SERVER_NAME not in servers:
                print(f"{path}: '{SERVER_NAME}' not present, nothing to do")
                continue
            servers.pop(SERVER_NAME)
            action = "removed"
        else:
            action = "updated" if SERVER_NAME in servers else "added"
            servers[SERVER_NAME] = entry

        print(f"\n{path}")
        print(f"  {SERVER_NAME}: {action}")
        print(f"  other servers kept: {others or 'none'}")
        if args.dry_run:
            print(json.dumps({SERVER_NAME: servers.get(SERVER_NAME)}, indent=2))
            continue

        if os.path.isfile(path):
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = f"{path}.bak_{stamp}"
            shutil.copy2(path, backup)
            print(f"  backup: {backup}")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
        print("  written")

    if not args.dry_run:
        print("\nNext: Quit Claude Desktop from the system tray (not just close the window), "
              "open SolidWorks, then start Claude Desktop again.")


if __name__ == "__main__":
    main()
