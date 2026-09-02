from __future__ import annotations

import logging
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    TkBase = TkinterDnD.Tk
except ImportError:
    DND_FILES = None
    TkBase = tk.Tk

from models import BuildCancelled, BuildInputs, ProgressEvent
from patches import PATCHES, normalize_patch_ids
from pipeline import BuildPipeline
from steam import detect_half_life_2


BG = "#090909"
PANEL = "#111111"
FIELD = "#181818"
BORDER = "#343434"
TEXT = "#f1f1f1"
MUTED = "#999999"
BUTTON = "#e5e5e5"
BUTTON_TEXT = "#111111"


class PatcherUI(TkBase):
    def __init__(self):
        super().__init__()
        self.title("Portal 2 Beta Patcher")
        self.geometry("700x440")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.protocol("WM_DELETE_WINDOW", self.close_requested)

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.output_path: Path | None = None
        self.blob_var = tk.StringVar()
        self.dat_var = tk.StringVar()
        self.hl2_var = tk.StringVar()
        self.hl2_warning_var = tk.StringVar()
        self.hl2_var.trace_add("write", self.update_hl2_warning)
        self.message_var = tk.StringVar()
        self.percent_var = tk.StringVar(value="0%")
        self.progress_fraction = 0.0
        self.patch_vars = {patch.id: tk.BooleanVar(value=True) for patch in PATCHES}
        self.last_selected_patch_ids = tuple(patch.id for patch in PATCHES)

        self.container = tk.Frame(self, bg=BG)
        self.container.pack(fill="both", expand=True, padx=28, pady=24)
        self.show_files()
        self.after(100, self.poll_events)
        threading.Thread(target=self.detect_hl2, daemon=True).start()

    def clear(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def heading(self, title: str, detail: str) -> None:
        tk.Label(self.container, text=title, bg=BG, fg=TEXT, font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(self.container, text=detail, bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(5, 0))

    def button(self, parent, text, command, secondary=False, width=11):
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            bg=FIELD if secondary else BUTTON,
            fg=TEXT if secondary else BUTTON_TEXT,
            activebackground="#292929" if secondary else "#ffffff",
            activeforeground=TEXT if secondary else BUTTON_TEXT,
            relief="solid",
            borderwidth=1,
            font=("Segoe UI Semibold", 10),
            padx=6,
            pady=7,
        )

    def show_files(self) -> None:
        self.clear()
        self.heading("Portal 2 July 2009 Patcher", "Select your 852_0 files.")
        form = tk.Frame(self.container, bg=BG)
        form.pack(fill="x", pady=(25, 0))
        self.file_row(form, "BLOB file", self.blob_var, ".blob", False)
        self.file_row(form, "DAT file", self.dat_var, ".dat", False)
        self.file_row(form, "Half-Life 2 folder", self.hl2_var, "", True)

        tk.Label(
            self.container,
            textvariable=self.hl2_warning_var,
            bg=BG,
            fg="#d6aa62",
            font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(0, 4))
        self.update_hl2_warning()

        self.error_label = tk.Label(self.container, textvariable=self.message_var, bg=BG, fg="#e58b8b", font=("Segoe UI", 9))
        self.error_label.pack(anchor="w", pady=(0, 4))
        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self.button(bottom, "Next", self.show_patch_chooser, width=13).pack(side="right")

    def file_row(self, parent, label, variable, extension, folder):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 15))
        tk.Label(row, text=label, width=18, anchor="w", bg=BG, fg=TEXT, font=("Segoe UI", 10)).pack(side="left")
        entry = tk.Entry(
            row,
            textvariable=variable,
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="solid",
            borderwidth=1,
            font=("Segoe UI", 9),
        )
        entry.pack(side="left", fill="x", expand=True, ipady=9, padx=(0, 9))
        browse = (lambda: self.browse_folder(variable)) if folder else (lambda: self.browse_file(variable, extension))
        self.button(row, "Browse", browse, secondary=True, width=9).pack(side="right")
        if DND_FILES is not None and not folder:
            entry.drop_target_register(DND_FILES)
            entry.dnd_bind("<<Drop>>", lambda event, var=variable: self.drop_file(event, var))

    def drop_file(self, event, variable):
        files = self.tk.splitlist(event.data)
        if files:
            variable.set(files[0])

    def browse_file(self, variable, extension):
        selected = filedialog.askopenfilename(filetypes=[(extension.upper().lstrip(".") + " files", f"*{extension}"), ("All files", "*.*")])
        if selected:
            variable.set(selected)

    def browse_folder(self, variable):
        selected = filedialog.askdirectory()
        if selected:
            variable.set(selected)

    def detect_hl2(self):
        detected = detect_half_life_2()
        if detected:
            self.events.put(("hl2", detected))

    def update_hl2_warning(self, *_args) -> None:
        if self.hl2_var.get().strip():
            self.hl2_warning_var.set("")
        else:
            self.hl2_warning_var.set("No Half-Life 2 folder: HL2 content support will be unavailable.")

    def selected_patch_ids(self) -> tuple[str, ...]:
        return normalize_patch_ids(patch_id for patch_id, variable in self.patch_vars.items() if variable.get())

    def set_patch_choice(self, patch_ids: tuple[str, ...], selected: bool) -> None:
        for patch_id in patch_ids:
            self.patch_vars[patch_id].set(selected)

    def validate_file_choices(self) -> None:
        if not Path(self.blob_var.get()).is_file():
            raise ValueError("Select the 852_0 BLOB file first.")
        if not Path(self.dat_var.get()).is_file():
            raise ValueError("Select the 852_0 DAT file first.")
        hl2_value = self.hl2_var.get().strip()
        if hl2_value and not Path(hl2_value).is_dir():
            raise ValueError("The selected Half-Life 2 folder does not exist.")

    def show_patch_chooser(self):
        try:
            self.validate_file_choices()
        except Exception as error:
            self.message_var.set(str(error))
            return

        self.message_var.set("")
        self.clear()
        self.heading("Choose fixes", "Recommended fixes are selected by default.")

        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x", pady=(10, 0))
        self.button(bottom, "Back", self.show_files, secondary=True, width=10).pack(side="left")
        self.button(bottom, "Build", self.start_build, width=13).pack(side="right")
        self.error_label = tk.Label(self.container, textvariable=self.message_var, bg=BG, fg="#e58b8b", font=("Segoe UI", 9))
        self.error_label.pack(side="bottom", anchor="w")

        list_frame = tk.Frame(self.container, bg=BG)
        list_frame.pack(fill="both", expand=True, pady=(16, 0))
        canvas = tk.Canvas(list_frame, bg=BG, highlightthickness=0, borderwidth=0)
        scrollbar = tk.Scrollbar(
            list_frame,
            orient="vertical",
            command=canvas.yview,
            bg=FIELD,
            activebackground=BORDER,
            troughcolor=BG,
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True, padx=(0, 8))

        choices = tk.Frame(canvas, bg=BG)
        choices_window = canvas.create_window((0, 0), window=choices, anchor="nw")
        choices.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(choices_window, width=event.width))
        patch_by_id = {patch.id: patch for patch in PATCHES}
        has_hl2 = bool(self.hl2_var.get().strip())
        if not has_hl2:
            self.set_patch_choice(("p1", "p3"), False)
        choices_to_show = (
            (
                ("p1", "p3"),
                "Half-Life 2 content support",
                "Copy the required HL2 assets and register their sound scripts.",
            ),
            (("p4",), patch_by_id["p4"].display_name, patch_by_id["p4"].description),
            (("p5",), patch_by_id["p5"].display_name, patch_by_id["p5"].description),
        )
        for patch_ids, name, detail in choices_to_show:
            primary_id = patch_ids[0]
            panel = tk.Frame(choices, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            panel.pack(fill="x", pady=(0, 7))
            checkbox = tk.Checkbutton(
                panel,
                text=name,
                variable=self.patch_vars[primary_id],
                command=lambda ids=patch_ids, variable=self.patch_vars[primary_id]: self.set_patch_choice(ids, variable.get()),
                bg=PANEL,
                fg=TEXT,
                selectcolor=FIELD,
                activebackground=PANEL,
                activeforeground=TEXT,
                font=("Segoe UI Semibold", 10),
                borderwidth=0,
                highlightthickness=0,
            )
            checkbox.pack(anchor="w", padx=14, pady=(7, 0))
            unavailable = not has_hl2 and "p1" in patch_ids
            if unavailable:
                checkbox.configure(state="disabled", disabledforeground=MUTED)
                detail += "  Unavailable because no Half-Life 2 folder was selected."
            tk.Label(
                panel,
                text=detail,
                bg=PANEL,
                fg=MUTED,
                anchor="w",
                justify="left",
                wraplength=610,
                font=("Segoe UI", 8),
            ).pack(fill="x", padx=36, pady=(1, 7))

        def scroll(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        def bind_wheel(widget):
            widget.bind("<MouseWheel>", scroll)
            for child in widget.winfo_children():
                bind_wheel(child)

        bind_wheel(list_frame)

    def start_build(self):
        try:
            self.validate_file_choices()
            blob = Path(self.blob_var.get())
            dat = Path(self.dat_var.get())
            hl2_value = self.hl2_var.get().strip()
            hl2 = Path(hl2_value) if hl2_value else None
            selected_patch_ids = self.selected_patch_ids()
            output = dat.resolve().parent / "852_0_fixed"
            inputs = BuildInputs(blob, dat, hl2, output, selected_patch_ids)
        except Exception as error:
            self.message_var.set(str(error))
            return
        self.last_selected_patch_ids = selected_patch_ids
        self.message_var.set("")
        self.cancel_event.clear()
        self.show_progress()
        self.worker = threading.Thread(target=self.run_pipeline, args=(inputs,), daemon=True)
        self.worker.start()

    def run_pipeline(self, inputs):
        try:
            output = BuildPipeline(lambda event: self.events.put(("progress", event)), self.cancel_event).run(inputs)
            self.events.put(("complete", output))
        except BuildCancelled:
            self.events.put(("cancelled", None))
        except Exception as error:
            logging.exception("Build failed")
            self.events.put(("error", str(error)))

    def show_progress(self):
        self.clear()
        self.heading("Patching 852_0", "Preparing the build.")
        block = tk.Frame(self.container, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        block.pack(fill="x", pady=(28, 0))
        inner = tk.Frame(block, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=18)
        top = tk.Frame(inner, bg=PANEL)
        top.pack(fill="x")
        tk.Label(top, textvariable=self.message_var, bg=PANEL, fg=TEXT, font=("Segoe UI", 10)).pack(side="left")
        tk.Label(top, textvariable=self.percent_var, bg=PANEL, fg=TEXT, font=("Segoe UI", 10)).pack(side="right")
        self.progress = tk.Canvas(inner, height=10, bg=PANEL, highlightthickness=0)
        self.progress.pack(fill="x", pady=(12, 16))
        self.progress.bind("<Configure>", lambda _event: self.draw_progress())
        self.detail = tk.Label(inner, text="Validating inputs", anchor="w", bg=PANEL, fg=MUTED, font=("Cascadia Mono", 9))
        self.detail.pack(fill="x")
        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self.button(bottom, "Cancel", self.cancel_build, secondary=True, width=10).pack(side="right")

    def draw_progress(self):
        if not hasattr(self, "progress"):
            return
        width = max(self.progress.winfo_width(), 1)
        self.progress.delete("all")
        self.progress.create_rectangle(0, 0, width, 10, fill="#303030", outline="")
        self.progress.create_rectangle(0, 0, width * self.progress_fraction, 10, fill=BUTTON, outline="")

    def update_progress(self, event: ProgressEvent):
        phase_ranges = {
            "validate": (0.00, 0.10),
            "extract": (0.10, 0.58),
            "p1": (0.58, 0.88),
            "patches": (0.88, 0.99),
            "complete": (1.00, 1.00),
        }
        start, end = phase_ranges.get(event.phase, (0.88, 0.99))
        local = min(max(event.completed / max(event.total, 1), 0.0), 1.0)
        self.progress_fraction = start + (end - start) * local
        self.percent_var.set(f"{round(self.progress_fraction * 100)}%")
        self.message_var.set(event.message)
        if hasattr(self, "detail"):
            self.detail.configure(text=event.phase)
        self.draw_progress()

    def cancel_build(self):
        self.cancel_event.set()
        self.message_var.set("Cancelling after the current file…")

    def show_complete(self, output: Path):
        self.output_path = output
        self.clear()
        self.heading("Finished", "Portal 2 build 852_0 is ready.")
        block = tk.Frame(self.container, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        block.pack(fill="x", pady=(28, 0))
        inner = tk.Frame(block, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=17)
        tk.Label(inner, text="Installed to", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(inner, text=str(output), bg=PANEL, fg=TEXT, font=("Cascadia Mono", 9)).pack(anchor="w", pady=(6, 0))
        summary = tk.Frame(self.container, bg=BG)
        summary.pack(fill="x", pady=(18, 0))
        for patch in PATCHES:
            if patch.id in self.last_selected_patch_ids:
                tk.Label(summary, text=f"✓  {patch.id}  {patch.display_name}", bg=BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=1)
        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self.button(bottom, "Open folder", lambda: os.startfile(output), secondary=True, width=12).pack(side="left")
        self.button(bottom, "Launch Portal 2", lambda: os.startfile(output / "Launch Portal 2.cmd"), width=16).pack(side="right")

    def show_error(self, text):
        self.show_files()
        self.message_var.set(text)

    def poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "hl2" and not self.hl2_var.get():
                    self.hl2_var.set(str(payload))
                elif kind == "progress":
                    self.update_progress(payload)
                elif kind == "complete":
                    self.show_complete(payload)
                elif kind == "error":
                    self.show_error(payload)
                elif kind == "cancelled":
                    self.show_error("Build cancelled.")
        except queue.Empty:
            pass
        self.after(100, self.poll_events)

    def close_requested(self):
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.after(200, self.close_requested)
            return
        self.destroy()


def run_ui() -> None:
    PatcherUI().mainloop()
