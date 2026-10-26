# Launcher, client releases and maintenance

## What each piece does

| Piece | Job |
|---|---|
| `HPMMO_Launcher.exe` (`launcher_cpp/`) | Checks for updates, updates itself and the game, starts the game. **No login.** |
| Game login screen (`scenes/main/main_menu.tscn`, `scripts/ui/main_menu.gd`) | Sign in / create an account, then world join and character selection. |
| `.github/workflows/client-release.yml` | Every push to `main`: exports the game, builds the launcher, signs a manifest, publishes GitHub Release `v1.0.<run>` (marked latest). |
| Account service `/api/status`, maintenance gate (`server/services/cpp`) | Reports ONLINE / maintenance; refuses `/api/login` and `/api/game-ticket` with 503 `code=maintenance` while `maintenance.flag` exists. |
| Deploy controller (`server/deploy/hpmmo_deploy.sh`) | Writes `maintenance.flag` when it announces the 30 s countdown, removes it once the new server release is verified ONLINE. |

## Update flow

1. The launcher fetches `https://github.com/semdin/hpmmo-client/releases/latest/download/manifest.json` and `.sig`
   and verifies the Ed25519 signature with the key built into it (`HPMMO_DEFAULT_RELEASE_KEY` in
   `launcher_cpp/src/common.h`). GitHub's TLS is validated by Windows; the signature is what authorizes an install.
2. `launcher_version` in the manifest newer than the running launcher -> it downloads `HPMMO_Launcher.exe`
   from the release, swaps itself and restarts.
3. `client_version` different from the installed one -> **delta update**: it fetches `content.json` (its
   sha256 is in the signed manifest), which lists every file as content-defined chunks (~256 KiB,
   `tools/release/chunk_release.py`). Chunks the installed version already has are copied locally; only the
   missing ones are downloaded with HTTP Range requests into the `chunks-<ver>.bin` of the release that first
   published them. Every chunk and every file is checked against its sha256, then the version is activated.
   If anything in that path fails (except a cancel or a full disk) the full zip is installed instead.
   Measured on the real build: v1.0.3 -> v1.0.4 downloaded 26 MB instead of ~500 MB.
4. PLAY starts `HPMMO.exe`; the game opens at its own login screen.

Versions are automatic: client `1.0.<workflow run number>`, launcher `3.0.<unix time of the last commit that
touched launcher_cpp/>`. A release that did not change the launcher does not reinstall it.

Install location: next to the launcher when that folder already holds an install (`current.json`, `versions/`)
or a `portable.txt`; otherwise `%LOCALAPPDATA%\HPMMO`. Player download link:
`https://github.com/semdin/hpmmo-client/releases/latest/download/HPMMO_Launcher.exe`.

**Never delete old GitHub releases**: newer releases reference chunks stored in older releases' `chunks-*.bin`.
The CI keeps the Godot import cache (`.godot`) between runs so unchanged assets re-export byte-identically
(Godot imports are not bit-reproducible; without the cache ~25 MB of models change every release).
`HPMMO_FULL_PACKAGE=1` forces the full zip (diagnostics).

## One-time setup

- Repository secret **`HPMMO_CLIENT_SIGNING_KEY`** (client repo -> Settings -> Secrets and variables -> Actions):
  the release signing private key as PEM text or as the 64-hex Ed25519 seed. Its public half must equal `HPMMO_DEFAULT_RELEASE_KEY`;
  the workflow refuses to publish otherwise. Never commit the private key.
- Workflow permissions: the job asks for `contents: write`; if the repository restricts the default token,
  allow read/write for Actions.

Rotating the key means a new launcher build with the new public key - and launchers already in the field only
trust the old key, so they must be replaced by hand. Keep the private key backed up.

## Maintenance (server deploys)

Push to `hpmmo-server` `main` -> the server workflow deploys with `--countdown 30`:

1. `maintenance.flag` is written (state ANNOUNCING) -> new logins get "Sunucu bakımda"; `/api/status`
   reports `maintenance: true`; the launcher pill turns amber.
2. The world server broadcasts the countdown; every player sees the banner
   ("Sunucu bakımı: 0:30 içinde oyundan çıkarılacaksın") and a chat line, then is saved and disconnected,
   and returns to the login screen with the maintenance notice.
3. The new release is installed and verified (the synthetic check logs in as `HPMMO_SMOKE_USER`, which the gate
   lets through), the flag is removed, logins reopen.

A failed deploy leaves the flag in place (logins stay closed) - by design, see `server/docs/runbook-rollback.md`.
Manual maintenance: create `/opt/hpmmo/state/maintenance.flag` (any content) and delete it to reopen.

## Tests

- `python tools/release/test_updater.py` - launcher updater incl. delta updates (113 checks; build `launcher_cpp/build` first).
- `godot --path client res://scenes/test/ui_menu_capture.tscn` - login screen screenshots in `tools/downloads/`.
