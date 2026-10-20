from __future__ import annotations

import threading
from collections.abc import Callable

import customtkinter as ctk

from photo_triage import Decision, PhotoSessionError
from staged_triage import StagedBatchSummary, StagedDecision, format_bytes


class ReviewCommitController:
    """Manages business logic, revision, and batch execution state for the Review & Commit drawer."""

    def __init__(self, session, on_committed: Callable[[], None] | None = None) -> None:
        self.session = session
        self.on_committed = on_committed
        self.cancel_token = threading.Event()
        self.is_committing = False
        self.worker_thread: threading.Thread | None = None

    @property
    def staged(self) -> list[StagedDecision]:
        return list(self.session.staged_decisions)

    @property
    def summary(self) -> StagedBatchSummary:
        return self.session.staged_summary

    def revise_decision(self, stem: str, new_decision: Decision) -> StagedDecision | None:
        if new_decision == "keep":
            dest = self.session.keep_dir
        elif new_decision == "nah":
            dest = self.session.nah_dir
        else:
            dest = self.session.flag_dir

        try:
            return self.session._staged_manager.revise(stem, new_decision, dest)
        except (KeyError, IndexError):
            return None

    def unstage_item(self, stem: str) -> StagedDecision | None:
        staged = self.session._staged_manager.unstage(stem)
        if staged is not None:
            self.session.completed_stems.discard(staged.stem)
            self.session.pending_groups.append(staged.group)
            self.session.pending_groups.sort(key=lambda g: (g.stem.lower(), g.stem))
            self.session.queue = self.session._project_pending_groups()
            self.session.active_index = next(
                (i for i, g in enumerate(self.session.queue) if g.stem == staged.stem), 0
            )
            if staged.decision == "keep":
                self.session.keep_count -= 1
            elif staged.decision == "nah":
                self.session.nah_count -= 1
        return staged

    def discard_all(self) -> int:
        return self.session.undo_all_staged()

    def start_commit(
        self,
        on_progress: Callable[[int, int, str], None],
        on_complete: Callable[[int], None],
        on_error: Callable[[str], None],
    ) -> None:
        if self.is_committing:
            return

        self.is_committing = True
        self.cancel_token.clear()
        len(self.session.staged_decisions)

        def _worker() -> None:
            try:
                records = self.session.commit_staged_batch(
                    on_progress=on_progress,
                    cancel_token=self.cancel_token,
                )
                self.is_committing = False
                if self.on_committed is not None:
                    self.on_committed()
                on_complete(len(records))
            except PhotoSessionError as err:
                self.is_committing = False
                on_error(str(err))
            except Exception as err:
                self.is_committing = False
                on_error(f"Unexpected error: {err}")

        self.worker_thread = threading.Thread(target=_worker, daemon=True)
        self.worker_thread.start()

    def cancel_commit(self) -> None:
        if self.is_committing:
            self.cancel_token.set()


class ReviewCommitModal(ctk.CTkToplevel):
    """CustomTkinter modal dialog displaying staged triage decisions, stats, and batch execution."""

    def __init__(
        self,
        parent,
        session,
        on_committed: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.controller = ReviewCommitController(session, on_committed)

        self.title("Review & Commit Staged Decisions")
        self.geometry("720x620")
        self.minsize(580, 480)

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._setup_summary_banner()
        self._setup_items_list()
        self._setup_progress_bar()
        self._setup_action_buttons()

        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self.lift)

    def _setup_summary_banner(self) -> None:
        self.banner_frame = ctk.CTkFrame(self, corner_radius=8)
        self.banner_frame.grid(row=0, column=0, sticky="ew", padx=16, pady=(16, 8))
        self.banner_frame.grid_columnconfigure((0, 1, 2, 3), weight=1)

        self.stat_total = ctk.CTkLabel(
            self.banner_frame, text="", font=ctk.CTkFont(size=14, weight="bold")
        )
        self.stat_total.grid(row=0, column=0, padx=8, pady=10)

        self.stat_keep = ctk.CTkLabel(
            self.banner_frame,
            text="",
            text_color="#22c55e",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.stat_keep.grid(row=0, column=1, padx=8, pady=10)

        self.stat_nah = ctk.CTkLabel(
            self.banner_frame,
            text="",
            text_color="#ef4444",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.stat_nah.grid(row=0, column=2, padx=8, pady=10)

        self.stat_reclaimed = ctk.CTkLabel(
            self.banner_frame, text="", font=ctk.CTkFont(size=13, weight="bold")
        )
        self.stat_reclaimed.grid(row=0, column=3, padx=8, pady=10)

        self._refresh_summary()

    def _refresh_summary(self) -> None:
        summary = self.controller.summary
        self.stat_total.configure(text=f"Total: {summary.total_count}")
        self.stat_keep.configure(text=f"Keep: {summary.keep_count}")
        self.stat_nah.configure(text=f"Nah: {summary.nah_count}")
        self.stat_reclaimed.configure(text=f"Reclaimed: {summary.reclaimed_bytes_human}")

    def _setup_items_list(self) -> None:
        self.items_frame = ctk.CTkScrollableFrame(self, label_text="Staged Photos", corner_radius=8)
        self.items_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=8)
        self.items_frame.grid_columnconfigure(0, weight=1)
        self._populate_items()

    def _populate_items(self) -> None:
        for widget in self.items_frame.winfo_children():
            widget.destroy()

        staged_items = self.controller.staged
        if not staged_items:
            empty_lbl = ctk.CTkLabel(
                self.items_frame,
                text="No staged decisions. Use Keep, Nah, or Flag in staged mode to stage photos.",
                text_color="gray60",
            )
            empty_lbl.grid(row=0, column=0, pady=40)
            return

        for idx, item in enumerate(staged_items):
            row_frame = ctk.CTkFrame(self.items_frame, fg_color="transparent")
            row_frame.grid(row=idx, column=0, sticky="ew", pady=4, padx=4)
            row_frame.grid_columnconfigure(0, weight=1)

            name_lbl = ctk.CTkLabel(
                row_frame, text=item.stem, anchor="w", font=ctk.CTkFont(size=13)
            )
            name_lbl.grid(row=0, column=0, sticky="w", padx=8)

            size_lbl = ctk.CTkLabel(
                row_frame,
                text=format_bytes(item.bytes_size),
                text_color="gray60",
                font=ctk.CTkFont(size=12),
            )
            size_lbl.grid(row=0, column=1, padx=8)

            # Decision selector
            choice_var = ctk.StringVar(value=item.decision.capitalize())

            def _on_change(val: str, stem=item.stem):
                self.controller.revise_decision(stem, val.lower())
                self._refresh_summary()

            decision_seg = ctk.CTkSegmentedButton(
                row_frame,
                values=["Keep", "Nah", "Flag"],
                command=_on_change,
                variable=choice_var,
                width=160,
            )
            decision_seg.grid(row=0, column=2, padx=8)

            def _on_unstage(stem=item.stem):
                self.controller.unstage_item(stem)
                self._populate_items()
                self._refresh_summary()
                if hasattr(self.parent, "refresh_ui"):
                    self.parent.refresh_ui()

            unstage_btn = ctk.CTkButton(
                row_frame,
                text="✕",
                width=30,
                fg_color="transparent",
                hover_color="#374151",
                command=_on_unstage,
            )
            unstage_btn.grid(row=0, column=3, padx=(4, 8))

    def _setup_progress_bar(self) -> None:
        self.progress_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.progress_frame.grid(row=2, column=0, sticky="ew", padx=16, pady=4)
        self.progress_frame.grid_columnconfigure(0, weight=1)

        self.progress_label = ctk.CTkLabel(self.progress_frame, text="", font=ctk.CTkFont(size=12))
        self.progress_label.grid(row=0, column=0, sticky="w", padx=4)

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self.progress_bar.set(0.0)
        self.progress_frame.grid_remove()

    def _setup_action_buttons(self) -> None:
        self.actions_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.actions_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 16))
        self.actions_frame.grid_columnconfigure(0, weight=1)

        self.discard_btn = ctk.CTkButton(
            self.actions_frame,
            text="Discard All",
            fg_color="#374151",
            hover_color="#1f2937",
            command=self._on_discard_all,
            width=110,
        )
        self.discard_btn.grid(row=0, column=1, padx=6)

        self.close_btn = ctk.CTkButton(
            self.actions_frame,
            text="Close",
            fg_color="#4b5563",
            hover_color="#374151",
            command=self._on_close,
            width=90,
        )
        self.close_btn.grid(row=0, column=2, padx=6)

        self.commit_btn = ctk.CTkButton(
            self.actions_frame,
            text="Commit Batch",
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._on_commit_or_cancel,
            width=130,
        )
        self.commit_btn.grid(row=0, column=3, padx=6)

    def _on_discard_all(self) -> None:
        if self.controller.is_committing:
            return
        self.controller.discard_all()
        self._populate_items()
        self._refresh_summary()
        if hasattr(self.parent, "refresh_ui"):
            self.parent.refresh_ui()

    def _on_commit_or_cancel(self) -> None:
        if self.controller.is_committing:
            self.controller.cancel_commit()
            self.commit_btn.configure(text="Cancelling...", state="disabled")
            return

        if not self.controller.staged:
            return

        self.progress_frame.grid()
        self.progress_bar.set(0.0)
        self.progress_label.configure(text="Starting batch commit...")
        self.commit_btn.configure(text="Cancel", fg_color="#b42318", hover_color="#912018")
        self.discard_btn.configure(state="disabled")

        def _on_prog(done: int, total: int, stem: str) -> None:
            self.after(0, lambda: self._update_progress(done, total, stem))

        def _on_done(count: int) -> None:
            self.after(0, lambda: self._handle_success(count))

        def _on_err(msg: str) -> None:
            self.after(0, lambda: self._handle_error(msg))

        self.controller.start_commit(_on_prog, _on_done, _on_err)

    def _update_progress(self, done: int, total: int, stem: str) -> None:
        fraction = done / total if total > 0 else 1.0
        self.progress_bar.set(fraction)
        self.progress_label.configure(text=f"Committing {done}/{total}: {stem}...")

    def _handle_success(self, count: int) -> None:
        self.progress_label.configure(text=f"Successfully committed {count} photos.")
        self.commit_btn.configure(text="Done", fg_color="#157f3b", state="disabled")
        self.discard_btn.configure(state="normal")
        self._populate_items()
        self._refresh_summary()
        if hasattr(self.parent, "refresh_ui"):
            self.parent.refresh_ui()
        self.after(1000, self.destroy)

    def _handle_error(self, message: str) -> None:
        self.progress_label.configure(text=f"Commit halted: {message}")
        self.commit_btn.configure(
            text="Commit Batch",
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            state="normal",
        )
        self.discard_btn.configure(state="normal")
        self._populate_items()
        self._refresh_summary()
        if hasattr(self.parent, "refresh_ui"):
            self.parent.refresh_ui()

    def _on_close(self) -> None:
        if self.controller.is_committing:
            self.controller.cancel_commit()
        self.destroy()
