# v0.4.3 review fixes

The starting tree was clean at `cbdfb555543c21a1952172e17b2a6aa940a7418a`. These are focused corrections to the existing implementation, not execution of the full remaining-work roadmap. No database schema, MCP tool names or approval boundaries changed.

| Finding                                                  | Status | Regression evidence                                                                                                                                                                       |
| -------------------------------------------------------- | ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Setup overwrites settings changed during indexing        | Done   | An intervening edit is preserved and setup refuses the write. An edit to a later client also restores the earlier setup write.                                                            |
| Failed receipt creation leaves setup partly applied      | Done   | A simulated receipt-write failure restores exact existing bytes and removes configurations that did not originally exist.                                                                 |
| Empty, punctuation-only and single-letter searches crash | Done   | Each returns an empty result with project scope and records retrieval statistics successfully.                                                                                            |
| Rollback selects a damaged previous package              | Done   | Corrupt executable, missing support file and invalid manifest are each rejected without changing either version marker. Restoring valid files allows rollback.                            |
| First graph edge hides a stronger connection             | Done   | The strongest selected-project connection wins in either weight order. Stronger edges from another project and second-hop neighbors stay excluded; results contain no duplicate neighbor. |
| Doctor reports malformed client configuration as valid   | Done   | Both client adapters reject non-object server collections and LazyToken entries. Existing valid remote registration objects remain preserved.                                             |

`onboarding.py` checks configuration bytes immediately before each setup write and includes receipt creation in its existing recovery block. Shape validation is shared by preview and diagnostics. `features.py` preserves project scope for empty results and selects each graph neighbor's strongest permitted edge before reading its metadata. `manage_install.ps1` reuses the existing package verifier before rollback selection.

## Verification

`python -m unittest discover -s tests -p test_*.py`: **100 tests, 99 passed, one skipped**, no failures. Tests use temporary stores, synthetic knowledge, temporary client profiles and temporary installation fixtures. The Windows symlink test requires privileges unavailable in this environment. The three Node workspace race checks run through the Python suite when Node is available.

The fresh Windows x64 v0.4.3 candidate was built with PyInstaller 6.19.0, Python 3.11 and tokenizers 0.19.1 in `release/review-fixes-candidate`. `python tests/smoke_release.py release/review-fixes-candidate` passed: bundled runtime, offline configured tokenizer, pending checkpoint, MCP, dashboard/3D assets, background synchronization, verified installation, rejected-update recovery, update, rollback, uninstall and preserved isolated data. Python and Node were absent from the child PATH; the real user PATH was checked unchanged.

Archive SHA-256: `17fcb0bc74d650db68c1babf94f30253faf972aca4cb25f42f808e832beecb4f`. Older candidates were retained. Formatter, installer syntax, whitespace and updated documentation-link checks passed. These checks do not verify a clean machine, real client loading or distribution readiness.

## Boundaries and remaining work

Configuration guards do not coordinate independent editors using a common lock. Keep client configuration editors idle during setup and rollback; file writes still use atomic replacement and guarded recovery. This iteration does not install, migrate or test against the user's real database, settings or PATH.

The next roadmap milestone remains an independently reviewed retrieval dataset and deterministic offline comparisons. It is not completed by these regression tests. Real agent benchmarks, public publishing, signing, clean Windows VM validation, client loading, and physical-device/accessibility checks remain separate work. No provider-token savings are claimed, and no push or public release is part of this iteration.
