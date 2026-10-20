"""The Preview Settings dialog.

The dialog is where the photographer sets progressive preview, the loading
indicator, the preview cache budget, the staged decision mode, and the
extension view filter.

Every method here is a mixin method: it operates on `self`, which is the
`App` that owns the widget tree.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from app_settings import MAX_PREVIEW_CACHE_BUDGET_MB, MIN_PREVIEW_CACHE_BUDGET_MB, AppSettings
from session_startup import preview_paths_for
from view_filter import (
    EMPTY_SELECTION_MESSAGE,
    selected_extensions,
    validate_extension_selection,
)


class SettingsDialogMixin:
    """The Preview Settings dialog."""

    def open_preview_settings_dialog(self):
        if self.preview_settings_dialog is not None and self.preview_settings_dialog.winfo_exists():
            self.preview_settings_dialog.focus()
            self.preview_settings_dialog.lift()
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("Preview Settings")
        dialog.geometry("460x510")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.configure(fg_color=self.main_frame.cget("fg_color"))
        dialog.grid_columnconfigure(0, weight=1)
        dialog.grid_rowconfigure(0, weight=1)

        progressive_var = tk.BooleanVar(value=self.settings.progressive_preview)
        loading_var = tk.BooleanVar(value=self.settings.loading_indicator)
        staged_decisions_var = tk.BooleanVar(value=self.settings.staged_decisions)
        budget_var = tk.StringVar(value=str(self.settings.preview_cache_budget_mb))
        filter_model = self.extension_filter_model()
        extension_vars = {
            extension: tk.BooleanVar(value=extension in filter_model.selected)
            for extension in filter_model.options
        }

        container = ctk.CTkFrame(dialog, fg_color="transparent")
        container.grid(row=0, column=0, sticky="nsew", padx=20, pady=20)
        container.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            container,
            text="Settings",
            font=ctk.CTkFont(size=18, weight="bold"),
        ).grid(row=0, column=0, sticky="w", pady=(2, 14))

        ctk.CTkSwitch(container, text="Progressive Preview", variable=progressive_var).grid(
            row=1,
            column=0,
            sticky="w",
            pady=6,
        )
        ctk.CTkSwitch(container, text="Loading Indicator", variable=loading_var).grid(
            row=2,
            column=0,
            sticky="w",
            pady=6,
        )
        ctk.CTkSwitch(
            container, text="Staged Decisions (Batch Commit)", variable=staged_decisions_var
        ).grid(
            row=3,
            column=0,
            sticky="w",
            pady=6,
        )

        ctk.CTkLabel(container, text="Preview Cache Budget (MB)").grid(
            row=4, column=0, sticky="w", pady=(18, 6)
        )
        ctk.CTkEntry(container, textvariable=budget_var).grid(row=5, column=0, sticky="ew")

        helper_text = (
            f"Allowed range: {MIN_PREVIEW_CACHE_BUDGET_MB}-{MAX_PREVIEW_CACHE_BUDGET_MB} MB."
        )
        ctk.CTkLabel(
            container,
            text=helper_text,
            text_color=self._apply_appearance_mode(("gray45", "gray65")),
            justify="left",
            wraplength=360,
        ).grid(row=6, column=0, sticky="w", pady=(8, 14))

        filter_frame = ctk.CTkScrollableFrame(
            container,
            label_text="Extension View Filter",
            height=110,
        )
        filter_frame.grid(row=7, column=0, sticky="ew", pady=(0, 16))
        filter_frame.grid_columnconfigure((0, 1, 2), weight=1)
        if extension_vars:
            for index, (extension, variable) in enumerate(extension_vars.items()):
                ctk.CTkCheckBox(
                    filter_frame,
                    text=extension,
                    variable=variable,
                ).grid(row=index // 3, column=index % 3, sticky="w", padx=6, pady=4)
        else:
            ctk.CTkLabel(
                filter_frame,
                text="Choose a source folder to discover extensions.",
                text_color=self._apply_appearance_mode(("gray45", "gray65")),
            ).grid(row=0, column=0, columnspan=3, sticky="w", padx=6, pady=4)

        button_row = ctk.CTkFrame(container, fg_color="transparent")
        button_row.grid(row=8, column=0, sticky="ew")
        button_row.grid_columnconfigure((0, 1), weight=1)

        def close_dialog():
            if dialog.winfo_exists():
                dialog.destroy()
            self.preview_settings_dialog = None

        def save_settings():
            selected = selected_extensions(extension_vars)
            if filter_model.options:
                try:
                    validate_extension_selection(selected)
                except ValueError:
                    messagebox.showerror("Keep or Nah", EMPTY_SELECTION_MESSAGE)
                    return

            try:
                budget = int(budget_var.get().strip())
            except ValueError:
                messagebox.showerror("Keep or Nah", "Preview cache budget must be a whole number.")
                return

            if budget < MIN_PREVIEW_CACHE_BUDGET_MB or budget > MAX_PREVIEW_CACHE_BUDGET_MB:
                messagebox.showerror(
                    "Keep or Nah",
                    f"Preview cache budget must be between {MIN_PREVIEW_CACHE_BUDGET_MB} and {MAX_PREVIEW_CACHE_BUDGET_MB} MB.",
                )
                return

            settings = AppSettings(
                progressive_preview=progressive_var.get(),
                loading_indicator=loading_var.get(),
                preview_cache_budget_mb=budget,
                staged_decisions=staged_decisions_var.get(),
            )
            self.session.staged_mode = staged_decisions_var.get()
            self.staged_mode_var.set(staged_decisions_var.get())
            if not self.save_settings_changes(
                settings,
                set(selected) if filter_model.options else None,
                messagebox.showerror,
            ):
                return
            close_dialog()
            self.refresh_ui()

        ctk.CTkButton(button_row, text="Cancel", command=close_dialog).grid(
            row=0, column=0, padx=(0, 6), sticky="ew"
        )
        save_button = ctk.CTkButton(button_row, text="Save", command=save_settings)
        save_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        def update_save_state(*_args):
            disabled = bool(filter_model.options) and not selected_extensions(extension_vars)
            save_button.configure(state="disabled" if disabled else "normal")

        for variable in extension_vars.values():
            variable.trace_add("write", update_save_state)
        update_save_state()

        dialog.protocol("WM_DELETE_WINDOW", close_dialog)
        dialog.after(0, dialog.grab_set)
        self.preview_settings_dialog = dialog

    def apply_preview_settings(self, settings: AppSettings, *, persist: bool = True):
        normalized = settings.normalized()
        if persist:
            normalized.save()
        self.settings = normalized
        self.session.staged_mode = normalized.staged_decisions
        if hasattr(self, "staged_mode_var") and self.staged_mode_var is not None:
            self.staged_mode_var.set(normalized.staged_decisions)
        self.preview_pipeline.configure_cache_budget(normalized.preview_cache_budget_mb)
        self.prune_preview_texture_cache(set(preview_paths_for(self.session)))
        self.preview_source_path = None
        self.preview_source_image = None
        self.reset_preview_request_state()
        self.refresh_preview(reload_image=True)
        self.refresh_ui()
