from __future__ import annotations

import json
import os
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer
from PySide6.QtWidgets import (QApplication, QLabel, QMainWindow, QMessageBox, QSplitter, QTabWidget,
                               QVBoxLayout, QWidget)

from . import APP_NAME, __version__
from .core import UserError
from .ffmpeg import FFMPEG, ffmpeg_version, safe_name
from .queue import QueueWidget
from .tabs import ALL_TABS
from .theme import dark_title_bar, make_icon
from .widgets import InfoPanel, OutputBar


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(make_icon())
        self.resize(1400, 900)
        self.setAcceptDrops(True)
        self._batch: set[str] = set()

        central = QWidget()
        v = QVBoxLayout(central)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        self.output_bar = OutputBar()
        v.addWidget(self.output_bar)

        self.tabs = QTabWidget()
        self.tab_list = []
        for cls in ALL_TABS:
            tab = cls(self)
            self.tab_list.append(tab)
            self.tabs.addTab(tab, cls.title)
            tab.file_selected.connect(self._on_file_selected)
            tab.add_requested.connect(self.add_from_tab)
        self.info = InfoPanel()
        self.hsplit = QSplitter(Qt.Horizontal)
        self.hsplit.addWidget(self.tabs)
        self.hsplit.addWidget(self.info)
        self.hsplit.setStretchFactor(0, 1)
        self.hsplit.setSizes([1100, 300])

        self.queue = QueueWidget()
        self.vsplit = QSplitter(Qt.Vertical)
        self.vsplit.addWidget(self.hsplit)
        self.vsplit.addWidget(self.queue)
        self.vsplit.setStretchFactor(0, 1)
        self.vsplit.setSizes([640, 260])
        v.addWidget(self.vsplit, 1)
        self.setCentralWidget(central)

        self.ver_label = QLabel()
        self.ver_label.setObjectName("hint")
        self.statusBar().addPermanentWidget(self.ver_label)
        self.queue.all_done.connect(self._on_queue_done)
        self.output_bar.changed.connect(self._refresh_previews)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self._restore()
        QTimer.singleShot(100, self._check_ffmpeg)

    # ---------- démarrage / fermeture ----------
    def _check_ffmpeg(self):
        ver = ffmpeg_version()
        local = "inclus" if "bin" in Path(FFMPEG).parts else "système"
        self.ver_label.setText(f"{APP_NAME} {__version__}  ·  ffmpeg {ver} ({local})  ")
        if ver == "introuvable":
            QMessageBox.critical(self, "ffmpeg introuvable",
                                 "ffmpeg.exe est introuvable.\nCopie ffmpeg.exe et ffprobe.exe dans le dossier « bin » de l'application.")

    def showEvent(self, e):
        super().showEvent(e)
        dark_title_bar(self)

    def _restore(self):
        s = QSettings()
        geo = s.value("win/geometry")
        if isinstance(geo, QByteArray):
            self.restoreGeometry(geo)
        for key, split in (("win/hsplit", self.hsplit), ("win/vsplit", self.vsplit)):
            st = s.value(key)
            if isinstance(st, QByteArray):
                split.restoreState(st)
        for tab in self.tab_list:
            raw = s.value(f"tab/{tab.tab_id}")
            if raw:
                try:
                    tab.restore(json.loads(raw))
                except (ValueError, TypeError):
                    pass
        self.tabs.setCurrentIndex(int(s.value("win/tab", 0)))
        self.queue.chk_auto.setChecked(s.value("queue/auto", True, type=bool))
        self.queue.chk_log.setChecked(s.value("queue/log", False, type=bool))

    def _save(self):
        s = QSettings()
        s.setValue("win/geometry", self.saveGeometry())
        s.setValue("win/hsplit", self.hsplit.saveState())
        s.setValue("win/vsplit", self.vsplit.saveState())
        s.setValue("win/tab", self.tabs.currentIndex())
        s.setValue("queue/auto", self.queue.chk_auto.isChecked())
        s.setValue("queue/log", self.queue.chk_log.isChecked())
        for tab in self.tab_list:
            s.setValue(f"tab/{tab.tab_id}", json.dumps(tab.state(), ensure_ascii=False))
        self.output_bar.save()

    def closeEvent(self, e):
        if self.queue.is_busy() or self.queue.pending_count():
            r = QMessageBox.question(self, "Quitter ?",
                                     "Des tâches sont en cours ou en attente.\nQuitter quand même (la tâche en cours sera annulée) ?")
            if r != QMessageBox.Yes:
                e.ignore()
                return
        self._save()
        self.queue.shutdown()
        for tab in self.tab_list:
            if hasattr(tab, "shutdown"):
                tab.shutdown()
        e.accept()

    # ---------- glisser-déposer sur la fenêtre ----------
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.tabs.currentWidget().add_paths(paths)

    # ---------- sortie ----------
    def _reserved(self) -> set[str]:
        return self.queue.reserved() | self._batch

    def base_dir(self, src: Path | None, root: Path | None, preview: bool) -> Path:
        base = self.output_bar.directory()
        if base is None:
            if preview:
                base = Path("[dossier de sortie]")
            else:
                raise UserError("Choisis d'abord un dossier de sortie (en haut).")
        if src is not None and root is not None and self.output_bar.keep_tree.isChecked():
            try:
                base = base / src.parent.relative_to(root)
            except ValueError:
                pass
        return base

    def resolve_output(self, src, root, stem, ext, preview=False, is_dir=False) -> Path | None:
        """Chemin de sortie selon le dossier choisi, le suffixe et la règle « si le fichier existe »."""
        base = self.base_dir(src, root, preview)
        stem = safe_name(stem + self.output_bar.suffix.text())

        def name(n):
            s = stem if n == 0 else f"{stem}_{n}"
            return base / (s if is_dir else f"{s}.{ext}")

        cand = name(0)
        if preview:
            return cand
        reserved = self._reserved()
        src_key = os.path.normcase(str(Path(src).absolute())) if src else None

        def taken(p):
            return os.path.normcase(str(p)) in reserved

        def is_src(p):
            return src_key is not None and os.path.normcase(str(p.absolute())) == src_key

        policy = self.output_bar.policy.currentData()
        if policy == "overwrite" and not taken(cand) and not is_src(cand):
            self._batch.add(os.path.normcase(str(cand)))
            return cand
        if policy == "skip":
            if cand.exists() or taken(cand) or is_src(cand):
                return None
            self._batch.add(os.path.normcase(str(cand)))
            return cand
        n = 0
        while True:
            p = name(n)
            if not p.exists() and not taken(p) and not is_src(p):
                self._batch.add(os.path.normcase(str(p)))
                return p
            n += 1

    # ---------- actions ----------
    def add_from_tab(self, tab):
        if self.output_bar.directory() is None and not self.output_bar.choose():
            return
        out_dir = self.output_bar.directory()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            QMessageBox.warning(self, "Dossier de sortie", f"Impossible d'utiliser ce dossier :\n{e}")
            return
        self._batch = set()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            jobs = tab.build_jobs(preview=False)
        except UserError as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, tab.title, str(e))
            return
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, tab.title, f"Erreur inattendue :\n{e}")
            return
        finally:
            self._batch = set()
        QApplication.restoreOverrideCursor()
        skipped = tab.skipped
        if not jobs:
            QMessageBox.information(self, tab.title, "Rien à faire : les fichiers de sortie existent déjà "
                                                     "(règle « Ignorer »)." if skipped else "Rien à faire.")
            return
        self.queue.add_jobs(jobs)
        msg = f"{len(jobs)} tâche(s) ajoutée(s)"
        if skipped:
            msg += f" · {skipped} ignorée(s) (le fichier existe déjà)"
        self.statusBar().showMessage(msg, 8000)
        if self.queue.chk_auto.isChecked():
            self.queue.start()

    def _on_queue_done(self, ok, err):
        msg = f"File terminée : {ok} réussie(s)" + (f", {err} erreur(s)" if err else "")
        self.statusBar().showMessage(msg, 0)
        QApplication.alert(self)
        if err and not self.queue.chk_log.isChecked():
            self.statusBar().showMessage(msg + " — sélectionne une tâche en erreur et coche « Journal » pour le détail", 0)

    def _on_file_selected(self, path):
        if self.sender() is self.tabs.currentWidget():
            self.info.show_file(path)

    def _on_tab_changed(self, _):
        tab = self.tabs.currentWidget()
        path = None
        if tab.files and tab.files.list.currentItem():
            path = Path(tab.files.list.currentItem().data(Qt.UserRole))
        elif getattr(tab, "src", None):
            path = tab.src
        self.info.show_file(path)

    def _refresh_previews(self):
        for tab in self.tab_list:
            tab.schedule_preview()
