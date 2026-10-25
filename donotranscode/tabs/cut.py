from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings, Qt, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import Job, UserError, temp_list_path
from ..ffmpeg import VIDEO_EXT, concat_escape, fmt_time, media_info, num, parse_time
from ..settings_form import check, combo, form_group
from ..widgets import TimeEdit, ext_filter
from .base import BaseTab
from .common import CONTAINERS, AudioEncoderBox, VideoEncoderBox


class _DropArea(QWidget):
    def __init__(self, on_drop):
        super().__init__()
        self.on_drop = on_drop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = [Path(u.toLocalFile()) for u in e.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.on_drop(paths)


class CutTab(BaseTab):
    tab_id = "cut"
    title = "Couper"
    extensions = VIDEO_EXT
    BUILTINS = {
        "Rapide — sans réencoder": {"mode": "fast"},
        "Précis — H.264 carte graphique": {"mode": "precise", "venc.encoder": "h264_nvenc", "venc.crf": 20,
                                           "aenc.codec": "aac"},
        "Précis — H.264 processeur": {"mode": "precise", "venc.encoder": "libx264", "venc.crf": 18,
                                      "venc.preset": "medium", "aenc.codec": "aac"},
    }

    def build_left(self):
        self.src: Path | None = None
        self.segments: list[tuple[float, float]] = []
        self._dragging = False
        w = _DropArea(self.add_paths)
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        top = QHBoxLayout()
        b_open = QPushButton("Ouvrir une vidéo…")
        b_open.clicked.connect(self._pick)
        self.lbl = QLabel("Aucune vidéo — glisse un fichier ici")
        self.lbl.setObjectName("hint")
        top.addWidget(b_open)
        top.addWidget(self.lbl, 1)
        v.addLayout(top)

        self.video = QVideoWidget()
        self.video.setMinimumHeight(220)
        self.video.setStyleSheet("background:#000;")
        v.addWidget(self.video, 1)
        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.6)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 0)
        v.addWidget(self.slider)
        ctl = QHBoxLayout()
        self.b_play = QPushButton("▶")
        self.b_play.setFixedWidth(44)
        ctl.addWidget(self.b_play)
        for label, delta in (("-5 s", -5000), ("-1 s", -1000), ("◀ image", "-f"), ("image ▶", "+f"),
                             ("+1 s", 1000), ("+5 s", 5000)):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, d=delta: self._step(d))
            ctl.addWidget(b)
        self.time_lbl = QLabel("00:00:00.000 / 00:00:00.000")
        ctl.addStretch(1)
        ctl.addWidget(self.time_lbl)
        v.addLayout(ctl)

        seg = QHBoxLayout()
        b_in = QPushButton("[  Début = ici")
        b_out = QPushButton("Fin = ici  ]")
        self.t_start = TimeEdit("début")
        self.t_end = TimeEdit("fin")
        b_add = QPushButton("+ Ajouter le segment")
        b_add.setObjectName("primary")
        seg.addWidget(b_in)
        seg.addWidget(self.t_start)
        seg.addWidget(self.t_end)
        seg.addWidget(b_out)
        seg.addWidget(b_add)
        v.addLayout(seg)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Début", "Fin", "Durée"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMaximumHeight(150)
        v.addWidget(self.table)
        row = QHBoxLayout()
        b_rm = QPushButton("Retirer le segment")
        b_clear = QPushButton("Vider les segments")
        hint = QLabel("Double-clic sur un segment pour y aller")
        hint.setObjectName("hint")
        row.addWidget(b_rm)
        row.addWidget(b_clear)
        row.addStretch(1)
        row.addWidget(hint)
        v.addLayout(row)

        self.b_play.clicked.connect(self._toggle_play)
        self.player.positionChanged.connect(self._on_pos)
        self.player.durationChanged.connect(lambda d: self.slider.setRange(0, d))
        self.player.playbackStateChanged.connect(
            lambda s: self.b_play.setText("⏸" if s == QMediaPlayer.PlayingState else "▶"))
        self.slider.sliderPressed.connect(lambda: setattr(self, "_dragging", True))
        self.slider.sliderReleased.connect(self._slider_released)
        self.slider.sliderMoved.connect(self.player.setPosition)
        b_in.clicked.connect(lambda: self.t_start.setText(fmt_time(self.player.position() / 1000)))
        b_out.clicked.connect(lambda: self.t_end.setText(fmt_time(self.player.position() / 1000)))
        b_add.clicked.connect(self._add_segment)
        b_rm.clicked.connect(self._remove_segment)
        b_clear.clicked.connect(self._clear_segments)
        self.table.cellDoubleClicked.connect(lambda r, _: self.player.setPosition(int(self.segments[r][0] * 1000)))
        self.t_start.textChanged.connect(lambda: self.schedule_preview())
        self.t_end.textChanged.connect(lambda: self.schedule_preview())
        return w

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Mode de coupe")
        self.mode = b.add("mode", combo([("fast", "Rapide — sans réencoder (coupe sur les images clés)"),
                                         ("precise", "Précis à l'image près — réencode")]))
        self.merge = b.add("merge", check("Réunir tous les segments dans un seul fichier"))
        self.container = b.add("container", combo([("same", "Même que l'original")] + CONTAINERS, "same"))
        f.addRow("Mode", self.mode)
        f.addRow("", self.merge)
        f.addRow("Conteneur", self.container)
        layout.addWidget(g)
        self.f_mode = f
        self.venc = VideoEncoderBox(b, allow_copy=False, default="h264_nvenc")
        self.aenc = AudioEncoderBox(b, allow_copy=True, default="aac")
        layout.addWidget(self.venc)
        layout.addWidget(self.aenc)
        self.mode.currentIndexChanged.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        precise = self.mode.currentData() == "precise"
        self.venc.setVisible(precise)
        self.aenc.setVisible(precise)
        self.f_mode.setRowVisible(self.container, precise)

    # ---------- lecteur ----------
    def _pick(self):
        start = QSettings().value("files/last_dir", "")
        f, _ = QFileDialog.getOpenFileName(self, "Ouvrir une vidéo", start, ext_filter(VIDEO_EXT))
        if f:
            QSettings().setValue("files/last_dir", str(Path(f).parent))
            self.add_paths([Path(f)])

    def add_paths(self, paths):
        p = next((p for p in paths if p.is_file() and p.suffix.lower() in VIDEO_EXT), None)
        if not p:
            return
        self.src = p
        self.lbl.setText(p.name)
        self.lbl.setToolTip(str(p))
        self.player.setSource(QUrl.fromLocalFile(str(p)))
        self.player.pause()
        self._clear_segments()
        self.t_start.clear()
        self.t_end.clear()
        self.file_selected.emit(p)
        self.schedule_preview()

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _step(self, delta):
        if isinstance(delta, str):
            info = media_info(self.src) if self.src else None
            frame = int(1000 / info.fps) if info and info.fps else 40
            self.player.pause()
            delta = frame if delta == "+f" else -frame
        self.player.setPosition(max(0, min(self.player.position() + delta, self.player.duration())))

    def _on_pos(self, pos):
        if not self._dragging:
            self.slider.setValue(pos)
        self.time_lbl.setText(f"{fmt_time(pos / 1000)} / {fmt_time(self.player.duration() / 1000)}")

    def _slider_released(self):
        self._dragging = False
        self.player.setPosition(self.slider.value())

    # ---------- segments ----------
    def _add_segment(self):
        try:
            s = parse_time(self.t_start.text()) or 0.0
            e = parse_time(self.t_end.text())
        except ValueError:
            return
        if e is None:
            e = self.player.duration() / 1000
        if e <= s:
            self.t_end.setStyleSheet("border: 1px solid #ff6b6b;")
            return
        self.segments.append((s, e))
        self._refresh_table()
        self.t_start.setText(fmt_time(e))
        self.t_end.clear()

    def _remove_segment(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for r in rows:
            del self.segments[r]
        self._refresh_table()

    def _clear_segments(self):
        self.segments.clear()
        self._refresh_table()

    def _refresh_table(self):
        self.table.setRowCount(len(self.segments))
        for r, (s, e) in enumerate(self.segments):
            for c, t in enumerate((fmt_time(s), fmt_time(e), fmt_time(e - s))):
                self.table.setItem(r, c, QTableWidgetItem(t))
        self.schedule_preview()

    # ---------- commandes ----------
    def items(self):
        return [(self.src, None)] if self.src else []

    def _segments(self) -> list[tuple[float, float]]:
        if self.segments:
            return list(self.segments)
        s = self.t_start.seconds("Début")
        e = self.t_end.seconds("Fin")
        if s is None and e is None:
            raise UserError("Indique un début et/ou une fin, ou ajoute des segments.")
        if e is None:
            info = media_info(self.src)
            e = info.duration if info else 0
        s = s or 0.0
        if e <= s:
            raise UserError("La fin doit être après le début.")
        return [(s, e)]

    def build_jobs(self, preview=False):
        self.skipped = 0
        if not self.src:
            raise UserError("Ouvre une vidéo.")
        src = self.src
        segs = self._segments()
        precise = self.mode.currentData() == "precise"
        cont = self.container.currentData()
        ext = cont if precise and cont != "same" else src.suffix.lower().lstrip(".")
        extra = self.extra_args()
        jobs = []

        if self.merge.isChecked() and len(segs) > 1:
            out = self.out_file(src, None, f"{src.stem}_montage", ext, preview)
            if out is None:
                self.skipped = 1
                return []
            total = sum(e - s for s, e in segs)
            if precise:
                info = media_info(src)
                has_a = bool(info and info.has_audio) and self.aenc.codec_name() not in ("none",)
                parts, labels = [], ""
                for i, (s, e) in enumerate(segs):
                    parts.append(f"[0:v]trim=start={num(s)}:end={num(e)},setpts=PTS-STARTPTS[v{i}]")
                    labels += f"[v{i}]"
                    if has_a:
                        parts.append(f"[0:a]atrim=start={num(s)}:end={num(e)},asetpts=PTS-STARTPTS[a{i}]")
                        labels += f"[a{i}]"
                parts.append(f"{labels}concat=n={len(segs)}:v=1:a={1 if has_a else 0}[v]" + ("[a]" if has_a else ""))
                a = ["-i", str(src), "-filter_complex", ";".join(parts), "-map", "[v]"]
                if has_a:
                    a += ["-map", "[a]"]
                a += self.venc.args()
                aargs = self.aenc.args()
                if has_a and aargs[:2] == ["-c:a", "copy"]:
                    aargs = ["-c:a", "aac", "-b:a", "192k"]  # un flux filtré ne peut pas être copié
                a += aargs if has_a else ["-an"]
                a += extra + [str(out)]
                jobs.append(Job(title=src.name, operation=f"Couper + réunir {len(segs)} segments", args=a,
                                outputs=[out], duration=total))
            else:
                lst = temp_list_path()
                lines = []
                for s, e in segs:
                    lines += [f"file '{concat_escape(src)}'", f"inpoint {num(s)}", f"outpoint {num(e)}"]
                a = ["-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0:v?", "-map", "0:a?",
                     "-c", "copy", "-avoid_negative_ts", "make_zero"] + extra + [str(out)]
                jobs.append(Job(title=src.name, operation=f"Couper + réunir {len(segs)} segments (copie)",
                                args=a, outputs=[out], duration=total,
                                temp_content={lst: "\n".join(lines) + "\n"}))
            return jobs

        for i, (s, e) in enumerate(segs, 1):
            name = f"{src.stem}_extrait" if len(segs) == 1 else f"{src.stem}_partie{i}"
            out = self.out_file(src, None, name, ext, preview)
            if out is None:
                self.skipped += 1
                continue
            a = ["-ss", num(s), "-to", num(e), "-i", str(src)]
            if precise:
                a += ["-map", "0:v:0", "-map", "0:a?"] + self.venc.args() + self.aenc.args()
            else:
                a += ["-map", "0:v?", "-map", "0:a?", "-map", "0:s?", "-c", "copy",
                      "-avoid_negative_ts", "make_zero"]
            if ext in ("mp4", "mov"):
                a += ["-movflags", "+faststart"]
            a += extra + [str(out)]
            jobs.append(Job(title=src.name, operation=f"Couper {fmt_time(s)} → {fmt_time(e)}", args=a,
                            outputs=[out], duration=e - s))
            if preview:
                break
        return jobs

    def warnings(self):
        w = []
        if self.mode.currentData() == "fast":
            w.append("Mode rapide : le début est calé sur l'image clé précédente (peut décaler de quelques secondes).")
        else:
            ext = self.container.currentData()
            w += self.venc.warnings(None if ext == "same" else ext)
        return w

    def state(self):
        return self.binder.get()

    def shutdown(self):
        self.player.stop()
