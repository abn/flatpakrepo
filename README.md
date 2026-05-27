# flatpakrepo

A personal Flatpak repository hosting upstream and custom Flatpaks for easy
consumption of updates. Built on top of
[aetherpak/actions](https://github.com/aetherpak/actions): each push builds the
changed apps, pushes OCI layers to GHCR, and serves a single signed Flatpak
remote plus per-app `.flatpakref` files from GitHub Pages.

## Layout

Apps are declared in [`apps.yaml`](apps.yaml) under one of two source kinds:

- **`manifest`** — flatpak manifest from a git submodule under `apps/<appid>/`,
  built in CI inside a `flathub-infra/flatpak-github-actions` container.
- **`bundles`** — pre-built `.flatpak` release assets per architecture, fetched
  by URL and verified against a SHA-256 checksum.

```yaml
apps:
  - id: ai.lemonade_server.Lemonade        # manifest source
    manifest: apps/ai.lemonade_server.Lemonade/ai.lemonade_server.Lemonade.yaml
    runtime: gnome-50                       # flathub-infra image tag
    arches: [x86_64]
    branch: stable

  - id: com.stacklok.ToolHive              # bundle source
    bundles:
      x86_64:
        url: https://github.com/.../com.stacklok.ToolHive_x86_64.flatpak
        sha256: <hex>
      aarch64:
        url: https://github.com/.../com.stacklok.ToolHive_aarch64.flatpak
        sha256: <hex>
```

`manifest` and `bundles` are mutually exclusive. For manifest entries the
submodule lives at `apps/<appid>/`; for bundle entries there is no submodule.

## Adding an app

### Manifest source (build from upstream sources)

```bash
git submodule add https://github.com/<owner>/<repo>.git apps/<appid>
# Append an entry to apps.yaml: id, manifest path, runtime, arches
git commit -am "Add <appid>"
git push
```

### Bundle source (import upstream release asset)

```bash
# Compute checksums
curl -fLO https://github.com/.../<file>_x86_64.flatpak
sha256sum <file>_x86_64.flatpak
# Append an entry to apps.yaml with bundles.{x86_64,aarch64}.{url,sha256}
git commit -am "Add <appid>"
git push
```

## Updating an app

Manifest: `git submodule update --remote apps/<appid>` then commit. Bundle:
edit the version in URL and update sha256 in `apps.yaml`. Either way, only the
apps whose entry (or, for manifests, whose directory) actually changed get
rebuilt.

## Build pipeline

[`.github/workflows/publish.yml`](.github/workflows/publish.yml) is a thin
caller of
[`aetherpak/actions/.github/workflows/publish-multi.yml@v1`](https://github.com/aetherpak/actions/blob/v1/.github/workflows/publish-multi.yml),
which owns: change detection (per-entry diff of `apps.yaml` against the base
SHA), manifest builds in flathub containers, bundle fetch + sha verify + ref
re-tag, parallel OCI push (per app/arch), single site aggregation, and Pages
deploy. The top-level `concurrency: flatpakrepo-publish` keeps two of our runs
from racing each other's deploys.

### Manual triggers

- **Rebuild one app**: Actions → *Publish Flatpak Repository* → Run workflow
  → enter the app id.
- **Rebuild everything**: same screen, tick `force-all`.

## Installation

The Pages site exposes per-app one-click `.flatpakref` files plus a repo-level
`<owner>-<repo>.flatpakrepo` for adding the remote. CLI install with signing:

```bash
curl -fsSLO https://<owner>.github.io/<repo>/sigs/key.asc
flatpak remote-add --user \
  --gpg-import=key.asc \
  --signature-lookaside=https://<owner>.github.io/<repo>/sigs \
  <owner>-<repo> oci+https://<owner>.github.io/<repo>
flatpak install --user <owner>-<repo> ai.lemonade_server.Lemonade
```

## One-time setup

- Settings → Pages → Source: **GitHub Actions**.
- For an organization repo: Settings → Packages → Package creation: **Public**.
- After the first run, set the GHCR package to public so consumers can pull
  layers without auth.
- (Optional) Add `AETHERPAK_GPG_KEY` (ASCII-armored private key) and
  `AETHERPAK_GPG_KEY_PASSPHRASE` repository secrets to enable signing.

## Secrets

| Secret | Required | Purpose |
| --- | --- | --- |
| `AETHERPAK_GPG_KEY` | optional | ASCII-armored GPG private key. When set, images are signed and verified installs are wired up. |
| `AETHERPAK_GPG_KEY_PASSPHRASE` | optional | Passphrase for the GPG private key, if protected. |
