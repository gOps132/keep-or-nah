from __future__ import annotations

import gui_app


def resolve_app_class():
    return gui_app.App


def main():
    app = resolve_app_class()()
    app.mainloop()


if __name__ == "__main__":
    main()
