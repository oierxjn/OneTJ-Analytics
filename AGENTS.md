# Repository Agent Rules

- Always use the project virtual environment Python for commands: `.venv\Scripts\python.exe`.
- Do not install dependencies with system Python in this repository.
- When handling Chinese comments/text, always read/write files with UTF-8 encoding (for example, use `-Encoding utf8` in PowerShell) to avoid mojibake.
- Do not remove existing comments just to bypass encoding/garbled-text issues; fix encoding first and preserve comment intent.
