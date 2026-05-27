# flatpakrepo

A personal Flatpak repository hosting upstream and custom Flatpaks for easy
consumption of updates. Built on top of
[aetherpak/actions](https://github.com/aetherpak/actions): each push builds the
changed apps, pushes OCI layers to GHCR, and serves a single signed Flatpak
remote plus per-app `.flatpakref` files from GitHub Pages.

## Layout

Each app lives under `apps/<appid>/` as a git submodule pointing at its source
flatpak repository. The manifest path, runtime container image, and
architectures are declared explicitly in [`apps.yaml`](apps.yaml) — no
auto-detection of any kind, so adding or removing an app is a one-line edit.

```
apps/
└── ai.lemonade_server.Lemonade/        # submodule: lemonade-sdk/lemonade-flatpak
    └── ai.lemonade_server.Lemonade.yaml
apps.yaml                                # declarative matrix source
```

A typical `apps.yaml` entry:

```yaml
apps:
  - id: ai.lemonade_server.Lemonade
    manifest: apps/ai.lemonade_server.Lemonade/ai.lemonade_server.Lemonade.yaml
    runtime: gnome-50                    # flathub-infra image tag
    arches: [x86_64]
    branch: stable                       # optional; defaults to stable
```

## Adding an app

```bash
git submodule add https://github.com/<owner>/<repo>.git apps/<appid>
# Then append an entry to apps.yaml
git commit -am "Add <appid>"
git push
```

## Updating an app

```bash
git submodule update --remote apps/<appid>
git commit -am "Bump <appid>"
git push
```

Only the apps whose submodule pointer (or any file under their directory)
changed get rebuilt.

## Build pipeline

[`.github/workflows/publish.yml`](.github/workflows/publish.yml) runs on
`push`, `workflow_dispatch`, and a weekly `schedule`:

1. **plan** — [`.github/scripts/plan.py`](.github/scripts/plan.py) diffs
   `HEAD` against `github.event.before` and intersects the touched paths with
   `apps.yaml` to emit a matrix of `{app-id, manifest, runtime, branch,
   arches}` entries. A change to `apps.yaml`, the workflow itself, or
   `plan.py` triggers a full rebuild; `schedule`, `workflow_dispatch`
   `force-all`, and any push without a reliable base SHA do the same.
2. **publish** — matrix-of-reusable-workflow calls to
   `aetherpak/actions/.github/workflows/publish.yml@v1`, one invocation per
   app, with `strategy.max-parallel: 1`. Each call handles build (per-arch
   matrix inside the reusable workflow), OCI push to GHCR, index merge with
   optional signing, and a Pages deploy. The next call seeds its
   `index/static` from the previous deploy.

`max-parallel: 1` is what keeps the reusable workflow's per-repo concurrency
lock from ever holding 3+ pending publishes, which GitHub Actions would
otherwise resolve by cancelling the oldest pending. Combined with the
top-level `concurrency: flatpakrepo-publish`, no two runs ever race the same
`index/static`.

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
