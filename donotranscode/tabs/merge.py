from __future__ import annotations

from ..core import Job, UserError, temp_list_path
from ..ffmpeg import VIDEO_EXT, concat_escape, media_info, num
from ..settings_form import combo, form_group, line, spin
from .base import BaseTab
from .common import CONTAINERS, AudioEncoderBox, VideoEncoderBox

RES = [("first", "Comme la 1re vidéo"), ("3840x2160", "3840×2160 (4K)"), ("1920x1080", "1920×1080"),
       ("1280x720", "1280×720"), ("1080x1920", "1080×1920 (vertical)"), ("custom", "Personnalisée")]
FPS = [("first", "Comme la 1re vidéo"), ("24", "24"), ("25", "25"), ("30", "30"), ("50", "50"), ("60", "60")]


class MergeTab(BaseTab):
    tab_id = "merge"
    title = "Fusionner"
    extensions = VIDEO_EXT
    reorder = True
    files_title = "Vidéos (dans l'ordre)"
    files_hint = "Glisse les vidéos à mettre bout à bout\n(glisse les lignes pour changer l'ordre)"
    BUILTINS = {
        "Rapide — vidéos identiques (même caméra / même source)": {"mode": "fast"},
        "Réencoder en MP4 1080p — carte graphique": {
            "mode": "reencode", "container": "mp4", "resolution": "1920x1080", "fps": "30",
            "venc.encoder": "h264_nvenc", "venc.crf": 21, "aenc.codec": "aac"},
    }

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Sortie")
        self.f = f
        self.name = b.add("name", line("fusion"))
        self.mode = b.add("mode", combo([("fast", "Rapide — sans réencoder (vidéos de même format)"),
                                         ("reencode", "Réencoder — vidéos différentes (taille, codec, fps)")]))
        self.container = b.add("container", combo([("same", "Comme la 1re vidéo")] + CONTAINERS, "same"))
        self.res = b.add("resolution", combo(RES, "first"))
        self.cw = b.add("w", spin(16, 16384, 1920, " px"))
        self.ch = b.add("h", spin(16, 16384, 1080, " px"))
        self.fps = b.add("fps", combo(FPS, "first"))
        f.addRow("Nom du fichier", self.name)
        f.addRow("Mode", self.mode)
        f.addRow("Conteneur", self.container)
        f.addRow("Résolution", self.res)
        f.addRow("Largeur", self.cw)
        f.addRow("Hauteur", self.ch)
        f.addRow("Images / seconde", self.fps)
        layout.addWidget(g)
        self.venc = VideoEncoderBox(b, allow_copy=False, default="h264_nvenc", default_pix="yuv420p")
        self.aenc = AudioEncoderBox(b, allow_copy=False, default="aac")
        layout.addWidget(self.venc)
        layout.addWidget(self.aenc)
        self.mode.currentIndexChanged.connect(self._update_rows)
        self.res.currentIndexChanged.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        re = self.mode.currentData() == "reencode"
        custom = self.res.currentData() == "custom"
        for w in (self.res, self.fps):
            self.f.setRowVisible(w, re)
        self.f.setRowVisible(self.cw, re and custom)
        self.f.setRowVisible(self.ch, re and custom)
        self.venc.setVisible(re)
        self.aenc.setVisible(re)

    def build_jobs(self, preview=False):
        self.skipped = 0
        files = [p for p, _ in self.items()]
        if len(files) < 2:
            raise UserError("Ajoute au moins deux vidéos.")
        d = self.binder.get()
        cont = d["container"]
        ext = files[0].suffix.lower().lstrip(".") if cont == "same" else cont
        out = self.out_file(None, None, d["name"] or "fusion", ext, preview)
        if out is None:
            self.skipped = 1
            return []
        extra = self.extra_args()
        infos = [media_info(p) for p in files]
        total = sum(i.duration for i in infos if i)

        if d["mode"] == "fast":
            lst = temp_list_path()
            text = "\n".join(f"file '{concat_escape(p)}'" for p in files) + "\n"
            a = ["-f", "concat", "-safe", "0", "-i", str(lst), "-map", "0:v?", "-map", "0:a?", "-c", "copy"]
            if ext in ("mp4", "mov"):
                a += ["-movflags", "+faststart"]
            a += extra + [str(out)]
            return [Job(title=f"{len(files)} vidéos", operation="Fusion (copie)", args=a, outputs=[out],
                        duration=total, temp_content={lst: text})]

        first = infos[0]
        if not first or not first.width:
            raise UserError(f"Impossible de lire {files[0].name}")
        if d["resolution"] == "first":
            W, H = first.width, first.height
        elif d["resolution"] == "custom":
            W, H = d["w"], d["h"]
        else:
            W, H = (int(x) for x in d["resolution"].split("x"))
        W, H = W // 2 * 2, H // 2 * 2
        fps = num(first.fps or 30) if d["fps"] == "first" else d["fps"]
        use_audio = self.aenc.codec_name() != "none"
        a, parts, labels = [], [], ""
        for p in files:
            a += ["-i", str(p)]
        extra_inputs = len(files)
        for i, (p, info) in enumerate(zip(files, infos)):
            if info is None:
                raise UserError(f"Impossible de lire {p.name}")
            parts.append(f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=decrease,"
                         f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p[v{i}]")
            labels += f"[v{i}]"
            if use_audio:
                if info.has_audio:
                    src_a = f"[{i}:a:0]"
                else:  # silence pour les vidéos sans son
                    a += ["-f", "lavfi", "-t", num(info.duration or 1), "-i", "anullsrc=r=48000:cl=stereo"]
                    src_a = f"[{extra_inputs}:a]"
                    extra_inputs += 1
                parts.append(f"{src_a}aresample=48000,aformat=channel_layouts=stereo[a{i}]")
                labels += f"[a{i}]"
        parts.append(f"{labels}concat=n={len(files)}:v=1:a={1 if use_audio else 0}[v]" + ("[a]" if use_audio else ""))
        a += ["-filter_complex", ";".join(parts), "-map", "[v]"]
        if use_audio:
            a += ["-map", "[a]"]
        a += self.venc.args() + self.aenc.args()
        if ext in ("mp4", "mov"):
            a += ["-movflags", "+faststart"]
        a += extra + [str(out)]
        return [Job(title=f"{len(files)} vidéos", operation="Fusion (réencodage)", args=a, outputs=[out],
                    duration=total)]

    def warnings(self):
        files = [p for p, _ in self.items()]
        w = []
        if self.mode.currentData() == "fast" and len(files) >= 2:
            infos = [media_info(p) for p in files[:30]]
            sig = {(i.vcodec, i.width, i.height, i.acodec) for i in infos if i}
            if len(sig) > 1:
                w.append("Les vidéos n'ont pas toutes le même format (codec / taille / audio) : "
                         "choisis « Réencoder » pour éviter une vidéo cassée.")
        if self.mode.currentData() == "reencode":
            cont = self.container.currentData()
            w += self.venc.warnings(None if cont == "same" else cont)
        return w
