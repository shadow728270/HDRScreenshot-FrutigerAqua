# Prismwake v0.2.0 | History OCR status polish

The **OCR** thumbnail badge is now drawn only when the capture contains indexed recognized text. The History OCR card distinguishes **Not indexed**, **Indexing…**, **No text found**, **OCR failed**, and **N words**.

When text is not indexed, a small Aqua **Run OCR** button appears in the OCR panel. Following an unsuccessful or empty recognition attempt it becomes **Retry OCR**. When OCR is running, the button disappears and the status shows **Indexing…**. Text and gallery metadata update automatically after the background jobs finish; History does not need to be reopened.

The existing **Copy Text** button still starts OCR when necessary, and copies the result when available. It does not auto-copy ordinary background-indexed screenshots. OCR remains fully local and the existing neural/Tesseract recognition engine is not changed.

Only `history/storage.py` was modified in the app. `tests/test_history_ocr_status.py` adds two targeted regression checks for OCR status progression and duplicate job suppression. The other 97 baseline project files are carried over unchanged from `Prismwake_v020_Windows_Smoke_Frame_Lifetime_Fix_Full.zip`.

## Test on Windows

After replacing `history/storage.py`, you can run the fast tests with:

```bat
.venv_build\Scripts\python.exe -m unittest discover -s tests -p test_history_ocr_status.py -v
```

Then start Prismwake, take a normal screenshot, open History promptly, and check that the OCR card displays **Indexing…**, updates to recognized words if found, and enables **Run OCR** / **Retry OCR** when recognition has not run or found no text. Confirm the OCR badge appears only for successfully indexed captures.

Build the EXE only after this visual check. No GitHub release was made. Native Windows PyQt6 visuals were not available for verification in the review environment.
