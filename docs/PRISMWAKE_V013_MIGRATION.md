# Prismwake v0.1.3: rebrand and backward-compatible upgrade contract

**Status: released October 24, 2026.** [Prismwake v0.1.3](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/tag/v0.1.3) is the current public stable release. The code, real Windows executable replacement tests, and both executable hashes passed GitHub Actions validation. The original v0.1.2 updater asset name and GitHub repository path remain supported.

## Why the old GitHub repository slug must remain active

The shipped v0.1.2 executable hardcodes all of the following:

| Contract | Exact v0.1.2 value | Implication |
|---|---|---|
| GitHub owner | `shadow728270` | The current client queries this owner's official Releases API. |
| GitHub repository | `HDRScreenshot-FrutigerAqua` | The client validates release and asset URL path prefixes against this exact name. |
| Releases API | `https://api.github.com/repos/shadow728270/HDRScreenshot-FrutigerAqua/releases/latest` | The original route must continue returning a valid stable release. |
| Required release asset | `HDRSnipFusion.exe` | The original client searches for an exact filename and ignores other EXEs. |
| Installed target | path of the currently executing `HDRSnipFusion.exe` | The staged updater replaces *that actual path*, preserving rollback. |
| Config folder | `%APPDATA%\HDRSnip Fusion` | Existing preferences, hotkeys, screenshot paths, and update metadata are here. |
| Staging folder | `%LOCALAPPDATA%\HDRSnip Fusion\updates` | In-flight update transactions must not be lost. |
| Startup Run value | `HDRSnipFusion` | Older startup entries may exist on user machines. |

v0.1.2 also requires the asset's uploaded state, a bounded plausible size, an HTTPS trusted-domain URL, and a 64-character SHA-256 from GitHub's asset digest and/or the release notes. It rejects digest conflicts. A *repository rename* may redirect the HTTP request, but the returned release and asset URLs can be rewritten to the **new** path, which v0.1.2 rejects. **Do not rename or delete this repository as part of v0.1.3.** Keep it as the stable legacy updater channel. Branding and future distribution can use "Prismwake" without changing the API path.

## Required v0.1.3 distribution strategy

1. Implement the desktop visual/user-facing rebrand to **Prismwake**, bumping `APP_VERSION` to `0.1.3`.
2. Build a real x64 PyInstaller `--onefile --windowed` executable named `Prismwake.exe` for fresh downloads **and also publish the exact same tested binary bytes** under the compatibility asset name `HDRSnipFusion.exe`.
3. Include distinct SHA-256 checksum sidecar files for **both** names, or write unambiguous digest metadata supported by the app. The legacy asset's `digest` must match the actual bytes. The release notes must never present a contradictory digest. GitHub's native asset digest is authoritative when present.
4. Publish a stable `v0.1.3` GitHub release **on this unchanged repository** with both EXE assets uploaded before announcing the release complete. Verify old clients parse the legacy asset and new clients choose the Prismwake asset.
5. Do **not** require immediate executable renaming on existing installations. When v0.1.2 updates, its known-good updater helper will replace its existing `HDRSnipFusion.exe` path with v0.1.3's bytes and restart that same path. The process may still be named `HDRSnipFusion.exe` until a separately tested, optional installer/migration renames it.
6. A fresh manual download may use `Prismwake.exe` and its own app-branded window titles. The app's updater must determine the currently installed target from the **actual executable path**, never assume the new filename.
7. Do not destructively move `%APPDATA%\HDRSnip Fusion`, overwrite preferences, or wipe `%LOCALAPPDATA%\HDRSnip Fusion\updates`. Implement an atomic, idempotent copy-forward configuration migration if using `Prismwake` paths for fresh installs. Reuse the legacy paths for upgraded installs until old in-flight transactions have finished.
8. Preserve the existing staged-update helper's file-lock, parent/bootloader PID, SHA-256 validation, startup confirmation, backup, rollback, active-transaction and clean-up logic. Preserve legacy Windows Start-with-Windows registry value behavior and migrate only after validation without orphaning duplicate entries.
9. Ensure **v0.1.3 checking for v0.1.4** also accepts compatible alias filenames and expected repository URLs without allowing unrelated repositories, untrusted redirects, arbitrary exe destinations, or downgrades. No weakening of integrity verification.
10. Use the same release tag and executable content version, and verify `Prismwake.exe` and `HDRSnipFusion.exe` are byte-identical. `Prismwake.exe.sha256` and `HDRSnipFusion.exe.sha256` should contain the appropriate asset filename but equal digests.

## Editor scope for v0.1.3

- **Blur and pixelate:** adjustable intensity and brush/rectangular mode. Apply to the final export pixels, including clipboard, without destructive changes to the underlying captured frame before export.
- **Permanent redaction:** a separate tool that irreversibly replaces obscured pixels in the exported output and does not serialize exposed original pixels into metadata, alpha, or editable data. Make a clear UI distinction between reversible blur and permanent redaction.
- **Pixel magnifier and eyedropper:** show a crisp nearest-neighbor enlarged selection of pixels, HEX/RGB for standard exported content, and luminance values only when grounded in the true HDR source metadata/data. Respect multi-monitor DPI.
- **Numbered callouts:** 1, 2, 3... labels with color/size styling, undo/redo, movement when supported.
- Keep existing pen/line/rect/ellipse/arrow/text, stroke thickness, non-destructive Paint Bucket, HDR tone mapping, overlay and hotkeys functioning.

## Mandatory test matrix before publication

- Legacy **v0.1.2** running as `HDRSnipFusion.exe` sees the stable v0.1.3 release as `update_available`, downloads the old-name asset, verifies SHA-256 and size, stages, installs, restarts and confirms, then preserves preferences and screenshots.
- v0.1.3 launched from **either name** detects v0.1.4 when available without false updates on current version or prereleases.
- v0.1.2 rejects a v0.1.3 release if it has only `Prismwake.exe` and no legacy asset: this negative test is intentional.
- Reject mismatching digest, invalid or missing asset size, wrong GitHub repository URL, non-HTTPS or off-domain redirects, and a tampered staged executable.
- Simulate an interrupted update, hung child/bootloader, locked target, and launch failure: clean rollback without deleting user data.
- Exercise installed/startup config migration from an existing v0.1.2 profile and a fresh Prismwake profile.
- Verify Windows x64 PyInstaller build produces **both aliases** and compatible version metadata; prevent publishing tag/release if either asset or checksum is absent.
- Regression test editor tools on SDR/HDR, multi-monitor and mixed-DPI captures; include screenshots in bug reports only after redacting private information.

## Deployment sequence (completed for v0.1.3)

1. Commit/test v0.1.3 implementation in a development branch; verify locally and with GitHub Actions.
2. Update the current Windows release workflow to build/test both executable names and preserve rollback checks.
3. User confirmed that attached Python updates are already tested and approved through their development workflow.
4. Only then tag `v0.1.3` on this original repository. Confirm the GitHub release includes both aliases/checksums and that the actual old v0.1.2 updater accepts its metadata.
5. Update the website's default download to `Prismwake.exe` **after** the tagged release is verified; retain the legacy download link indefinitely.
6. Consider repository slug migration **only** as a separate later task with a durable, validated old-API compatibility bridge. An ordinary GitHub redirect is insufficient for the shipped v0.1.2 URL allowlist.

This file exists to prevent an aesthetically pleasant rebrand from silently breaking live user installations.

## Release verification

- Official stable release: https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases/tag/v0.1.3
- Both EXE aliases use SHA-256 `959bc75e50ddccf0eff424b7559873c84834a8ccd2483f23047233e774bd0439`.
- v0.1.2 compatibility checks and v0.1.3 staged executable startup/rollback tests passed.
- The original repository is preserved as the update channel; newly published downloads use `Prismwake.exe`.
