"""
Register (or remove) this SolidWorks MCP server in Claude Desktop.

    .venv\\Scripts\\python.exe scripts\\register_claude_desktop.py            # add / update
    .venv\\Scripts\\python.exe scripts\\register_claude_desktop.py --remove   # remove
    .venv\\Scripts\\python.exe scripts\\register_claude_desktop.py --dry-run  # show only
    .venv\\Scripts\\python.exe scripts\\register_claude_desktop.py --list     # where it looks
    ... --config "C:\\path\\to\\claude_desktop_config.json"                   # explicit file

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


CFG = "claude_desktop_config.json"


def _uniq(paths):
    seen, out = set(), []
    for p in paths:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen:
            seen.add(k)
            out.append(os.path.abspath(p))
    return out


def config_candidates():
    """Config file paths (standard + MSIX), from env vars and from the home folder."""
    roamings, locals_ = [], []
    if os.environ.get("APPDATA"):
        roamings.append(os.environ["APPDATA"])
    if os.environ.get("LOCALAPPDATA"):
        locals_.append(os.environ["LOCALAPPDATA"])
    for home in {os.path.expanduser("~"), os.environ.get("USERPROFILE", "")}:
        if home:
            roamings.append(os.path.join(home, "AppData", "Roaming"))
            locals_.append(os.path.join(home, "AppData", "Local"))

    paths = [os.path.join(r, "Claude", CFG) for r in roamings]
    for loc in locals_:
        pkg_dirs = glob.glob(os.path.join(loc, "Packages", "Claude_*"))
        paths += [os.path.join(d, "LocalCache", "Roaming", "Claude", CFG) for d in pkg_dirs]
    return _uniq(paths)


def pick_configs(explicit=None):
    if explicit:
        p = os.path.abspath(os.path.expandvars(explicit))
        if os.path.isdir(p):
            p = os.path.join(p, CFG)
        if not os.path.isdir(os.path.dirname(p)):
            sys.exit(f"Folder does not exist: {os.path.dirname(p)}")
        return [p]

    cands = config_candidates()
    existing = [p for p in cands if os.path.isfile(p)]
    if existing:
        return existing
    # No config file yet: create it in every Claude folder that exists
    # (standard and MSIX may both be present; Claude Desktop reads one of them)
    folders = [p for p in cands if os.path.isdir(os.path.dirname(p))]
    if folders:
        return folders

    print("Checked:")
    for p in cands:
        print(f"  {'[dir ok]' if os.path.isdir(os.path.dirname(p)) else '[no dir]'} {p}")
    print(f"APPDATA={os.environ.get('APPDATA')!r}  LOCALAPPDATA={os.environ.get('LOCALAPPDATA')!r}  "
          f"home={os.path.expanduser('~')!r}")
    sys.exit("Claude Desktop config not found. In Claude Desktop: Settings > Developer > Edit Config, "
             "copy that file's path, then rerun with --config \"<path>\".")


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
    ap.add_argument("--config", help="Path to claude_desktop_config.json (or its folder)")
    ap.add_argument("--list", action="store_true", help="Show candidate config paths and exit")
    args = ap.parse_args()

    if args.list:
        for p in config_candidates():
            state = "file" if os.path.isfile(p) else ("dir only" if os.path.isdir(os.path.dirname(p)) else "missing")
            print(f"[{state:8}] {p}")
        return

    python = os.path.abspath(sys.executable)
    base = os.path.realpath(getattr(sys, "_base_executable", "") or sys.base_prefix)
    if "windowsapps" in base.lower() or "\\packages\\" in base.lower():
        print(f"WARNING: base Python looks like a Store/MSIX package ({base}). Its file writes to "
              f"AppData may be virtualized; prefer --config with the path from Claude Desktop.")
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

    for path in pick_configs(args.config):
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
