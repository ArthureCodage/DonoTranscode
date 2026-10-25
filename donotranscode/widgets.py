"""Widgets réutilisables : liste de fichiers, barre de sortie, infos, préréglages, champ de temps."""
from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QSettings, Qt, QThreadPool, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from . import presets
from .core import UserError
from .ffmpeg import fmt_size, fmt_time, media_info, natural_key, parse_time, thumbnail


def ext_filter(exts: set[str], label: str = "Fichiers pris en charge") -> str:
    pats = " ".join(f"*{e}" for e in sorted(exts))
    return f"{label} ({pats});;Tous les fichiers (*.*)"


# ---------- liste de fichiers ----------

class _DropList(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, reorder: bool, hint: str):
        super().__init__()
        self.hint = hint
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setAlternatingRowColors(True)
        self.setAcceptDrops(True)
        if reorder:
            self.setDragDropMode(QAbstractItemView.InternalMove)
            self.setDefaultDropAction(Qt.MoveAction)
        else:
            self.setDragDropMode(QAbstractItemView.DropOnly)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dropEvent(self, e):
        if e.mimeData().hasUrls():
            paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
            e.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            super().dropEvent(e)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self.count() == 0:
            qp = QPainter(self.viewport())
            qp.setPen(self.palette().placeholderText().color())
            qp.drawText(self.viewport().rect().adjusted(12, 12, -12, -12),
                        Qt.AlignCenter | Qt.TextWordWrap, self.hint)


class FileList(QWidget):
    changed = Signal()
    current_changed = Signal(object)

    def __init__(self, extensions: set[str], title="Fichiers", reorder=False,
                 hint="Glisse des fichiers ou des dossiers ici"):
        super().__init__()
        self.extensions = extensions
        self._keys: set[str] = set()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.title = title
        self.header = QLabel()
        f = self.header.font()
        f.setBold(True)
        self.header.setFont(f)
        v.addWidget(self.header)
        self.list = _DropList(reorder, hint)
        v.addWidget(self.list, 1)
        row1 = QHBoxLayout()
        b_files = QPushButton("+ Fichiers…")
        b_dir = QPushButton("+ Dossier…")
        self.recursive = QCheckBox("avec sous-dossiers")
        self.recursive.setChecked(QSettings().value("files/recursive", False, type=bool))
        self.recursive.toggled.connect(lambda v: QSettings().setValue("files/recursive", v))
        row1.addWidget(b_files)
        row1.addWidget(b_dir)
        row1.addWidget(self.recursive)
        row1.addStretch(1)
        v.addLayout(row1)
        row2 = QHBoxLayout()
        b_rm = QPushButton("Retirer")
        b_clear = QPushButton("Vider")
        row2.addWidget(b_rm)
        row2.addWidget(b_clear)
        if reorder:
            b_up, b_down, b_sort = QPushButton("▲"), QPushButton("▼"), QPushButton("Trier A→Z")
            for b in (b_up, b_down):
                b.setFixedWidth(36)
            b_up.clicked.connect(lambda: self._move(-1))
            b_down.clicked.connect(lambda: self._move(1))
            b_sort.clicked.connect(self.sort_natural)
            row2.addWidget(b_up)
            row2.addWidget(b_down)
            row2.addWidget(b_sort)
        row2.addStretch(1)
        v.addLayout(row2)

        b_files.clicked.connect(self.pick_files)
        b_dir.clicked.connect(self.pick_folder)
        b_rm.clicked.connect(self.remove_selected)
        b_clear.clicked.connect(self.clear)
        self.list.files_dropped.connect(self.add_paths)
        self.list.currentItemChanged.connect(lambda cur, _: self.current_changed.emit(
            Path(cur.data(Qt.UserRole)) if cur else None))
        self.list.model().rowsMoved.connect(lambda *_: self.changed.emit())
        self._update_header()

    # --- ajout ---
    def _last_dir(self) -> str:
        return QSettings().value("files/last_dir", str(Path.home()))

    def pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Ajouter des fichiers", self._last_dir(),
                                                ext_filter(self.extensions))
        if files:
            QSettings().setValue("files/last_dir", str(Path(files[0]).parent))
            self.add_paths([Path(f) for f in files])

    def pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Ajouter un dossier", self._last_dir())
        if d:
            QSettings().setValue("files/last_dir", d)
            self.add_paths([Path(d)])

    def add_paths(self, paths: list[Path]):
        added = 0
        for p in paths:
            if p.is_dir():
                it = p.rglob("*") if self.recursive.isChecked() else p.iterdir()
                files = sorted((f for f in it if f.is_file() and f.suffix.lower() in self.extensions),
                               key=natural_key)
                for f in files:
                    added += self._add(f, p)
            elif p.is_file() and p.suffix.lower() in self.extensions:
                added += self._add(p, None)
        if added:
            if self.list.currentRow() < 0:
                self.list.setCurrentRow(0)
            self._update_header()
            self.changed.emit()
        elif paths:
            QMessageBox.information(self, "Aucun fichier ajouté",
                                    "Aucun fichier pris en charge par cet onglet (ou déjà dans la liste).")

    def _add(self, path: Path, root: Path | None) -> int:
        key = os.path.normcase(str(path))
        if key in self._keys:
            return 0
        self._keys.add(key)
        text = str(path.relative_to(root)) if root else path.name
        item = QListWidgetItem(text)
        item.setToolTip(str(path))
        item.setData(Qt.UserRole, str(path))
        item.setData(Qt.UserRole + 1, str(root) if root else "")
        self.list.addItem(item)
        return 1

    # --- gestion ---
    def remove_selected(self):
        for item in self.list.selectedItems():
            self._keys.discard(os.path.normcase(item.data(Qt.UserRole)))
            self.list.takeItem(self.list.row(item))
        self._update_header()
        self.changed.emit()

    def clear(self):
        self.list.clear()
        self._keys.clear()
        self._update_header()
        self.changed.emit()
        self.current_changed.emit(None)

    def _move(self, delta: int):
        rows = sorted({self.list.row(i) for i in self.list.selectedItems()}, reverse=delta > 0)
        for r in rows:
            nr = r + delta
            if 0 <= nr < self.list.count():
                item = self.list.takeItem(r)
                self.list.insertItem(nr, item)
                item.setSelected(True)
        self.changed.emit()

    def sort_natural(self):
        items = [self.list.takeItem(0) for _ in range(self.list.count())]
        for it in sorted(items, key=lambda i: natural_key(i.data(Qt.UserRole))):
            self.list.addItem(it)
        self.changed.emit()

    def items(self) -> list[tuple[Path, Path | None]]:
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            root = it.data(Qt.UserRole + 1)
            out.append((Path(it.data(Qt.UserRole)), Path(root) if root else None))
        return out

    def _update_header(self):
        n = self.list.count()
        self.header.setText(f"{self.title}  ({n})" if n else self.title)


# ---------- champ de temps ----------

class TimeEdit(QLineEdit):
    def __init__(self, placeholder="hh:mm:ss.ms"):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setToolTip("Exemples : 90  ·  1:30  ·  00:01:30.250")
        self.textChanged.connect(self._validate)

    def _validate(self):
        try:
            parse_time(self.text())
            self.setStyleSheet("")
        except ValueError:
            self.setStyleSheet("border: 1px solid #ff6b6b;")

    def seconds(self, label: str) -> float | None:
        try:
            return parse_time(self.text())
        except ValueError:
            raise UserError(f"{label} : temps invalide « {self.text()} » (ex. 1:30 ou 00:01:30.5)")


# ---------- barre du dossier de sortie ----------

class OutputBar(QWidget):
    changed = Signal()

    POLICIES = [("rename", "Renommer (_1, _2…)"), ("overwrite", "Écraser"), ("skip", "Ignorer")]

    def __init__(self):
        super().__init__()
        s = QSettings()
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 6, 8, 2)
        lbl = QLabel("Dossier de sortie")
        f = lbl.font()
        f.setBold(True)
        lbl.setFont(f)
        self.path = QLineEdit(s.value("output/dir", ""))
        self.path.setPlaceholderText("Choisis où enregistrer les fichiers…")
        b_choose = QPushButton("Choisir…")
        b_open = QPushButton("📂")
        b_open.setToolTip("Ouvrir le dossier de sortie")
        b_open.setFixedWidth(36)
        self.suffix = QLineEdit(s.value("output/suffix", ""))
        self.suffix.setPlaceholderText("ex. _converti")
        self.suffix.setFixedWidth(110)
        self.suffix.setToolTip("Texte ajouté à la fin du nom des fichiers créés")
        self.policy = QComboBox()
        for data, label in self.POLICIES:
            self.policy.addItem(label, data)
        i = self.policy.findData(s.value("output/policy", "rename"))
        self.policy.setCurrentIndex(max(i, 0))
        self.keep_tree = QCheckBox("Recréer les sous-dossiers")
        self.keep_tree.setToolTip("Quand tu ajoutes un dossier, recrée sa structure dans le dossier de sortie")
        self.keep_tree.setChecked(s.value("output/keep_tree", True, type=bool))
        h.addWidget(lbl)
        h.addWidget(self.path, 1)
        h.addWidget(b_choose)
        h.addWidget(b_open)
        h.addSpacing(12)
        h.addWidget(QLabel("Suffixe"))
        h.addWidget(self.suffix)
        h.addSpacing(12)
        h.addWidget(QLabel("Si le fichier existe"))
        h.addWidget(self.policy)
        h.addSpacing(12)
        h.addWidget(self.keep_tree)
        b_choose.clicked.connect(self.choose)
        b_open.clicked.connect(self.open)
        for sig in (self.path.textChanged, self.suffix.textChanged, self.policy.currentIndexChanged,
                    self.keep_tree.toggled):
            sig.connect(lambda *_: (self.save(), self.changed.emit()))

    def directory(self) -> Path | None:
        t = self.path.text().strip().strip('"')
        return Path(t) if t else None

    def choose(self) -> bool:
        start = str(self.directory() or QSettings().value("files/last_dir", str(Path.home())))
        d = QFileDialog.getExistingDirectory(self, "Dossier de sortie", start)
        if d:
            self.path.setText(str(Path(d)))
            return True
        return False

    def open(self):
        d = self.directory()
        if d and d.is_dir():
            os.startfile(str(d))

    def save(self):
        s = QSettings()
        s.setValue("output/dir", self.path.text().strip())
        s.setValue("output/suffix", self.suffix.text())
        s.setValue("output/policy", self.policy.currentData())
        s.setValue("output/keep_tree", self.keep_tree.isChecked())


# ---------- panneau d'infos ----------

class _InfoSignals(QObject):
    done = Signal(str, object, bytes)


class _InfoTask(QRunnable):
    def __init__(self, path: Path, signals: _InfoSignals):
        super().__init__()
        self.path, self.signals = path, signals

    def run(self):
        info = media_info(self.path)
        thumb = thumbnail(self.path, info) if info and (info.has_video or info.is_image) else b""
        self.signals.done.emit(str(self.path), info, thumb)


class InfoPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumWidth(240)
        self.current: str | None = None
        self.signals = _InfoSignals()
        self.signals.done.connect(self._on_done)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        title = QLabel("Infos du fichier")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        v.addWidget(title)
        self.thumb = QLabel()
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setMinimumHeight(150)
        self.thumb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.thumb.setStyleSheet("background:#151618; border:1px solid #3a3d42; border-radius:4px;")
        v.addWidget(self.thumb)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 6, 0, 0)
        self.form.setLabelAlignment(Qt.AlignRight)
        v.addWidget(self.form_host)
        v.addStretch(1)
        self._pix: QPixmap | None = None
        self.show_file(None)

    def _clear_form(self):
        while self.form.rowCount():
            self.form.removeRow(0)

    def _row(self, label, text):
        val = QLabel(text)
        val.setWordWrap(True)
        val.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.form.addRow(QLabel(f"<span style='color:#8b9099'>{label}</span>"), val)

    def show_file(self, path):
        self._clear_form()
        self._pix = None
        self.thumb.clear()
        if not path:
            self.current = None
            self.thumb.setText("Sélectionne un fichier")
            return
        self.current = str(path)
        self.thumb.setText("Chargement…")
        self._row("Fichier", Path(path).name)
        QThreadPool.globalInstance().start(_InfoTask(Path(path), self.signals))

    def _on_done(self, path, info, thumb):
        if path != self.current:
            return
        self._clear_form()
        p = Path(path)
        self._row("Fichier", p.name)
        self._row("Dossier", str(p.parent))
        if info is None:
            self.thumb.setText("Fichier illisible")
            return
        self._row("Taille", fmt_size(info.size))
        self._row("Format", info.format_name)
        if not info.is_image and info.duration:
            self._row("Durée", fmt_time(info.duration))
        if info.has_video:
            fps = f" · {info.fps:.3f}".rstrip("0").rstrip(".") + " ips" if info.fps and not info.is_image else ""
            self._row("Image" if info.is_image else "Vidéo",
                      f"{info.vcodec} · {info.width}×{info.height}{fps}" + (f" · {info.pix_fmt}" if info.pix_fmt else ""))
        if info.has_audio:
            ch = {1: "mono", 2: "stéréo", 6: "5.1", 8: "7.1"}.get(info.channels, f"{info.channels} canaux")
            extra = f" · {info.audio_tracks} pistes" if info.audio_tracks > 1 else ""
            self._row("Audio", f"{info.acodec} · {info.sample_rate} Hz · {ch}{extra}")
        if info.subtitle_tracks:
            self._row("Sous-titres", f"{info.subtitle_tracks} piste(s)")
        if info.bitrate and not info.is_image:
            self._row("Débit", f"{info.bitrate / 1000:.0f} kb/s")
        if thumb:
            pm = QPixmap()
            pm.loadFromData(thumb)
            self._pix = pm
            self._fit_thumb()
        else:
            self.thumb.setText("Pas d'aperçu (audio)" if info.has_audio else "Pas d'aperçu")

    def _fit_thumb(self):
        if self._pix and not self._pix.isNull():
            w = max(self.thumb.width() - 4, 50)
            self.thumb.setPixmap(self._pix.scaled(w, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_thumb()


# ---------- préréglages ----------

class PresetBar(QWidget):
    def __init__(self, tab_id: str, builtins: dict, get_fn, apply_fn):
        super().__init__()
        self.tab_id, self.builtins, self.get_fn, self.apply_fn = tab_id, builtins, get_fn, apply_fn
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(QLabel("Préréglage"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(280)
        b_save = QPushButton("Enregistrer…")
        b_save.setToolTip("Enregistrer les réglages actuels comme préréglage perso")
        self.b_del = QPushButton("Supprimer")
        h.addWidget(self.combo, 1)
        h.addWidget(b_save)
        h.addWidget(self.b_del)
        self.combo.activated.connect(self._load)
        self.combo.currentIndexChanged.connect(self._update_del)
        b_save.clicked.connect(self._save)
        self.b_del.clicked.connect(self._delete)
        self.reload()

    def reload(self, select: str | None = None):
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("— choisir un préréglage —", None)
        for name in self.builtins:
            self.combo.addItem(f"★ {name}", ("b", name))
        for name in sorted(presets.user_presets(self.tab_id), key=str.lower):
            self.combo.addItem(name, ("u", name))
        if select:
            i = self.combo.findData(("u", select))
            self.combo.setCurrentIndex(max(i, 0))
        self.combo.blockSignals(False)
        self._update_del()

    def _update_del(self):
        d = self.combo.currentData()
        self.b_del.setEnabled(bool(d) and d[0] == "u")

    def _load(self, _=None):
        d = self.combo.currentData()
        if not d:
            return
        kind, name = d
        data = self.builtins.get(name) if kind == "b" else presets.user_presets(self.tab_id).get(name)
        if data is not None:
            self.apply_fn(data)

    def _save(self):
        d = self.combo.currentData()
        default = d[1] if d and d[0] == "u" else ""
        name, ok = QInputDialog.getText(self, "Enregistrer le préréglage", "Nom du préréglage :", text=default)
        name = name.strip()
        if not ok or not name:
            return
        if name in self.builtins:
            QMessageBox.warning(self, "Nom déjà pris", "Ce nom est celui d'un préréglage intégré.")
            return
        if name in presets.user_presets(self.tab_id) and name != default:
            if QMessageBox.question(self, "Remplacer ?", f"Remplacer le préréglage « {name} » ?") != QMessageBox.Yes:
                return
        presets.save_preset(self.tab_id, name, self.get_fn())
        self.reload(select=name)

    def _delete(self):
        d = self.combo.currentData()
        if not d or d[0] != "u":
            return
        if QMessageBox.question(self, "Supprimer ?", f"Supprimer le préréglage « {d[1]} » ?") == QMessageBox.Yes:
            presets.delete_preset(self.tab_id, d[1])
            self.reload()
