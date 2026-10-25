from __future__ import annotations

import warnings

import gui_app


def resolve_app_class():
    warnings.warn(
        "Keep or Nah has transitioned to a standalone native Rust/Tauri desktop application. "
        "Run 'npm run dev' or launch the native binary instead. "
        "The Python CustomTkinter frontend is deprecated and scheduled for decommissioning.",
        DeprecationWarning,
        stacklevel=2,
    )
    return gui_app.App


def main():
    app = resolve_app_class()()
    app.mainloop()


if __name__ == "__main__":
    main()
