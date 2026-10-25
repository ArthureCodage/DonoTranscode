from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QPushButton, QWidget

from ..core import Job, UserError, temp_list_path
from ..ffmpeg import AUDIO_EXT, IMAGE_EXT, VIDEO_EXT, concat_escape, media_info, num
from ..settings_form import check, combo, dspin, form_group, line, spin
from ..widgets import ext_filter
from .base import BaseTab
from .common import VideoEncoderBox

SIZES = [("auto", "Taille de la 1re image"), ("1920x1080", "1920×1080 (1080p)"), ("1280x720", "1280×720 (720p)"),
         ("3840x2160", "3840×2160 (4K)"), ("1080x1920", "1080×1920 (vertical)"), ("1080x1080", "1080×1080 (carré)"),
         ("custom", "Personnalisée")]


class SlideshowTab(BaseTab):
    tab_id = "slideshow"
    title = "Images → vidéo"
    extensions = IMAGE_EXT
    reorder = True
    files_title = "Images (dans l'ordre de la vidéo)"
    files_hint = "Glisse des images ou un dossier ici\nL'ordre de la liste = l'ordre dans la vidéo\n(glisse les lignes pour réordonner)"
    BUILTINS = {
        "Animation — 24 images/s": {"timing": "fps", "fps": 24},
        "Diaporama 1080p — 4 s par image": {"timing": "spi", "spi": 4, "size": "1920x1080", "fit": "pad"},
        "Timelapse — 30 images/s, GPU": {"timing": "fps", "fps": 30, "venc.encoder": "h264_nvenc"},
    }

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Sortie")
        self.name = b.add("name", line("diaporama"))
        self.container = b.add("container", combo([("mp4", "MP4"), ("mkv", "MKV"), ("webm", "WebM"), ("mov", "MOV")]))
        f.addRow("Nom du fichier", self.name)
        f.addRow("Conteneur", self.container)
        layout.addWidget(g)

        g, f = form_group("Durée")
        self.f_t = f
        self.timing = b.add("timing", combo([("fps", "Images par seconde (animation, timelapse)"),
                                              ("spi", "Secondes par image (diaporama)")]))
        self.fps = b.add("fps", dspin(0.1, 240, 24, 3, " images/s", 1))
        self.spi = b.add("spi", dspin(0.1, 600, 3, 2, " s", 0.5))
        self.out_fps = b.add("out_fps", spin(1, 120, 30, " ips"))
        f.addRow("Mode", self.timing)
        f.addRow("Vitesse", self.fps)
        f.addRow("Durée par image", self.spi)
        f.addRow("Images/s de la vidéo", self.out_fps)
        layout.addWidget(g)

        g, f = form_group("Taille")
        self.f_s = f
        self.size = b.add("size", combo(SIZES, "auto"))
        self.cw = b.add("w", spin(16, 16384, 1920, " px"))
        self.ch = b.add("h", spin(16, 16384, 1080, " px"))
        self.fit = b.add("fit", combo([("pad", "Ajuster avec des bandes"), ("crop", "Remplir (recadre)"),
                                       ("stretch", "Étirer")]))
        self.pad = b.add("pad_color", combo([("black", "Noir"), ("white", "Blanc")]))
        f.addRow("Taille", self.size)
        f.addRow("Largeur", self.cw)
        f.addRow("Hauteur", self.ch)
        f.addRow("Images de tailles différentes", self.fit)
        f.addRow("Couleur des bandes", self.pad)
        layout.addWidget(g)

        self.venc = VideoEncoderBox(b, allow_copy=False, default_pix="yuv420p")
        self.venc.crf.setValue(20)
        layout.addWidget(self.venc)

        g, f = form_group("Musique (optionnel)")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        self.music = b.add("music", line(placeholder="Aucune"))
        pick = QPushButton("Parcourir…")
        pick.clicked.connect(self._pick_music)
        h.addWidget(self.music, 1)
        h.addWidget(pick)
        self.shortest = b.add("shortest", check("Arrêter au plus court (vidéo ou musique)", True))
        self.abitrate = b.add("abitrate", combo(["128k", "192k", "256k", "320k"], "192k"))
        f.addRow("Fichier audio", row)
        f.addRow("", self.shortest)
        f.addRow("Débit audio", self.abitrate)
        layout.addWidget(g)

        self.timing.currentIndexChanged.connect(self._update_rows)
        self.size.currentIndexChanged.connect(self._update_rows)
        self.fit.currentIndexChanged.connect(self._update_rows)
        self._update_rows()

    def _pick_music(self):
        f, _ = QFileDialog.getOpenFileName(self, "Musique", "", ext_filter(AUDIO_EXT | VIDEO_EXT))
        if f:
            self.music.setText(str(Path(f)))

    def _update_rows(self, *_):
        spi = self.timing.currentData() == "spi"
        self.f_t.setRowVisible(self.fps, not spi)
        self.f_t.setRowVisible(self.spi, spi)
        self.f_t.setRowVisible(self.out_fps, spi)
        custom = self.size.currentData() == "custom"
        self.f_s.setRowVisible(self.cw, custom)
        self.f_s.setRowVisible(self.ch, custom)
        self.f_s.setRowVisible(self.pad, self.fit.currentData() == "pad")

    def build_jobs(self, preview=False):
        self.skipped = 0
        files = [p for p, _ in self.items()]
        if not files:
            raise UserError("Ajoute des images.")
        d = self.binder.get()
        if d["size"] == "auto":
            info = media_info(files[0])
            if not info or not info.width:
                raise UserError(f"Impossible de lire la taille de {files[0].name}")
            W, H = info.width // 2 * 2, info.height // 2 * 2
        elif d["size"] == "custom":
            W, H = d["w"] // 2 * 2, d["h"] // 2 * 2
        else:
            W, H = (int(x) for x in d["size"].split("x"))
        if d["timing"] == "fps":
            per, fps = 1 / d["fps"], num(d["fps"])
        else:
            per, fps = d["spi"], str(d["out_fps"])
        lines = []
        for p in files:
            lines += [f"file '{concat_escape(p)}'", f"duration {per:.6f}"]
        lines.append(f"file '{concat_escape(files[-1])}'")
        ext = d["container"]
        out = self.out_file(None, None, d["name"] or "diaporama", ext, preview)
        if out is None:
            self.skipped = 1
            return []
        lst = temp_list_path()
        fit = d["fit"]
        if fit == "pad":
            vf = f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color={d['pad_color']}"
        elif fit == "crop":
            vf = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        else:
            vf = f"scale={W}:{H}"
        vf += f",setsar=1,fps={fps}"
        a = ["-f", "concat", "-safe", "0", "-i", str(lst)]
        music = d["music"].strip().strip('"')
        if music:
            if not Path(music).is_file() and not preview:
                raise UserError(f"Musique introuvable : {music}")
            a += ["-i", music]
        a += ["-vf", vf, "-map", "0:v"]
        a += self.venc.args()
        if music:
            a += ["-map", "1:a", "-c:a", "libopus" if ext == "webm" else "aac", "-b:a", d["abitrate"]]
            if d["shortest"]:
                a += ["-shortest"]
        else:
            a += ["-an"]
        if ext in ("mp4", "mov"):
            a += ["-movflags", "+faststart"]
        a += self.extra_args()
        a.append(str(out))
        job = Job(title=f"{len(files)} images", operation=f"Images → {ext.upper()}", args=a, outputs=[out],
                  temp_content={lst: "\n".join(lines) + "\n"}, duration=per * len(files))
        return [job]

    def warnings(self):
        return self.venc.warnings(self.container.currentData())
