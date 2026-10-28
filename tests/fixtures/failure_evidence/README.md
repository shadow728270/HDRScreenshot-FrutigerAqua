# Prismwake OCR real-world failure evidence

- `01_tall_menu_OCR_50_percent.png`: user screenshot of OCR at 50% on tall menu. A static capture does not prove it froze indefinitely.
- `02_cyan_buttons_recognized_as_symbol.png`: user screenshot of failed OCR on five cyan menu buttons.
- `diagnostic_only_*.png`: crops taken **from the OCR dialog preview**, which has been scaled down and may include overlays. These are not original native-resolution image captures and must not be treated as equivalent evaluation inputs.

Labels visible in screenshot 2: Report Bug / Request Feature; Join us on Discord; Steam Workshop; Video Tutorials; Merch Store. OCR produced only —<.

See the accompanying .md prompt for code-level findings, including a concrete stdout/stderr pipe deadlock risk in `_run_single_tesseract_pass()`.
