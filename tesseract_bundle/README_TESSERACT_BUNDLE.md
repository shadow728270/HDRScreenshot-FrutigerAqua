# Prismwake v0.2.0 — Bundled Offline Tesseract OCR Runtime (`tesseract_bundle/`)

This directory holds the offline Tesseract OCR runtime and language models packaged inside `Prismwake.exe` (`--add-data "tesseract_bundle;tesseract_bundle"`):

- `tessdata/eng.traineddata` — Included directly in this repository/archive (Apache-2.0 License, official Tesseract `tessdata_fast` English model).
- `tessdata/ita.traineddata` — Automatically staged by `build_windows_oneclick.ps1` / `.github/workflows/build-windows.yml` during Windows packaging.
- `tesseract.exe` + dependent Windows `.dll` files — Automatically staged by `build_windows_oneclick.ps1` (or `build_windows_oneclick.bat`) and `.github/workflows/build-windows.yml` when building `dist\Prismwake.exe`.

## Verification
Run:
```powershell
python Prismwake.py --verify-ocr-bundle
# or against the compiled Windows executable:
.\dist\Prismwake.exe --write-ocr-verify-file .\ocr_verify.json
```
to verify that the packaged Tesseract binary launches offline and accurately recognizes a synthetic test screenshot.
