from __future__ import annotations

import logging
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD

    TkBase = TkinterDnD.Tk
except ImportError:
    DND_FILES = None
    TkBase = tk.Tk

from extractor import CatalogTarget, scan_archive_catalog
from models import BuildCancelled, BuildInputs, ProgressEvent
from patches import PATCHES, normalize_patch_ids
from patches.p7_hammer import repair_moved_tools
from pipeline import BuildPipeline
from steam import detect_half_life_2, detect_portal_2


BG = "#090909"
PANEL = "#111111"
FIELD = "#181818"
BORDER = "#343434"
TEXT = "#f1f1f1"
MUTED = "#999999"
BUTTON = "#e5e5e5"
BUTTON_TEXT = "#111111"


def patch_ids_for_mode(
    mode: str,
    depot_id: int | None = None,
    depot_version: int | None = None,
) -> tuple[str, ...]:
    if mode != "generic":
        return ("p1", "p3", "p4", "p5", "p7", "p8", "p10")
    patch_ids = ["p5", "p9", "p10"]
    if (depot_id, depot_version) == (852, 1):
        patch_ids.append("p11")
    return tuple(patch_ids)


def default_generic_output(archive_folder: Path, target: CatalogTarget) -> Path:
    return archive_folder.resolve().parent / f"{target.depot_id}_{target.version}_fixed"


def back_screen_for_mode(mode: str) -> str:
    return "generic_files" if mode == "generic" else "852_files"


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
        self.current_mode = "852_0"
        self.blob_var = tk.StringVar()
        self.dat_var = tk.StringVar()
        self.portal2_var = tk.StringVar()
        self.hl2_var = tk.StringVar()
        self.hl2_warning_var = tk.StringVar()
        self.portal2_warning_var = tk.StringVar()
        self.hl2_var.trace_add("write", self.update_hl2_warning)
        self.portal2_var.trace_add("write", self.update_portal2_warning)
        self.message_var = tk.StringVar()
        self.percent_var = tk.StringVar(value="0%")
        self.archive_folder_var = tk.StringVar()
        self.generic_output_var = tk.StringVar()
        self.custom_key_var = tk.StringVar()
        self.goldberg_zip_var = tk.StringVar()
        self.catalog_targets: list[CatalogTarget] = []
        self.selected_target: CatalogTarget | None = None
        self.progress_fraction = 0.0
        self.patch_vars = {patch.id: tk.BooleanVar(value=True) for patch in PATCHES}
        self.patch_vars["p10"].set(False)
        self.last_selected_patch_ids = tuple(patch.id for patch in PATCHES)

        self.container = tk.Frame(self, bg=BG)
        self.container.pack(fill="both", expand=True, padx=28, pady=24)
        self.show_mode_selection()
        self.after(100, self.poll_events)
        threading.Thread(target=self.detect_portal2, daemon=True).start()
        threading.Thread(target=self.detect_hl2, daemon=True).start()

    def clear(self) -> None:
        for child in self.container.winfo_children():
            child.destroy()

    def heading(self, title: str, detail: str) -> None:
        tk.Label(self.container, text=title, bg=BG, fg=TEXT, font=("Segoe UI Semibold", 18)).pack(anchor="w")
        tk.Label(self.container, text=detail, bg=BG, fg=MUTED, font=("Segoe UI", 10)).pack(anchor="w", pady=(5, 0))

    def show_mode_selection(self) -> None:
        self.clear()
        self.heading("Portal 2 Beta Patcher", "What do you want to extract and patch?")

        choices = tk.Frame(self.container, bg=BG)
        choices.pack(fill="x", pady=(28, 0))

        self.mode_choice(
            choices,
            "Portal 2 July 2009 Core Hub",
            "Extract the July 2009 (852_0) build and choose from all available fixes.",
            self.show_files,
        ).pack(fill="x", pady=(0, 12))
        self.mode_choice(
            choices,
            "Other Portal 2 steam2 Build",
            "Extract another build and choose fixes.",
            self.show_generic_files,
        ).pack(fill="x")

    def mode_choice(self, parent, title: str, detail: str, command):
        panel = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        text = tk.Frame(panel, bg=PANEL)
        text.pack(side="left", fill="both", expand=True, padx=18, pady=16)
        tk.Label(
            text,
            text=title,
            bg=PANEL,
            fg=TEXT,
            anchor="w",
            font=("Segoe UI Semibold", 12),
        ).pack(fill="x")
        tk.Label(
            text,
            text=detail,
            bg=PANEL,
            fg=MUTED,
            anchor="w",
            justify="left",
            wraplength=480,
            font=("Segoe UI", 9),
        ).pack(fill="x", pady=(5, 0))
        self.button(panel, "Choose", command, width=10).pack(side="right", padx=16)
        return panel

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

    def show_generic_files(self, reset: bool = True) -> None:
        self.current_mode = "generic"
        if reset:
            self.selected_target = None
            self.catalog_targets = []
        self.message_var.set("")
        self.clear()
        self.heading("Other Portal 2 build", "Choose a folder containing the build's BLOB and DAT files.")

        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self.button(bottom, "Back", self.show_mode_selection, secondary=True, width=10).pack(side="left")
        self.generic_next_button = self.button(bottom, "Next", self.show_generic_patch_chooser, width=13)
        self.generic_next_button.configure(state="disabled")
        self.generic_next_button.pack(side="right")

        form = tk.Frame(self.container, bg=BG)
        form.pack(fill="x", pady=(16, 0))
        row = tk.Frame(form, bg=BG)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(row, text="Archive folder", width=15, anchor="w", bg=BG, fg=TEXT, font=("Segoe UI", 10)).pack(side="left")
        entry = tk.Entry(row, textvariable=self.archive_folder_var, bg=FIELD, fg=TEXT, insertbackground=TEXT,
                         relief="solid", borderwidth=1, font=("Segoe UI", 9))
        entry.pack(side="left", fill="x", expand=True, ipady=8, padx=(0, 8))
        self.button(row, "Browse", self.browse_generic_folder, secondary=True, width=8).pack(side="right")
        if DND_FILES is not None:
            entry.drop_target_register(DND_FILES)
            entry.dnd_bind("<<Drop>>", self.drop_archive_folder)

        status = tk.Frame(self.container, bg=BG)
        status.pack(fill="x", pady=(10, 5))
        tk.Label(status, textvariable=self.message_var, bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 9)).pack(side="left")
        self.scan_button = self.button(status, "Scan", self.start_catalog_scan, secondary=True, width=8)
        self.scan_button.pack(side="right")

        self.catalog_frame = tk.Frame(self.container, bg=BG)
        self.catalog_frame.pack(fill="both", expand=True)
        self.render_catalog()
        if self.selected_target is not None:
            self.generic_next_button.configure(state="normal")

    def browse_generic_folder(self) -> None:
        selected = filedialog.askdirectory(title="Select the folder containing Portal 2 archives")
        if selected:
            self.archive_folder_var.set(selected)
            self.start_catalog_scan()

    def drop_archive_folder(self, event) -> None:
        paths = self.tk.splitlist(event.data)
        if not paths:
            return
        selected = Path(paths[0])
        if selected.is_file():
            selected = selected.parent
        self.archive_folder_var.set(str(selected))
        self.start_catalog_scan()

    def start_catalog_scan(self) -> None:
        folder = Path(self.archive_folder_var.get().strip())
        if not folder.is_dir():
            self.message_var.set("Select an archive folder first.")
            return
        self.selected_target = None
        self.catalog_targets = []
        self.message_var.set("Scanning archives…")
        self.scan_button.configure(state="disabled")
        self.generic_next_button.configure(state="disabled")
        self.render_catalog()

        def scan() -> None:
            try:
                self.events.put(("catalog", scan_archive_catalog(folder)))
            except Exception as error:
                self.events.put(("catalog_error", str(error)))

        threading.Thread(target=scan, daemon=True).start()

    def render_catalog(self) -> None:
        if not hasattr(self, "catalog_frame"):
            return
        for child in self.catalog_frame.winfo_children():
            child.destroy()
        if not self.catalog_targets:
            tk.Label(self.catalog_frame, text="No scan results yet.", bg=BG, fg=MUTED,
                     font=("Segoe UI", 9)).pack(anchor="w", pady=(8, 0))
            return
        canvas = tk.Canvas(self.catalog_frame, bg=BG, highlightthickness=0, height=130)
        scrollbar = tk.Scrollbar(self.catalog_frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        rows = tk.Frame(canvas, bg=BG)
        window = canvas.create_window((0, 0), window=rows, anchor="nw")
        rows.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
        selected = tk.StringVar()
        for index, target in enumerate(self.catalog_targets):
            row = tk.Radiobutton(
                rows,
                text=target.label,
                variable=selected,
                value=str(index),
                command=lambda item=target: self.select_catalog_target(item),
                state="normal" if target.ready else "disabled",
                bg=PANEL,
                fg=TEXT,
                disabledforeground="#666666",
                selectcolor=FIELD,
                activebackground=PANEL,
                activeforeground=TEXT,
                anchor="w",
                font=("Cascadia Mono", 8),
            )
            row.pack(fill="x", pady=(0, 2), ipady=3)
    def select_catalog_target(self, target: CatalogTarget) -> None:
        self.selected_target = target
        archive_folder = Path(self.archive_folder_var.get()).resolve()
        self.generic_output_var.set(str(default_generic_output(archive_folder, target)))
        self.generic_next_button.configure(state="normal")
        if target.needs_custom_key:
            self.message_var.set(f"Depot {target.depot_id} needs a 32-character hexadecimal key.")
        else:
            self.message_var.set("")

    def show_files(self) -> None:
        self.current_mode = "852_0"
        self.clear()
        self.heading("Portal 2 July 2009 Patcher", "Select your 852_0 files.")
        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self.button(bottom, "Back", self.show_mode_selection, secondary=True, width=10).pack(side="left")
        self.button(bottom, "Fix moved build", self.repair_tools, secondary=True, width=17).pack(side="left", padx=(10, 0))
        self.button(bottom, "Next", self.show_patch_chooser, width=13).pack(side="right")
        form = tk.Frame(self.container, bg=BG)
        form.pack(fill="x", pady=(20, 0))
        self.file_row(form, "BLOB file", self.blob_var, ".blob", False)
        self.file_row(form, "DAT file", self.dat_var, ".dat", False)
        self.file_row(form, "Portal 2 folder", self.portal2_var, "", True)
        self.file_row(form, "Half-Life 2 folder", self.hl2_var, "", True)

        warning_frame = tk.Frame(self.container, bg=BG)
        warning_frame.pack(fill="x")
        self.portal2_warning_label = tk.Label(
            warning_frame,
            textvariable=self.portal2_warning_var,
            bg=BG,
            fg="#d6aa62",
            font=("Segoe UI", 9),
        )
        self.hl2_warning_label = tk.Label(
            warning_frame,
            textvariable=self.hl2_warning_var,
            bg=BG,
            fg="#d6aa62",
            font=("Segoe UI", 9),
        )
        self.update_portal2_warning()
        self.update_hl2_warning()

        self.error_label = tk.Label(self.container, textvariable=self.message_var, bg=BG, fg="#e58b8b", font=("Segoe UI", 9))
        self.error_label.pack(anchor="w", pady=(0, 4))

    def file_row(self, parent, label, variable, extension, folder):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(0, 10))
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

    def browse_goldberg_zip(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select the Goldberg ZIP",
            filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
        )
        if selected:
            self.goldberg_zip_var.set(selected)

    def add_goldberg_zip_field(self, panel) -> None:
        zip_row = tk.Frame(panel, bg=PANEL)
        zip_row.pack(fill="x", padx=36, pady=(0, 8))
        tk.Entry(
            zip_row,
            textvariable=self.goldberg_zip_var,
            bg=FIELD,
            fg=TEXT,
            insertbackground=TEXT,
            relief="solid",
            borderwidth=1,
            font=("Cascadia Mono", 8),
        ).pack(side="left", fill="x", expand=True, ipady=5)
        self.button(
            zip_row,
            "Browse",
            self.browse_goldberg_zip,
            secondary=True,
            width=8,
        ).pack(side="right", padx=(8, 0))

    def browse_folder(self, variable):
        selected = filedialog.askdirectory()
        if selected:
            variable.set(selected)

    def repair_tools(self) -> None:
        messagebox.showinfo(
            "Fix moved build",
            "Use this after moving a patched 852_0_fixed folder. It updates Hammer and HLMV to use the folder's new location.",
            parent=self,
        )
        selected = filedialog.askdirectory(title="Select the moved 852_0_fixed folder")
        if not selected:
            return
        try:
            repair_moved_tools(Path(selected))
        except Exception as error:
            messagebox.showerror("Fix moved build", str(error), parent=self)
            return
        messagebox.showinfo(
            "Fix moved build",
            "Hammer and HLMV now use this folder's current location.",
            parent=self,
        )

    def detect_hl2(self):
        detected = detect_half_life_2()
        if detected:
            self.events.put(("hl2", detected))

    def detect_portal2(self):
        detected = detect_portal_2()
        if detected:
            self.events.put(("portal2", detected))

    def update_hl2_warning(self, *_args) -> None:
        if self.hl2_var.get().strip():
            self.hl2_warning_var.set("")
            if hasattr(self, "hl2_warning_label"):
                self.hl2_warning_label.pack_forget()
        else:
            self.hl2_warning_var.set("No Half-Life 2 folder: HL2 content support will be unavailable.")
            if hasattr(self, "hl2_warning_label"):
                self.hl2_warning_label.pack(anchor="w", pady=(0, 4))

    def update_portal2_warning(self, *_args) -> None:
        if self.portal2_var.get().strip():
            self.portal2_warning_var.set("")
            if hasattr(self, "portal2_warning_label"):
                self.portal2_warning_label.pack_forget()
        else:
            self.portal2_warning_var.set("No Portal 2 folder: the Hammer and HLMV fix will be unavailable. Please do not pirate Portal 2!")
            if hasattr(self, "portal2_warning_label"):
                options = {"anchor": "w", "pady": (0, 4)}
                if self.hl2_warning_label.winfo_manager():
                    options["before"] = self.hl2_warning_label
                self.portal2_warning_label.pack(**options)

    def selected_patch_ids(self) -> tuple[str, ...]:
        return normalize_patch_ids(
            (patch_id for patch_id, variable in self.patch_vars.items() if variable.get()),
            self.current_mode,
        )

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
        portal2_value = self.portal2_var.get().strip()
        if portal2_value and not Path(portal2_value).is_dir():
            raise ValueError("The selected Portal 2 folder does not exist.")

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
        has_portal2 = bool(self.portal2_var.get().strip())
        if not has_hl2:
            self.set_patch_choice(("p1", "p3"), False)
        if not has_portal2:
            self.set_patch_choice(("p7",), False)
        choices_to_show = (
            (
                ("p1", "p3"),
                "Half-Life 2 content support",
                "Copy the required HL2 assets and register their sound scripts.",
            ),
            (("p4",), patch_by_id["p4"].display_name, patch_by_id["p4"].description),
            (("p5",), patch_by_id["p5"].display_name, patch_by_id["p5"].description),
            (("p7",), patch_by_id["p7"].display_name, patch_by_id["p7"].description),
            (("p8",), patch_by_id["p8"].display_name, patch_by_id["p8"].description),
            (("p10",), patch_by_id["p10"].display_name, patch_by_id["p10"].description),
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
            unavailable_reason = "Unavailable because no Half-Life 2 folder was selected."
            if "p7" in patch_ids and not has_portal2:
                unavailable = True
                unavailable_reason = "Unavailable because no retail Portal 2 folder was selected."
            if unavailable:
                checkbox.configure(state="disabled", disabledforeground=MUTED)
                detail += f"  {unavailable_reason}"
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
            if primary_id == "p10":
                self.add_goldberg_zip_field(panel)

        def scroll(event):
            canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

        def bind_wheel(widget):
            widget.bind("<MouseWheel>", scroll)
            for child in widget.winfo_children():
                bind_wheel(child)

        bind_wheel(list_frame)

    def show_generic_patch_chooser(self) -> None:
        target = self.selected_target
        if target is None or not target.ready:
            self.message_var.set("Select a ready revision first.")
            return
        self.current_mode = "generic"
        self.message_var.set("")
        self.clear()
        detail = (
            "Choose the patches you want to apply."
            if target.runnable
            else "This content-only depot can be extracted, but it is not independently runnable."
        )
        self.heading("Choose fixes", detail)
        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self.button(bottom, "Back", lambda: self.show_generic_files(False), secondary=True, width=10).pack(side="left")
        self.button(bottom, "Build", self.start_generic_build, width=13).pack(side="right")

        choices = tk.Frame(self.container, bg=BG)
        choices.pack(fill="x", pady=(18, 0))
        patch_by_id = {patch.id: patch for patch in PATCHES}
        patch_ids = patch_ids_for_mode("generic", target.depot_id, target.version)
        if not target.runnable:
            for patch_id in patch_ids:
                self.patch_vars[patch_id].set(False)
        for patch_id in patch_ids:
            patch = patch_by_id[patch_id]
            panel = tk.Frame(choices, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
            panel.pack(fill="x", pady=(0, 8))
            checkbox = tk.Checkbutton(
                panel,
                text=patch.display_name,
                variable=self.patch_vars[patch_id],
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
            detail = patch.description
            if not target.runnable:
                checkbox.configure(state="disabled", disabledforeground=MUTED)
                detail += "  Unavailable because this is a content-only depot."
            tk.Label(panel, text=detail, bg=PANEL, fg=MUTED, anchor="w", justify="left",
                     wraplength=610, font=("Segoe UI", 8)).pack(fill="x", padx=36, pady=(1, 7))
            if patch_id == "p10":
                self.add_goldberg_zip_field(panel)

        if target.needs_custom_key:
            key_row = tk.Frame(self.container, bg=BG)
            key_row.pack(fill="x", pady=(5, 0))
            tk.Label(key_row, text="Depot key", width=15, anchor="w", bg=BG, fg=TEXT,
                     font=("Segoe UI", 10)).pack(side="left")
            tk.Entry(key_row, textvariable=self.custom_key_var, bg=FIELD, fg=TEXT,
                     insertbackground=TEXT, relief="solid", borderwidth=1,
                     font=("Cascadia Mono", 9)).pack(side="left", fill="x", expand=True, ipady=7)
            tk.Label(self.container, text="Enter the 32 hexadecimal characters supplied with the archive.",
                     bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 8)).pack(fill="x", padx=(105, 0), pady=(3, 0))
        self.error_label = tk.Label(self.container, textvariable=self.message_var, bg=BG, fg="#e58b8b",
                                    font=("Segoe UI", 9))
        self.error_label.pack(side="bottom", anchor="w", pady=(0, 5))

    def start_generic_build(self) -> None:
        try:
            target = self.selected_target
            if target is None or not target.ready:
                raise ValueError("Select a ready revision first.")
            output = Path(self.generic_output_var.get().strip())
            if output.exists():
                raise FileExistsError(f"Output already exists: {output}")
            custom_key = None
            if target.needs_custom_key:
                text = self.custom_key_var.get().strip()
                if len(text) != 32:
                    raise ValueError("The depot key must contain exactly 32 hexadecimal characters.")
                try:
                    custom_key = bytes.fromhex(text)
                except ValueError as error:
                    raise ValueError("The depot key must contain only hexadecimal characters.") from error
            available_patch_ids = patch_ids_for_mode("generic", target.depot_id, target.version)
            selected_patch_ids = tuple(
                patch_id for patch_id in available_patch_ids if self.patch_vars[patch_id].get()
            )
            goldberg_archive = None
            if "p10" in selected_patch_ids:
                zip_text = self.goldberg_zip_var.get().strip()
                if not zip_text:
                    raise ValueError("Select the Goldberg ZIP to use")
                goldberg_archive = Path(zip_text)
            final = target.chain[-1]
            inputs = BuildInputs(
                final.blob_path,
                final.dat_path,
                None,
                output,
                selected_patch_ids,
                None,
                "generic",
                target.depot_id,
                target.version,
                target.crc,
                target.chain,
                custom_key,
                goldberg_archive,
            )
        except Exception as error:
            self.message_var.set(str(error))
            return
        self.last_selected_patch_ids = normalize_patch_ids(
            selected_patch_ids,
            "generic",
            runnable=target.runnable,
            depot_id=target.depot_id,
            depot_version=target.version,
        )
        self.active_inputs = inputs
        self.message_var.set("")
        self.cancel_event.clear()
        self.show_progress()
        self.worker = threading.Thread(target=self.run_pipeline, args=(inputs,), daemon=True)
        self.worker.start()

    def start_build(self):
        try:
            self.validate_file_choices()
            blob = Path(self.blob_var.get())
            dat = Path(self.dat_var.get())
            hl2_value = self.hl2_var.get().strip()
            hl2 = Path(hl2_value) if hl2_value else None
            portal2_value = self.portal2_var.get().strip()
            portal2 = Path(portal2_value) if portal2_value else None
            selected_patch_ids = self.selected_patch_ids()
            goldberg_archive = None
            if "p10" in selected_patch_ids:
                zip_text = self.goldberg_zip_var.get().strip()
                if not zip_text:
                    raise ValueError("Select the Goldberg ZIP to use")
                goldberg_archive = Path(zip_text)
            output = dat.resolve().parent / "852_0_fixed"
            inputs = BuildInputs(
                blob,
                dat,
                hl2,
                output,
                selected_patch_ids,
                portal2,
                goldberg_archive_path=goldberg_archive,
            )
        except Exception as error:
            self.message_var.set(str(error))
            return
        self.last_selected_patch_ids = selected_patch_ids
        self.active_inputs = inputs
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
        if self.current_mode == "generic" and self.selected_target is not None:
            title = f"Patching {self.selected_target.depot_id} version {self.selected_target.version}"
        else:
            title = "Patching 852_0"
        self.heading(title, "Preparing the build.")
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
        runnable = (output / "hl2.exe").is_file() and (output / "portal2" / "GameInfo.txt").is_file()
        if self.current_mode == "generic" and self.selected_target is not None:
            detail = f"Portal 2 depot {self.selected_target.depot_id} version {self.selected_target.version} is ready."
            if not runnable:
                detail = "Extraction finished. This content-only depot is not independently runnable."
        else:
            detail = "Portal 2 build 852_0 is ready."
        self.heading("Finished", detail)
        block = tk.Frame(self.container, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        block.pack(fill="x", pady=(28, 0))
        inner = tk.Frame(block, bg=PANEL)
        inner.pack(fill="x", padx=18, pady=17)
        tk.Label(inner, text="Installed to", bg=PANEL, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w")
        tk.Label(inner, text=str(output), bg=PANEL, fg=TEXT, font=("Cascadia Mono", 9)).pack(anchor="w", pady=(6, 0))
        summary = tk.Frame(self.container, bg=BG)
        summary.pack(fill="x", pady=(18, 0))
        selected_patches = [patch for patch in PATCHES if patch.id in self.last_selected_patch_ids]
        for index, patch in enumerate(selected_patches):
            row = index % 4
            column = index // 4
            tk.Label(
                summary,
                text=f"✓  {patch.id}  {patch.display_name}",
                bg=BG,
                fg=MUTED,
                anchor="w",
                font=("Segoe UI", 9),
            ).grid(row=row, column=column, sticky="w", padx=(0, 28), pady=1)
        summary.grid_columnconfigure(0, weight=1)
        summary.grid_columnconfigure(1, weight=1)
        bottom = tk.Frame(self.container, bg=BG)
        bottom.pack(side="bottom", fill="x")
        self.button(bottom, "Open folder", lambda: os.startfile(output), secondary=True, width=12).pack(side="left")
        launcher = output / "Launch Portal 2.cmd"
        if launcher.is_file():
            self.button(bottom, "Launch Portal 2", lambda: os.startfile(launcher), width=16).pack(side="right")

    def show_error(self, text):
        if back_screen_for_mode(self.current_mode) == "generic_files":
            self.show_generic_files(False)
        else:
            self.show_files()
        self.message_var.set(text)

    def poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "hl2" and not self.hl2_var.get():
                    self.hl2_var.set(str(payload))
                elif kind == "portal2" and not self.portal2_var.get():
                    self.portal2_var.set(str(payload))
                elif kind == "catalog":
                    self.catalog_targets = payload
                    self.message_var.set(
                        f"Found {len(payload)} archive candidate{'s' if len(payload) != 1 else ''}."
                        if payload else "No matching Portal 2 Steam 2 archives were found."
                    )
                    if hasattr(self, "scan_button"):
                        self.scan_button.configure(state="normal")
                    self.render_catalog()
                elif kind == "catalog_error":
                    self.message_var.set(str(payload))
                    if hasattr(self, "scan_button"):
                        self.scan_button.configure(state="normal")
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
