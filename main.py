import os
import tkinter as tk


FORCE_CLASSIC_ENV_VAR = "KEEP_OR_NAH_FORCE_CLASSIC_UI"


def resolve_app_class():
    force_classic = os.environ.get(FORCE_CLASSIC_ENV_VAR) == "1"
    if force_classic or tk.TkVersion < 8.6:
        from classic_gui import ClassicApp

        return ClassicApp

    from gui_app import App

    return App


def main():
    app_class = resolve_app_class()
    app = app_class()
    app.mainloop()


if __name__ == "__main__":
    main()
