# flatpakrepo

A personal Flatpak repository hosting upstream and custom Flatpaks for easy
consumption of updates.

Site: https://abn.github.io/flatpakrepo — install instructions, app listing,
and one-click `.flatpakref` files live there.

## Apps

Apps are declared in [`apps.yaml`](apps.yaml). Each entry uses one of two
source kinds:

```yaml
apps:
  - id: ai.lemonade_server.Lemonade        # manifest source
    manifest: apps/ai.lemonade_server.Lemonade/ai.lemonade_server.Lemonade.yaml
    runtime: gnome-50
    arches: [x86_64]
    branch: stable

  - id: com.stacklok.ToolHive              # bundle source
    bundles:
      x86_64: { url: ..., sha256: ... }
      aarch64: { url: ..., sha256: ... }
```

Manifest entries pull from a submodule under `apps/<appid>/` and build in CI.
Bundle entries import a prebuilt `.flatpak` release asset, verify the
SHA-256, and re-tag to the entry's `branch` (default `stable`).

### Add an app

```bash
# Manifest source
git submodule add https://github.com/<owner>/<repo>.git apps/<appid>
# Bundle source: just append the entry; no submodule
$EDITOR apps.yaml
git commit -am "add <appid>"
git push
```

### Update an app

```bash
# Manifest source
git submodule update --remote apps/<appid>
# Bundle source: bump the version in URL and update sha256 in apps.yaml
$EDITOR apps.yaml
git commit -am "bump <appid>"
git push
```

Only apps whose entry (or, for manifests, whose directory) actually changed
get rebuilt.

## Build

[`.github/workflows/publish.yml`](.github/workflows/publish.yml) is a thin
caller of
[`aetherpak/actions`](https://github.com/aetherpak/actions)'s
`publish-multi.yml` reusable workflow, which owns everything from planning
through the Pages deploy. See the aetherpak docs for the full input list,
schema reference, and signing setup.
