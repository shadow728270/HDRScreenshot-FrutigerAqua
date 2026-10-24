# Contributing to Prismwake

Thanks for helping improve this free Windows screenshot tool.

## Report a bug

Use [GitHub Issues](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/issues). When possible, include:

- Windows version and whether HDR or Auto HDR is enabled.
- GPU model and graphics driver version.
- App version and how you launched it (EXE or Python).
- Expected behavior, actual behavior, and steps to reproduce.
- Whether the problem happens with the app's Diagnostic Safe Mode.

**Privacy:** Before sharing diagnostic logs or screenshots, remove personal information, usernames, file paths, window titles, and anything sensitive. Don't upload crash dumps without checking their contents.

## Suggest a feature

Open a feature-request issue with an explanation of what problem it solves. Requests about HDR color accuracy, capture speed, accessibility, and the interface are welcome.

## Contribute code

1. Open an issue first for significant changes.
2. Fork the repository, branch off `main`, and make a focused change.
3. Use Python 3.10+ on Windows. Install dependencies with `py -m pip install -r requirements.txt`.
4. Test relevant functionality, particularly HDR capture, hotkeys, system tray behavior, and multi-monitor mapping.
5. Open a pull request describing your change and how you tested it.

Don't attach `build/`, `dist/`, local configuration, logs, or large binary files to pull requests. Please keep the native DXGI/COM cleanup rules intact.

## License

Contributions submitted to this project are intended to be distributed under its [MIT License](LICENSE). Only submit code or assets you have permission to contribute.
