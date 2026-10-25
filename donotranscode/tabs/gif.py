from __future__ import annotations

from ..core import Job
from ..ffmpeg import VIDEO_EXT, num
from ..settings_form import check, combo, dspin, form_group, spin
from ..widgets import TimeEdit
from .base import BaseTab
from .common import SCALERS

DITHERS = [("sierra2_4a", "Sierra (recommandé)"), ("floyd_steinberg", "Floyd-Steinberg"),
           ("bayer", "Bayer (trame régulière, plus léger)"), ("none", "Aucun (aplats)")]


class GifTab(BaseTab):
    tab_id = "gif"
    title = "GIF"
    extensions = VIDEO_EXT
    files_title = "Vidéos"
    files_hint = "Glisse des vidéos ici pour en faire des GIF"
    BUILTINS = {
        "GIF léger — 480 px, 12 ips": {"format": "gif", "width": 480, "fps": 12, "colors": 128,
                                       "dither": "bayer", "bayer_scale": 3},
        "GIF qualité — 720 px, 20 ips": {"format": "gif", "width": 720, "fps": 20, "colors": 256,
                                         "dither": "sierra2_4a"},
        "WebP animé — 720 px": {"format": "webp", "width": 720, "fps": 24, "webp_q": 80},
    }

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Passage de la vidéo")
        self.start = b.add("start", TimeEdit("vide = depuis le début"))
        self.dur = b.add("duration", dspin(0, 3600, 5, 2, " s", 0.5, special="jusqu'à la fin"))
        f.addRow("Début", self.start)
        f.addRow("Durée", self.dur)
        layout.addWidget(g)

        g, f = form_group("Animation")
        self.f = f
        self.fmt = b.add("format", combo([("gif", "GIF"), ("webp", "WebP animé (plus léger, plus de couleurs)")]))
        self.fps = b.add("fps", spin(1, 60, 15, " ips"))
        self.width = b.add("width", spin(0, 3840, 480, " px", special="originale"))
        self.algo = b.add("algo", combo(SCALERS, "lanczos"))
        self.loop = b.add("loop", combo([("0", "En boucle"), ("once", "Une seule fois")]))
        self.speed = b.add("speed", dspin(0.25, 4, 1, 2, "×", 0.25))
        f.addRow("Format", self.fmt)
        f.addRow("Images / seconde", self.fps)
        f.addRow("Largeur", self.width)
        f.addRow("Algorithme", self.algo)
        f.addRow("Lecture", self.loop)
        f.addRow("Vitesse", self.speed)
        layout.addWidget(g)

        g, f = form_group("Palette GIF")
        self.g_gif = g
        self.fg = f
        self.colors = b.add("colors", spin(2, 256, 256, " couleurs"))
        self.stats = b.add("stats_mode", combo([("diff", "Optimisée pour ce qui bouge"), ("full", "Globale")]))
        self.dither = b.add("dither", combo(DITHERS))
        self.bayer = b.add("bayer_scale", spin(0, 5, 2))
        f.addRow("Couleurs", self.colors)
        f.addRow("Palette", self.stats)
        f.addRow("Tramage", self.dither)
        f.addRow("Taille de trame Bayer", self.bayer)
        layout.addWidget(g)

        g, f = form_group("WebP animé")
        self.g_webp = g
        self.webp_q = b.add("webp_q", spin(0, 100, 75))
        self.webp_lossless = b.add("webp_lossless", check("Sans perte"))
        f.addRow("Qualité", self.webp_q)
        f.addRow("", self.webp_lossless)
        layout.addWidget(g)

        self.fmt.currentIndexChanged.connect(self._update_rows)
        self.dither.currentIndexChanged.connect(self._update_rows)
        self.width.valueChanged.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        gif = self.fmt.currentData() == "gif"
        self.g_gif.setVisible(gif)
        self.g_webp.setVisible(not gif)
        self.fg.setRowVisible(self.bayer, self.dither.currentData() == "bayer")
        self.f.setRowVisible(self.algo, self.width.value() > 0)

    def make_job(self, src, root, preview):
        d = self.binder.get()
        start = self.start.seconds("Début")
        ext = d["format"]
        out = self.out_file(src, root, src.stem, ext, preview)
        if out is None:
            return None
        a = []
        if start is not None:
            a += ["-ss", num(start)]
        if d["duration"]:
            a += ["-t", num(d["duration"])]
        a += ["-i", str(src)]
        chain = []
        if d["speed"] != 1:
            chain.append(f"setpts=PTS/{d['speed']:g}")
        chain.append(f"fps={d['fps']}")
        if d["width"]:
            chain.append(f"scale={d['width']}:-1:flags={d['algo']}")
        base = ",".join(chain)
        if ext == "gif":
            dither = d["dither"] + (f":bayer_scale={d['bayer_scale']}" if d["dither"] == "bayer" else "")
            diff = ":diff_mode=rectangle" if d["stats_mode"] == "diff" else ""
            graph = (f"{base},split[a][b];[a]palettegen=max_colors={d['colors']}:stats_mode={d['stats_mode']}[p];"
                     f"[b][p]paletteuse=dither={dither}{diff}")
            a += ["-vf", graph, "-loop", "0" if d["loop"] == "0" else "-1"]
        else:
            a += ["-vf", base, "-c:v", "libwebp_anim", "-lossless", "1" if d["webp_lossless"] else "0",
                  "-quality", str(d["webp_q"]), "-loop", "0" if d["loop"] == "0" else "1"]
        a += ["-an"]
        a += self.extra_args()
        a.append(str(out))
        end = (start or 0) + d["duration"] if d["duration"] else None
        job = Job(title=src.name, operation=f"Vidéo → {ext.upper()}", args=a, outputs=[out],
                  probe_path=src, clip=(start, end))
        if d["speed"] != 1:
            job.probe_path = None
            job.duration = (d["duration"] or 0) / d["speed"]
        return job

    def warnings(self):
        w = []
        if self.fmt.currentData() == "gif" and (self.width.value() == 0 or self.width.value() > 800) \
                and (self.dur.value() == 0 or self.dur.value() > 10):
            w.append("Un GIF large et long peut peser des dizaines de Mo : réduis la largeur, la durée ou les ips.")
        return w
