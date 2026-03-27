# Platform Notes

## macOS

- On macOS with older Tk builds, the app falls back to the standard `tkinter`
  interface instead of `CustomTkinter`.
- If you see startup or rendering issues, use a Python build linked against
  Tk 8.6 or newer.

## Windows

- Native Windows packaging is supported through `scripts/build.py windows`.
- CrossOver-based Windows packaging from macOS is also supported, but it
  requires a bottle with a working Windows Python installation.
