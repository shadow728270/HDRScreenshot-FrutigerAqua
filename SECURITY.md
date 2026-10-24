# Security policy

Prismwake is an early-stage Windows screenshot application using native graphics APIs. Please report possible security vulnerabilities responsibly.

## Reporting security concerns

Avoid posting a proof-of-concept exploit or private data publicly. Contact the repository maintainer through their GitHub profile to arrange a private report if possible. If GitHub private vulnerability reporting is enabled for this repository, use **Security → Report a vulnerability**.

For ordinary bugs or crashes without sensitive details, use [GitHub Issues](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/issues).

## Download and privacy notes

- Download releases only from this repository's official [GitHub Releases](https://github.com/shadow728270/HDRScreenshot-FrutigerAqua/releases) page.
- The initial Windows executable is unsigned and can trigger SmartScreen.
- The Python source code is public. Official builds are produced by the repository's GitHub Actions workflow.
- The application writes settings and optional diagnostics locally under `%APPDATA%\HDRSnip Fusion` (legacy v0.1.2 profile retained for compatibility).
- Screenshots and diagnostic logs can contain private information. Inspect files carefully before uploading them to issues.
