# Launcher, client releases and maintenance

## What each piece does

| Piece | Job |
|---|---|
| `ThousandRealms_Launcher.exe` (`launcher_cpp/`) | Checks for updates, updates itself and the game, starts the game. **No login.** |
| Game login screen (`scenes/main/main_menu.tscn`, `scripts/ui/main_menu.gd`) | Sign in / create an account, then world join and character selection. |
| `.github/workflows/client-release.yml` | Every push to `main`: exports the game, builds the launcher, signs a manifest, publishes GitHub Release `v1.0.<run>` (marked latest). |
| Account service `/api/status`, maintenance gate (`server/services/cpp`) | Reports ONLINE / maintenance; refuses `/api/login` and `/api/game-ticket` with 503 `code=maintenance` while `maintenance.flag` exists. |
| Deploy controller (`server/deploy/hpmmo_deploy.sh`) | Writes `maintenance.flag` when it announces the 30 s countdown, removes it once the new server release is verified ONLINE. |

## Update flow

1. The launcher fetches `https://github.com/semdin/hpmmo-client/releases/latest/download/manifest.json` and `.sig`
   and verifies the Ed25519 signature with the key built into it (`HPMMO_DEFAULT_RELEASE_KEY` in
   `launcher_cpp/src/common.h`). GitHub's TLS is validated by Windows; the signature is what authorizes an install.
2. `launcher_version` in the manifest newer than the running launcher -> it downloads the launcher the manifest
   names (`ThousandRealms_Launcher.exe`), swaps itself and restarts.
3. `client_version` different from the installed one -> **delta update**: it fetches `content.json` (its
   sha256 is in the signed manifest), which lists every file as content-defined chunks (~256 KiB,
   `tools/release/chunk_release.py`). Chunks the installed version already has are copied locally; only the
   missing ones are downloaded with HTTP Range requests into the `chunks-<ver>.bin` of the release that first
   published them. Every chunk and every file is checked against its sha256, then the version is activated.
   Since 1.0.64 releases ship chunks only: a failure in that path is the update's error (the full-zip fallback
   is used only by a release that still carries a zip).
   Measured on the real build: v1.0.3 -> v1.0.4 downloaded 26 MB instead of ~500 MB.
4. PLAY starts `ThousandRealms.exe`; the game opens at its own login screen.

Versions are automatic: client `1.0.<workflow run number>`, launcher `3.0.<unix time of the last commit that
touched launcher_cpp/>`. A release that did not change the launcher does not reinstall it.

Install location: next to the launcher when that folder already holds an install (`current.json`, `versions/`)
or a `portable.txt`; otherwise `%LOCALAPPDATA%\ThousandRealms` (`~/.local/share/ThousandRealms`, `~/Library/Application Support/ThousandRealms`).
Player download link:
`https://github.com/semdin/hpmmo-client/releases/latest/download/ThousandRealms_Launcher.exe`.

**Chunk source window - never delete the last 30 releases**: a release's `content*.json` references chunks only
in the `chunks-*.bin` of the last 30 client versions, counting itself (`CHUNK_SOURCE_WINDOW` in
`tools/release/release_common.py`, `chunk_release.py --source-window`). A chunk whose only published copy is older
is re-packed into the new release's own bin, and `gen_manifest.py --verify` refuses a content index that points
outside the window. So the latest release depends on at most the 29 releases before it: those must stay; anything
older may be deleted. Cost: when the bulk of the game ages out of the window one release re-uploads it (about one
compressed build per platform, ~0.85 GB each), at most once per 30 releases; players download nothing extra
(chunks are matched by hash, so a re-packed chunk they already have is copied locally).
The CI keeps the Godot import cache (`.godot`) between runs so unchanged assets re-export byte-identically
(Godot imports are not bit-reproducible; without the cache ~25 MB of models change every release).
`HPMMO_FULL_PACKAGE=1` forces the full zip (diagnostics); on a chunk-only release the update/repair stops at once
with a config error (exit 3) that says so. `HPMMO_UpdaterCLI --update --stop-after download|verify|stage` goes
through the chunk path: `download` stops once every missing chunk is in `staging/chunks`, `verify` once the
verified files are staged in `versions/<ver>.tmp`, `stage` once the activation journal is written as well.

A repair that fails (`Dosyaları onar`) ends in the failed state with its reason; the launcher never reports
"Oyun hazır" after it, since the following check only compares versions.

## Rename from HPMMO (2026-11)

The game shipped as "HPMMO" until 1.0.x of November 2026. Everything a player sees on disk now carries the
game's name; installs from before move over by themselves:

| Before | Now |
|---|---|
| `HPMMO_Launcher.exe`, `HPMMO_Launcher-x86_64.AppImage`, `HPMMO Launcher.app` | `ThousandRealms_Launcher.exe`, `ThousandRealms_Launcher-x86_64.AppImage`, `Thousand Realms Launcher.app` |
| `HPMMO.exe` + `HPMMO.pck`, `HPMMO.x86_64`, `HPMMO.app` | `ThousandRealms.exe` + `ThousandRealms.pck`, `ThousandRealms.x86_64`, `Thousand Realms.app` |
| `%LOCALAPPDATA%\HPMMO` (and the Linux/macOS equivalents) | `%LOCALAPPDATA%\ThousandRealms` |
| `application/config/name="HPMMO"`: user data in `…/app_userdata/HPMMO` | `"Thousand Realms"`: `…/app_userdata/Thousand Realms` |

- **Releases** publish the launchers under both names (byte-identical copies under the old names), so old
  download links keep working. The manifests name the new files; an old launcher self-updates from whatever URL
  its manifest gives and writes the new binary over its own file, which still has the old name.
- **The new launcher, on start** (`launcher_cpp/src/legacy_names.cpp`, before the config is read): a file still
  called `HPMMO_Launcher*` (or a bundle `HPMMO Launcher*.app`) renames itself in place unless the new name
  exists; Windows `.lnk` files on the Desktop, in the Start menu and in the taskbar/Start pins that pointed at it
  are retargeted (desktop/Start menu entries with HPMMO in the name become `Thousand Realms.lnk`); Linux
  `.desktop` files in `~/.local/share/applications` and on the desktop are rewritten. The macOS Dock follows a
  bundle rename by itself.
- **The install folder** (`MigrateLegacyInstallRoot`, `launcher_cpp/src/updater.cpp`): the default
  `<data>/HPMMO` is renamed to `<data>/ThousandRealms` in one step (versions, `current.json`,
  `launcher_state.json`, `user/`, logs). While the game runs from it, an activation is pending or a file is held
  open, the old folder is used and the move is tried on the next start. Portable installs and an explicit
  `install_root` stay where they are. The installed old version (`HPMMO.exe`) keeps starting until the next
  update, which downloads nothing extra for the rename: chunks are matched by content, not by file name.
- **Game data** (`scripts/autoload/user_data_migration.gd`, first autoload): copies `…/app_userdata/HPMMO`
  into the new `user://` once (settings, saved login, quick slots, bag layout, looks, …; never overwrites;
  logs and GPU caches stay behind) and leaves the old folder for a rollback. The world server's project gets
  the same name and autoload through `dev.ps1 sync-world`, so its `user://` (local saves) moves the same way.
- Unchanged, because no player sees them: `HPMMO_*` environment variables, `HPMMO_UpdaterCLI`, the Windows
  mutex/window class, bundle ids, the `hpmmo-client` repository.

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
