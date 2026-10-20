"""Keyboard shortcuts for the desktop GUI.

The bindings are installed on the application root so they work no matter
which widget has focus, except while a text entry has focus: typing a
filename must not be read as a triage decision.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree.
"""

from __future__ import annotations

import sys
import tkinter as tk


class ShortcutsMixin:
    """Keyboard bindings and the handlers behind them."""

    def bind_shortcuts(self):
        self.bind_all("<Left>", self.handle_previous_shortcut)
        self.bind_all("<Right>", self.handle_next_shortcut)
        self.bind_all("<KeyPress-a>", self.handle_nah_shortcut)
        self.bind_all("<KeyPress-d>", self.handle_keep_shortcut)
        self.bind_all("<KeyPress-f>", self.handle_flag_shortcut)
        self.bind_all("<KeyPress-F>", self.handle_flag_shortcut)
        self.bind_all("<space>", self.handle_space_shortcut)
        self.bind_all("<Delete>", self.handle_delete_shortcut)
        self.bind_all("<KeyPress-c>", self.handle_compare_shortcut)
        self.bind_all("<KeyPress-C>", self.handle_compare_shortcut)
        self.bind_all("<KeyPress-1>", self.handle_compare_pick_1_shortcut)
        self.bind_all("<KeyPress-2>", self.handle_compare_pick_2_shortcut)

        modifier = "Command" if sys.platform == "darwin" else "Control"
        self.bind(f"<{modifier}-z>", self.handle_undo_shortcut)
        self.bind(f"<{modifier}-Z>", self.handle_undo_shortcut)
        self.bind(f"<{modifier}-minus>", self.handle_zoom_out_shortcut)
        self.bind(f"<{modifier}-equal>", self.handle_zoom_in_shortcut)
        self.bind(f"<{modifier}-plus>", self.handle_zoom_in_shortcut)
        self.bind(f"<{modifier}-0>", self.handle_zoom_reset_shortcut)
        self.bind(f"<{modifier}-comma>", self.handle_open_preview_settings_shortcut)

    def bind_if_supported(self, widget, sequence: str, handler):
        try:
            widget.bind(sequence, handler)
        except tk.TclError:
            return

    def handle_undo_shortcut(self, _event=None):
        self.undo_last_action()

    def handle_previous_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.navigate_selection(-1)
        return "break"

    def handle_next_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.navigate_selection(1)
        return "break"

    def handle_nah_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("nah")
        return "break"

    def handle_keep_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("keep")
        return "break"

    def handle_flag_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("flag")
        return "break"

    def handle_space_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("keep")
        return "break"

    def handle_delete_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.sort_current_photo("nah")
        return "break"

    def handle_compare_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        self.toggle_compare_mode()
        return "break"

    def handle_compare_pick_1_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        if getattr(self, "compare_mode", False):
            self.pick_compare_candidate(1)
            return "break"
        return None

    def handle_compare_pick_2_shortcut(self, _event=None):
        if not self.shortcuts_enabled():
            return None
        if getattr(self, "compare_mode", False):
            self.pick_compare_candidate(2)
            return "break"
        return None

    def handle_zoom_in_shortcut(self, _event=None):
        self.zoom_in()

    def handle_zoom_out_shortcut(self, _event=None):
        self.zoom_out()

    def handle_zoom_reset_shortcut(self, _event=None):
        self.reset_zoom()

    def handle_open_preview_settings_shortcut(self, _event=None):
        self.open_preview_settings_dialog()
        return "break"

    def shortcuts_enabled(self) -> bool:
        focused = self.focus_get()
        if focused is None:
            return True
        widget_class = focused.winfo_class()
        return widget_class not in {"Entry", "TEntry", "Text", "Spinbox", "TSpinbox"}
