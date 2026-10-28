# Independent OCR regression fixtures for Prismwake v0.2.0

These 6 synthetic fixtures were independently authored for reviewing the new OCR pipeline. They are deliberately different from Gemini’s original 12 benchmarks. They are **not** images from the user's original game screenshots. Their intended visible text is listed in `ground_truth.json`.

Test the images unmodified, offline and without hardcoded expected phrases in production code.

Main findings with the v0.2.0-complete(4) ZIP, on this Linux host using real Tesseract:

- `new_game_menu`: expected four menu labels without icons; new OCR returns additional `O` before `Settings` and `Leave Lobby`. Current new pipeline CER ~9.5%, whereas the included *reconstructed legacy comparison function* produces clean text. (Note: the actual prior ZIP may behave differently; do not equate the reconstructed comparator with the shipped build.)
- `keep_leading_I`: expected `I LOVE LOGS`, new OCR outputs `| LOVE LOGS`. Actual prior ZIP also misread the `I` on this fixture, so this is not proven to be a newly introduced bug.
- The other four samples were recognized exactly in this local run.

The 12/12 performance reported by Gemini on its synthetic training/development fixtures is reproducible but NOT evidence of 100% real-world accuracy. Test novel icons, fonts, backgrounds, and actual uncropped full-resolution captured image pixels.
