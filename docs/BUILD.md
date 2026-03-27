# Build Guide

This project uses `uv` for local environment management and `scripts/build.py` as the packaging entrypoint.

## Commands

### Sync the local environment

```bash
uv sync
```

### macOS `.app`

```bash
uv run python scripts/build.py macos
```

Choose a specific interpreter if needed:

```bash
uv run python scripts/build.py macos --python /path/to/python3.12
```

Output:

```bash
dist/macos/Keep or Nah.app
```

The macOS app is unsigned.

### Windows `.exe` on Windows

Run this on a real Windows machine:

```bash
uv run python scripts/build.py windows
```

Or choose a specific interpreter:

```bash
uv run python scripts/build.py windows --python C:\path\to\python.exe
```

Output:

```bash
dist/windows/KeepOrNah.exe
```

### Windows `.exe` from macOS via CrossOver

On macOS, the Windows build runs inside a CrossOver bottle:

```bash
uv run python scripts/build.py windows --cx-bottle your-bottle-name
```

If the bottle does not expose Python on PATH, confirm the exact Windows path to
 the interpreter and pass the complete path with `--win-python`:

```bash
uv run python scripts/build.py windows \
  --cx-bottle your-bottle-name \
  --win-python "C:\users\crossover\AppData\Local\Programs\Python\Python312\python.exe"
```

Do not assume `python.exe` is discoverable by name inside the bottle. Confirm
 the interpreter location first.

### Build both from macOS

```bash
uv run python scripts/build.py all --cx-bottle your-bottle-name
```

## Notes

- `packaging/macos.spec` builds the macOS app bundle.
- `packaging/windows.spec` builds the Windows single-file executable.
- `hook-tkinterdnd2.py` is included so the TkDnD runtime files are bundled.
- Build outputs are written under `dist/`.
- Intermediate files are written under `build/`.
- PyInstaller cache is written under `.pyinstaller/`.
