"""Squelette commun des onglets : fichiers à gauche, réglages à droite, commande ffmpeg en bas."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QFrame, QGroupBox, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QScrollArea, QSplitter, QVBoxLayout, QWidget)

from ..core import Job, UserError, parse_extra
from ..ffmpeg import MEDIA_EXT, cmdline
from ..settings_form import Binder, line
from ..widgets import FileList, PresetBar


class BaseTab(QWidget):
    tab_id = "base"
    title = "Base"
    extensions = MEDIA_EXT
    reorder = False
    files_title = "Fichiers"
    files_hint = "Glisse des fichiers ou des dossiers ici"
    BUILTINS: dict = {}

    file_selected = Signal(object)
    add_requested = Signal(object)

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.binder = Binder()
        self.files: FileList | None = None
        self.skipped = 0

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        split = QSplitter(Qt.Horizontal)
        root.addWidget(split)
        split.addWidget(self.build_left())

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        self.presets = PresetBar(self.tab_id, self.BUILTINS, self.binder.get, self.apply_settings)
        rv.addWidget(self.presets)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        self.form = QVBoxLayout(host)
        self.form.setContentsMargins(0, 0, 6, 0)
        scroll.setWidget(host)
        rv.addWidget(scroll, 1)
        self.build_form(self.form)
        self.form.addStretch(1)

        cmd_box = QGroupBox("Commande ffmpeg")
        cv = QVBoxLayout(cmd_box)
        er = QHBoxLayout()
        er.addWidget(QLabel("Arguments en plus"))
        self.extra = self.binder.add("extra_args", line(placeholder="ex. -metadata title=\"Mon film\"  (ajoutés juste avant la sortie)"))
        er.addWidget(self.extra, 1)
        cv.addLayout(er)
        self.cmd_view = QPlainTextEdit()
        self.cmd_view.setReadOnly(True)
        self.cmd_view.setFont(QFont("Consolas", 9))
        self.cmd_view.setFixedHeight(64)
        cv.addWidget(self.cmd_view)
        rv.addWidget(cmd_box)
        self.warn = QLabel()
        self.warn.setObjectName("warn")
        self.warn.setWordWrap(True)
        self.warn.setVisible(False)
        rv.addWidget(self.warn)
        bottom = QHBoxLayout()
        b_copy = QPushButton("Copier la commande")
        self.b_add = QPushButton("Ajouter à la file d'attente  ➜")
        self.b_add.setObjectName("primary")
        bottom.addWidget(b_copy)
        bottom.addStretch(1)
        bottom.addWidget(self.b_add)
        rv.addLayout(bottom)
        split.addWidget(right)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        split.setSizes([400, 600])

        self.defaults = self.binder.get()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.update_preview)
        self.binder.on_change(self.schedule_preview)
        if self.files:
            self.files.changed.connect(self.schedule_preview)
            self.files.current_changed.connect(self.file_selected)
        b_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.cmd_view.toPlainText()))
        self.b_add.clicked.connect(lambda: self.add_requested.emit(self))
        QTimer.singleShot(0, self.update_preview)

    # ---------- à surcharger ----------
    def build_left(self) -> QWidget:
        self.files = FileList(self.extensions, self.files_title, self.reorder, self.files_hint)
        return self.files

    def build_form(self, layout: QVBoxLayout):
        raise NotImplementedError

    def make_job(self, src: Path, root: Path | None, preview: bool) -> Job | None:
        raise NotImplementedError

    def warnings(self) -> list[str]:
        return []

    # ---------- commun ----------
    def items(self) -> list[tuple[Path, Path | None]]:
        return self.files.items() if self.files else []

    def add_paths(self, paths: list[Path]):
        if self.files:
            self.files.add_paths(paths)

    def build_jobs(self, preview: bool = False) -> list[Job]:
        self.skipped = 0
        items = self.items()
        if not items:
            raise UserError("Ajoute au moins un fichier.")
        if preview:
            items = items[:1]
        jobs = []
        for src, root in items:
            job = self.make_job(src, root, preview)
            if job is None:
                self.skipped += 1
            else:
                jobs.append(job)
        return jobs

    def out_file(self, src, root, stem, ext, preview) -> Path | None:
        return self.ctx.resolve_output(src, root, stem, ext, preview)

    def out_dir(self, src, root, name, preview) -> Path | None:
        return self.ctx.resolve_output(src, root, name, "", preview, is_dir=True)

    def extra_args(self) -> list[str]:
        return parse_extra(self.extra.text())

    def schedule_preview(self):
        self._timer.start()

    def update_preview(self):
        try:
            if not self.items():
                text = "Ajoute des fichiers pour voir la commande ffmpeg."
            else:
                jobs = self.build_jobs(preview=True)
                text = cmdline(["ffmpeg", *jobs[0].args]) if jobs else ""
        except UserError as e:
            text = f"⚠ {e}"
        except Exception as e:  # ne jamais casser l'interface pour un aperçu
            text = f"⚠ Erreur : {e}"
        self.cmd_view.setPlainText(text)
        try:
            w = self.warnings()
        except Exception:
            w = []
        self.warn.setText("\n".join(f"⚠ {x}" for x in w))
        self.warn.setVisible(bool(w))

    def apply_settings(self, data: dict):
        self.binder.set(self.defaults)
        self.binder.set(data)

    def state(self) -> dict:
        return self.binder.get()

    def restore(self, data: dict):
        self.binder.set(data)
