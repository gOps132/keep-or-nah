"""The widget tree of the desktop GUI.

This module builds the frames, buttons, canvases, and menu of the `App`. The
tree is created against `self`, so the `App` stays the single owner of
every widget and no widget is ever re-parented.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree.
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

import customtkinter as ctk


class LayoutMixin:
    """Construction of the `App` widget tree."""

    def setup_body(self):
        self.control_bar = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.control_bar.grid(row=0, column=0, padx=18, pady=(18, 10), sticky="ew")
        self.control_bar.grid_columnconfigure((0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10), weight=1)

        self.source_button = ctk.CTkButton(
            self.control_bar, text="Source", command=self.choose_source_folder
        )
        self.source_button.grid(row=0, column=0, padx=(0, 8), sticky="ew")

        self.keep_folder_button = ctk.CTkButton(
            self.control_bar, text="Keep", command=self.choose_keep_folder
        )
        self.keep_folder_button.grid(row=0, column=1, padx=8, sticky="ew")

        self.nah_folder_button = ctk.CTkButton(
            self.control_bar, text="Nah", command=self.choose_nah_folder
        )
        self.nah_folder_button.grid(row=0, column=2, padx=8, sticky="ew")

        self.action_mode = ctk.CTkSegmentedButton(
            self.control_bar,
            values=["move", "copy"],
            variable=self.action_mode_var,
            command=self.handle_action_mode_change,
        )
        self.action_mode.grid(row=0, column=3, padx=8, sticky="ew")

        self.undo_button = ctk.CTkButton(
            self.control_bar, text="Undo", command=self.undo_last_action
        )
        self.undo_button.grid(row=0, column=4, padx=8, sticky="ew")

        self.load_button = ctk.CTkButton(self.control_bar, text="Load", command=self.load_queue)
        self.load_button.grid(row=0, column=5, padx=8, sticky="ew")

        self.toggle_actions_button = ctk.CTkButton(
            self.control_bar,
            text="Hide Buttons",
            command=self.toggle_action_buttons,
        )
        self.toggle_actions_button.grid(row=0, column=6, padx=8, sticky="ew")

        self.compare_mode_button = ctk.CTkButton(
            self.control_bar,
            text="2-Up (C)",
            width=72,
            command=self.toggle_compare_mode,
        )
        self.compare_mode_button.grid(row=0, column=7, padx=8, sticky="ew")

        self.zoom_out_button = ctk.CTkButton(
            self.control_bar, text="-", width=44, command=self.zoom_out
        )
        self.zoom_out_button.grid(row=0, column=8, padx=(8, 4), sticky="ew")

        self.zoom_fit_button = ctk.CTkButton(
            self.control_bar, text="Fit", width=60, command=self.reset_zoom
        )
        self.zoom_fit_button.grid(row=0, column=9, padx=4, sticky="ew")

        self.zoom_in_button = ctk.CTkButton(
            self.control_bar, text="+", width=44, command=self.zoom_in
        )
        self.zoom_in_button.grid(row=0, column=10, padx=(4, 0), sticky="ew")

        self.preview_host = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.preview_host.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="nsew")
        self.preview_host.grid_columnconfigure(0, weight=1)
        self.preview_host.grid_rowconfigure(0, weight=1)

        canvas_color = self.resolve_canvas_color()
        self.preview_canvas = tk.Canvas(
            self.preview_host,
            bg=canvas_color,
            bd=0,
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", self.handle_preview_configure)
        self.preview_canvas.bind("<MouseWheel>", self.handle_mousewheel)
        self.preview_canvas.bind("<Shift-MouseWheel>", self.handle_shift_mousewheel)
        self.preview_canvas.bind("<Button-4>", self.handle_linux_wheel)
        self.preview_canvas.bind("<Button-5>", self.handle_linux_wheel)
        self.preview_canvas.bind("<Shift-Button-4>", self.handle_linux_shift_wheel)
        self.preview_canvas.bind("<Shift-Button-5>", self.handle_linux_shift_wheel)
        self.preview_canvas.bind("<ButtonPress-1>", self.start_pan)
        self.preview_canvas.bind("<B1-Motion>", self.drag_pan)

        self.bind_if_supported(
            self.preview_canvas, "<Command-MouseWheel>", self.handle_zoom_mousewheel
        )
        self.bind_if_supported(
            self.preview_canvas, "<Control-MouseWheel>", self.handle_zoom_mousewheel
        )
        self.bind_if_supported(
            self.preview_canvas, "<Control-Button-4>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(
            self.preview_canvas, "<Control-Button-5>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(
            self.preview_canvas, "<Command-Button-4>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(
            self.preview_canvas, "<Command-Button-5>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(self.preview_canvas, "<Magnify>", self.handle_magnify)

        self.compare_canvas = tk.Canvas(
            self.preview_host,
            bg=canvas_color,
            bd=0,
            highlightthickness=0,
            xscrollincrement=1,
            yscrollincrement=1,
        )
        self.compare_canvas.bind("<Configure>", self.handle_preview_configure)
        self.compare_canvas.bind("<MouseWheel>", self.handle_mousewheel)
        self.compare_canvas.bind("<Shift-MouseWheel>", self.handle_shift_mousewheel)
        self.compare_canvas.bind("<Button-4>", self.handle_linux_wheel)
        self.compare_canvas.bind("<Button-5>", self.handle_linux_wheel)
        self.compare_canvas.bind("<Shift-Button-4>", self.handle_linux_shift_wheel)
        self.compare_canvas.bind("<Shift-Button-5>", self.handle_linux_shift_wheel)
        self.compare_canvas.bind("<ButtonPress-1>", self.start_pan)
        self.compare_canvas.bind("<B1-Motion>", self.drag_pan)

        self.bind_if_supported(
            self.compare_canvas, "<Command-MouseWheel>", self.handle_zoom_mousewheel
        )
        self.bind_if_supported(
            self.compare_canvas, "<Control-MouseWheel>", self.handle_zoom_mousewheel
        )
        self.bind_if_supported(
            self.compare_canvas, "<Control-Button-4>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(
            self.compare_canvas, "<Control-Button-5>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(
            self.compare_canvas, "<Command-Button-4>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(
            self.compare_canvas, "<Command-Button-5>", self.handle_linux_zoom_wheel
        )
        self.bind_if_supported(self.compare_canvas, "<Magnify>", self.handle_magnify)

        self.queue_host = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.queue_host.grid(row=2, column=0, padx=18, pady=(0, 8), sticky="ew")
        self.queue_host.grid_columnconfigure(0, weight=1)
        self.queue_host.grid_rowconfigure(0, weight=1)

        self.thumbnail_canvas = tk.Canvas(
            self.queue_host,
            bg=canvas_color,
            bd=0,
            highlightthickness=0,
            height=108,
            xscrollincrement=1,
        )
        self.thumbnail_canvas.grid(row=0, column=0, sticky="ew")
        self.thumbnail_canvas.bind("<Configure>", self.schedule_thumbnail_strip_rebuild)
        self.thumbnail_canvas.bind("<MouseWheel>", self.handle_thumbnail_wheel)
        self.thumbnail_canvas.bind("<Button-4>", self.handle_thumbnail_linux_wheel)
        self.thumbnail_canvas.bind("<Button-5>", self.handle_thumbnail_linux_wheel)

    def setup_footer(self):
        self.nah_button = ctk.CTkButton(
            self.footer_frame,
            text="Nah",
            fg_color="#b42318",
            hover_color="#912018",
            height=54,
            command=lambda: self.sort_current_photo("nah"),
        )
        self.nah_button.grid(row=0, column=0, padx=(18, 6), pady=18, sticky="ew")

        self.flag_button = ctk.CTkButton(
            self.footer_frame,
            text="Flag",
            fg_color="#d97706",
            hover_color="#b45309",
            height=54,
            command=lambda: self.sort_current_photo("flag"),
        )
        self.flag_button.grid(row=0, column=1, padx=6, pady=18, sticky="ew")

        self.keep_button = ctk.CTkButton(
            self.footer_frame,
            text="Keep",
            fg_color="#157f3b",
            hover_color="#126532",
            height=54,
            command=lambda: self.sort_current_photo("keep"),
        )
        self.keep_button.grid(row=0, column=2, padx=6, pady=18, sticky="ew")

        self.review_button = ctk.CTkButton(
            self.footer_frame,
            text="Review Batch",
            fg_color="#4f46e5",
            hover_color="#4338ca",
            height=54,
            command=self.open_review_commit_modal,
        )
        self.review_button.grid(row=0, column=3, padx=(6, 18), pady=18, sticky="ew")

    def setup_menu(self):
        menubar = tk.Menu(self)
        settings_label = "Settings..." if sys.platform == "darwin" else "Preview Settings..."
        accelerator = "Cmd+," if sys.platform == "darwin" else "Ctrl+,"

        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(
            label=settings_label, accelerator=accelerator, command=self.open_preview_settings_dialog
        )
        file_menu.add_separator()
        file_menu.add_command(
            label="Exit" if sys.platform != "darwin" else "Quit Keep or Nah",
            command=self.handle_window_close,
        )
        menubar.add_cascade(
            label="Keep or Nah" if sys.platform == "darwin" else "File", menu=file_menu
        )

        view_menu = tk.Menu(menubar, tearoff=False)
        view_menu.add_command(
            label="Preview Settings...",
            accelerator=accelerator,
            command=self.open_preview_settings_dialog,
        )
        view_menu.add_checkbutton(
            label="Staged Decisions Mode",
            variable=self.staged_mode_var,
            command=self.toggle_staged_mode,
        )
        view_menu.add_command(
            label="Toggle 2-Up Compare", accelerator="C", command=self.toggle_compare_mode
        )
        menubar.add_cascade(label="View", menu=view_menu)

        self.configure(menu=menubar)
        self.menubar = menubar

    def resolve_canvas_color(self) -> str:
        raw_color = self.main_frame.cget("fg_color")
        return self._apply_appearance_mode(raw_color)

    def folder_label(self, label: str, path: Path | None) -> str:
        if path is None:
            return label

        name = path.name or str(path)
        if len(name) > 18:
            name = f"{name[:15]}..."
        return f"{label}: {name}"

    def update_selector_buttons(self):
        self.source_button.configure(text=self.folder_label("Source", self.session.source_dir))
        self.keep_folder_button.configure(text=self.folder_label("Keep", self.session.keep_dir))
        self.nah_folder_button.configure(text=self.folder_label("Nah", self.session.nah_dir))
