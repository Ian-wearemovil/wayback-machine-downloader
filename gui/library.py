"""Remember downloaded sites and find ones already saved on disk."""

import json
import os
import re
from pathlib import Path

# Domain folders created by the downloader, including an optional port.
_SITE_DIRECTORY = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z0-9-]+(?::\d+)?$", re.IGNORECASE)


def library_file():
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "wayback-machine-downloader" / "downloads.json"


def load_records(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    records = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        folder = item.get("path")
        if not name or not folder:
            continue
        records.append(
            {
                "name": str(name),
                "path": str(folder),
                "url": str(item.get("url") or ""),
            }
        )
    return records


def save_records(path, records):
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")


def remember_download(records, name, url, folder):
    """Return records with this download added or updated."""
    folder = str(Path(folder))
    kept = [record for record in records if record["path"] != folder]
    kept.append({"name": name, "path": folder, "url": url})
    return kept


def discover_sites(parent):
    """Find site folders already saved directly inside ``parent``."""
    parent = Path(parent)
    if not parent.is_dir():
        return []
    found = []
    for child in parent.iterdir():
        if not child.is_dir() or not _SITE_DIRECTORY.match(child.name):
            continue
        if not (child / "index.html").is_file():
            continue
        found.append(
            {
                "name": child.name,
                "path": str(child),
                "url": "http://" + child.name,
            }
        )
    return found


def visible_sites(records, parent):
    """Saved downloads that are still on disk, plus sites found in ``parent``."""
    by_path = {}
    for record in records:
        folder = Path(record["path"])
        if folder.is_dir() and (folder / "index.html").is_file():
            by_path[str(folder.resolve())] = {
                "name": record["name"],
                "path": str(folder),
                "url": record.get("url") or "",
            }
    for found in discover_sites(parent):
        key = str(Path(found["path"]).resolve())
        by_path.setdefault(key, found)
    return sorted(by_path.values(), key=lambda record: record["name"].lower())
