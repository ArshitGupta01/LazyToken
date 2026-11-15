# Windows CLI release procedure

No public release is currently verified. The GitHub latest-release endpoint returned 404 during this session. These steps prepare distribution; they do not authorize publication.

1. Run the unit suite and inspect all changes. Confirm version in `kn.VERSION`.
2. Build on Windows x64 with Python 3.14.10 or newer in the 3.14 series, OpenSSL 3.5.9 or newer in the 3.5 LTS series, PyInstaller 6.19.0 and tokenizers 0.23.3: `powershell -NoProfile -File build_release.ps1 -Output release/cli-candidate`. Review these minimums when security fixes are released. OpenSSL 3.0 reached end of public support on September 7, 2026: <https://openssl-library.org/post/2026-09-16-eol30/>. Existing local candidates built with Python 3.11.9 and OpenSSL 3.0.13 must not be published.
3. Run `python tests/smoke_release.py release/cli-candidate`. Test the verified local zip through `install.ps1 -PackagePath ... -ExpectedSha256 ...`, including update/rollback/uninstall in an isolated directory and PATH store.
4. Inspect licenses/notices and complete a clean-machine test with no separately installed Python/Node. Test disconnected core use, external MCP clients and interrupted update recovery. Sign the executable/bootstrap if a trusted publisher identity is available; regenerate manifests/checksums after signing.
5. With explicit user authorization, create the matching version tag and GitHub Release. Upload `lazytoken-vVERSION-windows-x64.zip`, `bootstrap.ps1` and `SHA256SUMS`. The zip contains the runtime plus the managed local install helper; bootstrap is a self-contained download installer. CI only uploads build artifacts, never creates a release.
6. Verify GitHub reports the zip asset's `digest` as SHA-256 and that it equals the independently checked local hash. The bootstrap refuses a missing digest. Test installation pinned to the exact published tag. Publish a copyable installation command only after the endpoint and artifact checks actually pass.

The bootstrap is itself executable code: users should download the versioned file, verify its checksum/signature through a trusted channel, inspect it and execute it. Do not recommend an unverified mutable remote script. HTTPS/GitHub asset digests provide channel integrity, not protection against publisher account compromise. No signing key or independent trust root is embedded yet.

Data lives outside the managed app directory. App rollback changes binaries, not database schema; restore a verified pre-upgrade backup to a new directory when an older binary refuses a newer schema. Never replace a live database. Update validates a new version before selecting it and retains the previous version. Uninstall preserves data; client cleanup is explicit and refuses newer edits.

Earlier local candidates include an older bootstrap that only accepts the Python 3.11 runtime DLL. To upgrade one of those installations to a Python 3.14 package, use the newly verified bootstrap with `-Upgrade` and the existing install root; after that, the managed update path uses the updated bootstrap. Test this transition before release.

Rollback also verifies the previous package against its saved file manifest before changing version markers. A damaged or missing executable, support file or manifest must leave the current version selected. Setup regression checks must include edits during indexing and a failed recovery-receipt write; these use temporary client configurations only.
