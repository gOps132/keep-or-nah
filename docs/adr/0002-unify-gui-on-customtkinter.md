# Consolidate Desktop GUI on CustomTkinter

Maintaining two parallel GUI frontends (`classic_gui.py` using standard Tk/ttk and `gui_app.py` using CustomTkinter) resulted in ~1,300 lines of duplicated logic, fragmented keyboard event handlers, and styling inconsistencies across operating systems. We decided to retire `classic_gui.py` completely and consolidate the entire desktop frontend onto `CustomTkinter` (`gui_app.py`) for consistent dark/light themes and modern widget styling.

## Considered Options

- **Retaining Classic Tkinter/ttk**: Outdated visual aesthetics, poor dark mode support on modern OS platforms, and maintenance overhead of duplicate UI files.
- **Porting to PyQt / PySide or Tauri / Electron**: Substantial rewrite required for all existing Tkinter widgets and canvas drawing code, alongside steep packaging and dependency footprints.
- **Unified CustomTkinter (Chosen)**: Drop-in modernization on top of the established Python Tk event loop, unified keyboard shortcuts, and immediate retirement of ~1,340 lines of duplicate code.

## Consequences

- All desktop UI features and tests now target `gui_app.App` directly.
- Retains standard Tk canvas primitives for high-performance preview zooming and split-compare panning.
