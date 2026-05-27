#!/usr/bin/env python3
"""Expand apps.yaml into a build matrix, narrowed to the touched apps.

Inputs (env):
    CONFIG    path to apps.yaml (default: apps.yaml)
    FORCE     '' | 'all' | '<app-id>'
    BASE_SHA  commit to diff against; empty / all-zeros / unknown -> rebuild all

Outputs (GITHUB_OUTPUT):
    apps    JSON list of selected app ids
    matrix  {include: [{app-id, manifest, runtime, branch, arches}, ...]}
            where arches is the space-separated form the aetherpak reusable
            workflow expects
    count   number of selected apps
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import yaml

SUPPORTED_ARCHES = {"x86_64", "aarch64"}
ZERO_SHA = "0" * 40

# Touching any of these means a rebuild of every app, because runtime, arches,
# or selection logic itself may have shifted.
CONFIG_PATHS = {
    "apps.yaml",
    ".github/workflows/publish.yml",
    ".github/scripts/plan.py",
}


def die(msg: str) -> None:
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def load_apps(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        die(f"{path} not found")
    raw = yaml.safe_load(path.read_text()) or {}
    apps = raw.get("apps") or []
    normalized = []
    for entry in apps:
        normalized.append({
            "id": entry["id"],
            "manifest": entry["manifest"],
            "runtime": entry["runtime"],
            "branch": entry.get("branch", "stable"),
            "arches": entry.get("arches", ["x86_64"]),
        })
    return normalized


def diff_files(base_sha: str) -> list[str] | None:
    """Return the paths changed between base_sha and HEAD, or None to mean
    'no reliable base, rebuild everything'."""
    if not base_sha or base_sha == ZERO_SHA:
        return None
    if subprocess.run(["git", "cat-file", "-e", base_sha], capture_output=True).returncode != 0:
        return None
    r = subprocess.run(
        ["git", "diff", "--name-only", base_sha, "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.splitlines()


def select_ids(apps: list[dict], *, force: str, changed: list[str] | None) -> list[str]:
    all_ids = [a["id"] for a in apps]
    if force == "all":
        return all_ids
    if force:
        if force not in all_ids:
            die(f"Requested app '{force}' is not in the config")
        return [force]
    if changed is None or any(p in CONFIG_PATHS for p in changed):
        return all_ids
    # A submodule pointer bump shows up as a change to the submodule path itself,
    # so a prefix match on the app's directory covers both in-tree edits and bumps.
    selected = []
    for app in apps:
        app_dir = str(pathlib.PurePosixPath(app["manifest"]).parent)
        if app_dir in (".", ""):
            continue
        prefix = app_dir.rstrip("/") + "/"
        if any(p == app_dir or p.startswith(prefix) for p in changed):
            selected.append(app["id"])
    return selected


def expand_matrix(apps: list[dict], selected: list[str]) -> list[dict]:
    by_id = {a["id"]: a for a in apps}
    include = []
    for app_id in selected:
        app = by_id[app_id]
        for arch in app["arches"]:
            if arch not in SUPPORTED_ARCHES:
                die(f"Unsupported arch '{arch}' for app '{app_id}'")
        include.append({
            "app-id": app["id"],
            "manifest": app["manifest"],
            "runtime": app["runtime"],
            "branch": app["branch"],
            "arches": " ".join(app["arches"]),
        })
    return include


def emit_outputs(apps_json: str, matrix_json: str, count: int) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as fh:
        fh.write(f"apps={apps_json}\n")
        fh.write(f"matrix={matrix_json}\n")
        fh.write(f"count={count}\n")


def main() -> None:
    config = pathlib.Path(os.environ.get("CONFIG", "apps.yaml"))
    force = os.environ.get("FORCE", "").strip()
    base_sha = os.environ.get("BASE_SHA", "").strip()

    apps = load_apps(config)
    changed = diff_files(base_sha) if not force else []
    selected = sorted(set(select_ids(apps, force=force, changed=changed)))
    include = expand_matrix(apps, selected)

    apps_json = json.dumps(selected)
    matrix_json = json.dumps({"include": include}, separators=(",", ":"))
    emit_outputs(apps_json, matrix_json, len(selected))

    print(f"Changed files: {changed!r}")
    print(f"Selected apps: {apps_json}")
    print(f"Matrix: {matrix_json}")


if __name__ == "__main__":
    main()
