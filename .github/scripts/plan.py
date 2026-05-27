#!/usr/bin/env python3
"""Expand apps.yaml into a build matrix, narrowed to the touched apps.

Inputs (env):
    CONFIG    path to apps.yaml (default: apps.yaml)
    FORCE     '' | 'all' | '<app-id>'
    BASE_SHA  commit to diff against; empty / all-zeros / unknown -> rebuild all

Outputs (GITHUB_OUTPUT):
    apps              JSON list of selected app ids
    matrix            full matrix: {include: [<row>, ...]}
    matrix-manifest   subset where source == 'manifest'
    matrix-bundle     subset where source == 'bundle'
    count             total number of selected apps
    count-manifest    number of manifest entries (used to gate the build job)
    count-bundle      number of bundle entries (used to gate the prep-bundle job)

Row shape:
    manifest: {source, app-id, manifest, runtime, branch, arch, runner}
    bundle:   {source, app-id, branch, arch, runner, bundle-url, bundle-sha256}
"""
from __future__ import annotations

import json
import logging
import os
import pathlib
import subprocess
import sys

import yaml

log = logging.getLogger("plan")

RUNNER_BY_ARCH = {
    "x86_64": "ubuntu-latest",
    "aarch64": "ubuntu-24.04-arm",
}
ZERO_SHA = "0" * 40

# Touching either forces a full rebuild. apps.yaml is handled per-entry below.
CONFIG_PATHS = {
    ".github/workflows/publish.yml",
    ".github/scripts/plan.py",
}


def die(msg: str) -> None:
    # `::error::` is a workflow command parsed by the runner; emit directly so
    # the line format isn't subject to logging config.
    print(f"::error::{msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def load_apps_yaml(text: str) -> list[dict]:
    raw = yaml.safe_load(text) or {}
    return raw.get("apps") or []


def load_apps(path: pathlib.Path) -> list[dict]:
    if not path.is_file():
        die(f"{path} not found")
    apps = load_apps_yaml(path.read_text())
    for entry in apps:
        validate(entry)
    return apps


def validate(entry: dict) -> None:
    app_id = entry.get("id")
    if not app_id:
        die(f"app entry missing 'id': {entry!r}")
    has_manifest = "manifest" in entry
    has_bundles = "bundles" in entry
    if has_manifest == has_bundles:
        die(f"'{app_id}': exactly one of 'manifest' or 'bundles' is required")
    if has_manifest:
        if not entry.get("runtime"):
            die(f"'{app_id}': 'runtime' is required when 'manifest' is set")
        for arch in entry.get("arches", ["x86_64"]):
            if arch not in RUNNER_BY_ARCH:
                die(f"'{app_id}': unsupported arch '{arch}'")
    else:
        bundles = entry["bundles"] or {}
        if not bundles:
            die(f"'{app_id}': 'bundles' must contain at least one architecture")
        for arch, b in bundles.items():
            if arch not in RUNNER_BY_ARCH:
                die(f"'{app_id}': unsupported bundle arch '{arch}'")
            if not isinstance(b, dict) or not b.get("url") or not b.get("sha256"):
                die(f"'{app_id}' bundle '{arch}': 'url' and 'sha256' are required")


def previous_apps(base_sha: str, config_path: pathlib.Path) -> list[dict] | None:
    """Load apps.yaml as of base_sha. None means 'no reliable previous state'."""
    if not base_sha or base_sha == ZERO_SHA:
        return None
    r = subprocess.run(
        ["git", "show", f"{base_sha}:{config_path}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return None
    try:
        return load_apps_yaml(r.stdout)
    except yaml.YAMLError:
        return None


def diff_files(base_sha: str) -> list[str] | None:
    if not base_sha or base_sha == ZERO_SHA:
        return None
    if subprocess.run(["git", "cat-file", "-e", base_sha], capture_output=True).returncode != 0:
        return None
    r = subprocess.run(
        ["git", "diff", "--name-only", base_sha, "HEAD"],
        capture_output=True, text=True, check=True,
    )
    return r.stdout.splitlines()


def manifest_dir_touched(entry: dict, changed: list[str]) -> bool:
    manifest = entry.get("manifest")
    if not manifest:
        return False
    app_dir = str(pathlib.PurePosixPath(manifest).parent)
    if app_dir in (".", ""):
        return False
    prefix = app_dir.rstrip("/") + "/"
    return any(p == app_dir or p.startswith(prefix) for p in changed)


def select_ids(
    apps_current: list[dict],
    apps_previous: list[dict] | None,
    *,
    force: str,
    changed: list[str] | None,
) -> list[str]:
    all_ids = [a["id"] for a in apps_current]
    if force == "all":
        return all_ids
    if force:
        if force not in all_ids:
            die(f"Requested app '{force}' is not in the config")
        return [force]
    if changed is None:
        return all_ids
    if any(p in CONFIG_PATHS for p in changed):
        return all_ids
    by_id_prev = {a["id"]: a for a in (apps_previous or [])}
    selected = []
    for app in apps_current:
        # Manifest source: gitlink bumps and in-tree edits both surface as paths
        # under the manifest's directory, so a prefix match catches both.
        if manifest_dir_touched(app, changed):
            selected.append(app["id"])
            continue
        # Any source: rebuild when the app's entry-dict differs from the previous
        # apps.yaml — bundle sha bumps, runtime/arch changes, etc.
        if apps_previous is None or by_id_prev.get(app["id"]) != app:
            selected.append(app["id"])
    return selected


def expand_matrix(apps: list[dict], selected: list[str]) -> list[dict]:
    by_id = {a["id"]: a for a in apps}
    include = []
    for app_id in selected:
        app = by_id[app_id]
        branch = app.get("branch", "stable")
        if "manifest" in app:
            arches = app.get("arches", ["x86_64"])
            for arch in arches:
                include.append({
                    "source": "manifest",
                    "app-id": app_id,
                    "manifest": app["manifest"],
                    "runtime": app["runtime"],
                    "branch": branch,
                    "arch": arch,
                    "runner": RUNNER_BY_ARCH[arch],
                })
        else:
            for arch, b in app["bundles"].items():
                include.append({
                    "source": "bundle",
                    "app-id": app_id,
                    "branch": branch,
                    "arch": arch,
                    "runner": RUNNER_BY_ARCH[arch],
                    "bundle-url": b["url"],
                    "bundle-sha256": b["sha256"],
                })
    return include


def emit_outputs(values: dict[str, str]) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        return
    with open(out, "a", encoding="utf-8") as fh:
        for k, v in values.items():
            fh.write(f"{k}={v}\n")


def main() -> None:
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    config = pathlib.Path(os.environ.get("CONFIG", "apps.yaml"))
    force = os.environ.get("FORCE", "").strip()
    base_sha = os.environ.get("BASE_SHA", "").strip()

    apps_current = load_apps(config)
    apps_prev = previous_apps(base_sha, config) if not force else None
    changed = diff_files(base_sha) if not force else []

    selected = sorted(set(select_ids(apps_current, apps_prev, force=force, changed=changed)))
    include = expand_matrix(apps_current, selected)
    manifest_rows = [r for r in include if r["source"] == "manifest"]
    bundle_rows = [r for r in include if r["source"] == "bundle"]

    apps_json = json.dumps(selected)
    matrix_json = json.dumps({"include": include}, separators=(",", ":"))
    manifest_json = json.dumps({"include": manifest_rows}, separators=(",", ":"))
    bundle_json = json.dumps({"include": bundle_rows}, separators=(",", ":"))

    emit_outputs({
        "apps": apps_json,
        "matrix": matrix_json,
        "matrix-manifest": manifest_json,
        "matrix-bundle": bundle_json,
        "count": str(len(selected)),
        "count-manifest": str(len(manifest_rows)),
        "count-bundle": str(len(bundle_rows)),
    })

    log.info("Changed files: %r", changed)
    log.info("Selected apps: %s", apps_json)
    log.info("Matrix (manifest): %s", manifest_json)
    log.info("Matrix (bundle): %s", bundle_json)


if __name__ == "__main__":
    main()
