from __future__ import annotations

from ..core import Job, UserError
from ..ffmpeg import VIDEO_EXT, num
from ..settings_form import check, combo, dspin, form_group, spin
from ..widgets import TimeEdit
from .base import BaseTab
from .common import (CONTAINERS, ROT_FILTER, ROTATIONS, SCALERS, AudioEncoderBox, VideoEncoderBox)

RESOLUTIONS = [("0", "Originale"), ("2160", "2160p (4K)"), ("1440", "1440p"), ("1080", "1080p (Full HD)"),
               ("720", "720p"), ("576", "576p"), ("480", "480p"), ("360", "360p"), ("custom", "Personnalisée")]
FPS = [("0", "Originale"), ("23.976", "23,976"), ("24", "24"), ("25", "25"), ("29.97", "29,97"), ("30", "30"),
       ("50", "50"), ("59.94", "59,94"), ("60", "60"), ("custom", "Personnalisée")]
SUB_CODEC = {"mkv": "copy", "mp4": "mov_text", "mov": "mov_text", "webm": "webvtt"}


class VideoTab(BaseTab):
    tab_id = "video"
    title = "Vidéo"
    extensions = VIDEO_EXT
    files_title = "Vidéos à convertir"
    files_hint = "Glisse des vidéos ou des dossiers ici\n(AVI, MKV, MOV, MP4, WMV, FLV…)"
    BUILTINS = {
        "MP4 H.264 — bonne qualité (processeur)": {
            "container": "mp4", "venc.encoder": "libx264", "venc.crf": 20, "venc.preset": "slow",
            "aenc.codec": "aac", "aenc.bitrate": "192k"},
        "MP4 H.264 — rapide (carte graphique)": {
            "container": "mp4", "venc.encoder": "h264_nvenc", "venc.crf": 23, "venc.preset": "p5",
            "aenc.codec": "aac", "aenc.bitrate": "192k"},
        "MKV H.265 — petit fichier (carte graphique)": {
            "container": "mkv", "venc.encoder": "hevc_nvenc", "venc.crf": 28, "venc.preset": "p6",
            "aenc.codec": "libopus", "aenc.bitrate": "128k", "all_audio": True, "subs": True},
        "MKV H.265 10 bits — archivage (processeur)": {
            "container": "mkv", "venc.encoder": "libx265", "venc.crf": 22, "venc.preset": "slow",
            "venc.pix_fmt": "yuv420p10le", "aenc.codec": "copy", "all_audio": True, "subs": True},
        "MP4 720p — partage (Discord…)": {
            "container": "mp4", "venc.encoder": "h264_nvenc", "venc.crf": 28, "resolution": "720",
            "aenc.codec": "aac", "aenc.bitrate": "128k"},
        "WebM VP9 — web": {
            "container": "webm", "venc.encoder": "libvpx-vp9", "venc.crf": 32, "aenc.codec": "libopus",
            "aenc.bitrate": "128k"},
        "Changer de conteneur → MKV (sans réencoder)": {
            "container": "mkv", "venc.encoder": "copy", "aenc.codec": "copy", "all_audio": True, "subs": True},
        "Changer de conteneur → MP4 (sans réencoder)": {
            "container": "mp4", "venc.encoder": "copy", "aenc.codec": "copy"},
    }

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Format de sortie")
        self.container = b.add("container", combo(CONTAINERS, "mp4"))
        f.addRow("Conteneur", self.container)
        layout.addWidget(g)

        self.venc = VideoEncoderBox(b)
        layout.addWidget(self.venc)

        g, f = form_group("Image")
        self.f_img = f
        self.res = b.add("resolution", combo(RESOLUTIONS, "0"))
        self.cw = b.add("custom_w", spin(0, 16384, 1920, " px", special="auto"))
        self.ch = b.add("custom_h", spin(0, 16384, 1080, " px", special="auto"))
        self.no_up = b.add("no_upscale", check("Ne jamais agrandir une vidéo plus petite", True))
        self.scaler = b.add("scaler", combo(SCALERS, "lanczos"))
        self.fps = b.add("fps", combo(FPS, "0"))
        self.fps_custom = b.add("fps_custom", dspin(1, 240, 30, 3, " ips", 1))
        self.deint = b.add("deinterlace", check("Désentrelacer (vieilles vidéos TV / DV)"))
        self.rot = b.add("rotation", combo(ROTATIONS, "none"))
        f.addRow("Résolution (hauteur)", self.res)
        f.addRow("Largeur", self.cw)
        f.addRow("Hauteur", self.ch)
        f.addRow("", self.no_up)
        f.addRow("Algorithme", self.scaler)
        f.addRow("Images / seconde", self.fps)
        f.addRow("Valeur", self.fps_custom)
        f.addRow("Rotation", self.rot)
        f.addRow("", self.deint)
        layout.addWidget(g)
        self.img_group = g

        self.aenc = AudioEncoderBox(b)
        layout.addWidget(self.aenc)

        g, f = form_group("Pistes, découpe et options")
        self.all_audio = b.add("all_audio", check("Garder toutes les pistes audio (sinon la principale)"))
        self.subs = b.add("subs", check("Garder les sous-titres"))
        self.faststart = b.add("faststart", check("Lecture web rapide (faststart, MP4/MOV)", True))
        self.strip = b.add("strip_meta", check("Supprimer les métadonnées"))
        self.start = b.add("start", TimeEdit("vide = depuis le début"))
        self.end = b.add("end", TimeEdit("vide = jusqu'à la fin"))
        f.addRow("", self.all_audio)
        f.addRow("", self.subs)
        f.addRow("", self.faststart)
        f.addRow("", self.strip)
        f.addRow("Début", self.start)
        f.addRow("Fin", self.end)
        layout.addWidget(g)

        for w in (self.res, self.fps):
            w.currentIndexChanged.connect(self._update_rows)
        self.venc.encoder.currentIndexChanged.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        f = self.f_img
        custom = self.res.currentData() == "custom"
        f.setRowVisible(self.cw, custom)
        f.setRowVisible(self.ch, custom)
        f.setRowVisible(self.no_up, self.res.currentData() not in ("0", "custom"))
        f.setRowVisible(self.fps_custom, self.fps.currentData() == "custom")
        self.img_group.setEnabled(not self.venc.is_copy())

    def video_filters(self, d) -> list[str]:
        vf = []
        if d["deinterlace"]:
            vf.append("yadif")
        if d["rotation"] != "none":
            vf.append(ROT_FILTER[d["rotation"]])
        algo = d["scaler"]
        res = d["resolution"]
        if res == "custom":
            w, h = d["custom_w"], d["custom_h"]
            if w or h:
                vf.append(f"scale={w or -2}:{h or -2}:flags={algo}")
        elif res != "0":
            h = f"min({res}\\,ih)" if d["no_upscale"] else res
            vf.append(f"scale=-2:{h}:flags={algo}")
        fps = d["fps"]
        if fps == "custom":
            vf.append(f"fps={num(d['fps_custom'])}")
        elif fps != "0":
            vf.append(f"fps={fps}")
        return vf

    def make_job(self, src, root, preview):
        d = self.binder.get()
        ext = d["container"]
        start = self.start.seconds("Début")
        end = self.end.seconds("Fin")
        if start is not None and end is not None and end <= start:
            raise UserError("La fin doit être après le début.")
        out = self.out_file(src, root, src.stem, ext, preview)
        if out is None:
            return None
        a = []
        if start is not None:
            a += ["-ss", num(start)]
        if end is not None:
            a += ["-to", num(end)]
        a += ["-i", str(src)]
        if d["all_audio"] or d["subs"]:
            a += ["-map", "0:v:0", "-map", "0:a?" if d["all_audio"] else "0:a:0?"]
            if d["subs"] and ext != "avi":
                a += ["-map", "0:s?"]
        if not self.venc.is_copy():
            vf = self.video_filters(d)
            if vf:
                a += ["-vf", ",".join(vf)]
        a += self.venc.args()
        a += self.aenc.args()
        if d["subs"] and ext != "avi":
            a += ["-c:s", SUB_CODEC.get(ext, "copy")]
        if ext in ("mp4", "mov") and d["faststart"]:
            a += ["-movflags", "+faststart"]
        if d["strip_meta"]:
            a += ["-map_metadata", "-1"]
        a += self.extra_args()
        a.append(str(out))
        op = f"Vidéo → {ext.upper()}" + (" (copie)" if self.venc.is_copy() else "")
        return Job(title=src.name, operation=op, args=a, outputs=[out], probe_path=src, clip=(start, end))

    def warnings(self):
        ext = self.container.currentData()
        w = self.venc.warnings(ext) + self.aenc.warnings(ext)
        if self.venc.is_copy() and (self.start.text() or self.end.text()):
            w.append("En copie, la découpe se cale sur les images clés (début approximatif).")
        if self.subs.isChecked() and ext in ("mp4", "mov", "webm"):
            w.append("Les sous-titres image (PGS, VobSub) ne passent qu'en MKV.")
        return w
