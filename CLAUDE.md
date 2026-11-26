# Atelier Photo — working notes for Claude

Local desktop app (PySide6, Windows + macOS) that **only sorts** photo rushes:
import → scene/variant grouping → automatic keep / review / reject → manual check →
byte-identical export. Editing, cropping and prompt-based edits were removed on
2026-11-25; do not reintroduce rendering code. UI text and docs are in French.

## Rules
- Never `git commit`, `git push`, or offer to: the user commits. Leave changes in the working tree.
- Keep `.gitignore` current when the app or scripts start writing new files.
- Only the repo-root files listed in `scripts/make_mac_transfer.py` ship in source archives (this file does not).

## Commands (PowerShell or Git Bash, from the repo root)
- Tests: `.venv/Scripts/python -m pytest -q --basetemp=test-output/pt -p no:cacheprovider`
  (the system temp folder is not writable for pytest here; `--basetemp` is required).
- Lint: `.venv/Scripts/python -m ruff check atelier scripts tests main.py`
- End-to-end with the real DINOv3 model: `.venv/Scripts/python main.py --self-test test-output/self-test.json`
- `tests/test_windows_uninstall.py` needs `ATELIER_TEST_INSTALLER=1` and Inno Setup in `.build-tools/inno`.

## Map (`atelier/`)
- `imaging.py` — `decode(path)` → analysis copy (PIL RGB, sRGB, oriented, ≤ 1280 px; RAW at half size).
  Damaged data → `CorruptPhoto`; unreadable → `ValueError`; disk errors stay `OSError` (resumable).
  `features(image)` → 8 technical measures (`selection.TECH_KEYS`). Same pixels as before the
  refactor, so stored vectors and the bundled selector stay valid.
- `dino.py` — DINOv3 ViT-S/16 ONNX, 448×448, 384-d L2-normalised `pooler_output`. `encoder.version`
  includes model hashes; vectors of different versions are never mixed.
- `analysis.py` — `propose` (per photo: technical verdict, reference similarity, nearby feedback),
  `finalize` (per batch: scenes, scores, `decide`), `reselect` (recompute, keep manual decisions).
  References add `2 × std(scores) × similarity`; similarity ≥ `CLOSE_REFERENCE` (.82) is shown.
- `selection.py` — scenes, 400-d design matrix, Newton logistic regression, keep/review budgets.
- `training.py` — `match` kept photos to rush originals, `learn` → selector only.
- `pipeline.py` — job creation + `run_job` (runs in a spawned process): analysis, training,
  selection, export, recovery. `export_one` = exclusive name reservation, temp file + fsync +
  `os.replace`, digest checks, sidecars via `xmp.companions`. `quarantine` moves damaged files
  (and their `.xmp` / `.nef.xmp`) into `Photos corrompues/`.
- `store.py` — SQLite (`SCHEMA_VERSION = 8`, kept unchanged on purpose). Older libraries may hold
  `filter_enabled` / `crops_enabled` columns, edit fields in photo/feedback JSON and
  `profiles/<p>/training/<reportage>/` sample folders: all ignored (folders deleted when their
  reportage is removed). Batches store a frozen `snapshot` (references, feedback, selector).
- `app.py` / `workspace_ui.py` — main window, `PhotoViewer` (keys 1/2/3 decide, then next photo).
  Preview = `profiles/<p>/batches/<b>/<photo>.png` loaded directly; thumbnails `.jpg`.
- `help_ui.py` (quick guide + advanced help), `help_reference.py` (technical reference).

## Docs that must stay in sync
- `atelier/help_reference.py` `REFERENCE` == `docs/FONCTIONNEMENT_DETAILLE.md` (test enforced).
  After editing the reference, regenerate the copy with CRLF endings:
  `Path('docs/FONCTIONNEMENT_DETAILLE.md').write_text(REFERENCE.lstrip(), encoding='utf-8', newline='\r\n')`.
- `README.md` (user-facing install/usage), `LIRE SUR MAC.md`, `packaging/macos/INSTALLER.html`,
  `THIRD_PARTY_NOTICES.md` + `requirements-tested.txt` + `pyproject.toml` for dependencies.
- `atelier/assets/default_profile.json` must pass `scripts/distribution_assets.verify_distribution_assets`
  (selector numbers only, no names, paths or corpus counts).

## Test conventions
- Tests use fake encoders (`encode` = normalised mean colour) and `run_job(..., workers)` in-process.
- Fake `stats` dicts in tests carry exactly the 8 `TECH_KEYS`.
- To force a variant choice by references, use a neutral selector: the heuristic's
  "sharpest frame" bonus otherwise dominates.
