from __future__ import annotations

from ..core import Job, UserError
from ..ffmpeg import VIDEO_EXT, media_info, num, safe_name
from ..settings_form import check, combo, dspin, form_group, line, spin
from ..widgets import TimeEdit
from .base import BaseTab
from .common import SCALERS

MODES = [("all", "Toutes les images"), ("fps", "N images par seconde"),
         ("every", "1 image toutes les N secondes"), ("count", "N images réparties sur la vidéo"),
         ("key", "Seulement les images clés (rapide)"), ("scene", "À chaque changement de scène")]


class ExtractTab(BaseTab):
    tab_id = "extract"
    title = "Extraire images"
    extensions = VIDEO_EXT
    files_title = "Vidéos"
    files_hint = "Glisse des vidéos ici pour en extraire des images"
    BUILTINS = {
        "1 image par seconde, PNG": {"mode": "fps", "value": 1, "format": "png"},
        "Dataset — 50 images réparties, PNG": {"mode": "count", "value": 50, "format": "png"},
        "Changements de scène, JPG": {"mode": "scene", "scene": 0.3, "format": "jpg"},
    }

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Quelles images")
        self.f_mode = f
        self.mode = b.add("mode", combo(MODES, "fps"))
        self.value = b.add("value", dspin(0.01, 100000, 1, 2, step=1))
        self.scene = b.add("scene", dspin(0.05, 0.95, 0.3, 2, step=0.05))
        self.scene.setToolTip("Sensibilité : plus bas = plus d'images détectées")
        self.start = b.add("start", TimeEdit("vide = depuis le début"))
        self.end = b.add("end", TimeEdit("vide = jusqu'à la fin"))
        f.addRow("Mode", self.mode)
        self.value_label = "Valeur"
        f.addRow("Valeur", self.value)
        f.addRow("Seuil de scène", self.scene)
        f.addRow("Début", self.start)
        f.addRow("Fin", self.end)
        layout.addWidget(g)

        g, f = form_group("Format des images")
        self.f_fmt = f
        self.fmt = b.add("format", combo([("png", "PNG (sans perte)"), ("jpg", "JPG"), ("webp", "WebP")], "png"))
        self.jpg_q = b.add("jpg_q", spin(1, 31, 2))
        self.webp_q = b.add("webp_q", spin(0, 100, 90))
        self.width = b.add("width", spin(0, 16384, 0, " px", special="originale"))
        self.algo = b.add("algo", combo(SCALERS, "lanczos"))
        f.addRow("Format", self.fmt)
        f.addRow("Qualité JPG (1 = meilleure)", self.jpg_q)
        f.addRow("Qualité WebP", self.webp_q)
        f.addRow("Largeur", self.width)
        f.addRow("Algorithme", self.algo)
        layout.addWidget(g)

        g, f = form_group("Nommage")
        self.subdir = b.add("subdir", check("Un sous-dossier par vidéo (« nom_images »)", True))
        self.prefix = b.add("prefix", line("{nom}_", "{nom} = nom de la vidéo"))
        self.digits = b.add("digits", spin(1, 9, 5))
        self.start_num = b.add("start_number", spin(0, 1000000, 1))
        f.addRow("", self.subdir)
        f.addRow("Préfixe", self.prefix)
        f.addRow("Chiffres du numéro", self.digits)
        f.addRow("Premier numéro", self.start_num)
        layout.addWidget(g)

        self.mode.currentIndexChanged.connect(self._update_rows)
        self.fmt.currentIndexChanged.connect(self._update_rows)
        self.width.valueChanged.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        m = self.mode.currentData()
        self.f_mode.setRowVisible(self.value, m in ("fps", "every", "count"))
        label = {"fps": "Images par seconde", "every": "Toutes les (secondes)", "count": "Nombre d'images"}.get(m, "Valeur")
        lbl = self.f_mode.labelForField(self.value)
        if lbl:
            lbl.setText(label)
        self.f_mode.setRowVisible(self.scene, m == "scene")
        fmt = self.fmt.currentData()
        self.f_fmt.setRowVisible(self.jpg_q, fmt == "jpg")
        self.f_fmt.setRowVisible(self.webp_q, fmt == "webp")
        self.f_fmt.setRowVisible(self.algo, self.width.value() > 0)

    def make_job(self, src, root, preview):
        d = self.binder.get()
        start = self.start.seconds("Début")
        end = self.end.seconds("Fin")
        if start is not None and end is not None and end <= start:
            raise UserError("La fin doit être après le début.")
        ext = d["format"]
        prefix = safe_name(d["prefix"].replace("{nom}", src.stem)) if d["prefix"] else ""
        prefix = prefix.replace("%", "%%")
        if d["subdir"]:
            folder = self.out_dir(src, root, f"{src.stem}_images", preview)
            if folder is None:
                return None
        else:
            folder = self.ctx.base_dir(src, root, preview)
        a = []
        if start is not None:
            a += ["-ss", num(start)]
        if end is not None:
            a += ["-to", num(end)]
        m = d["mode"]
        if m == "key":
            a += ["-skip_frame", "nokey"]
        a += ["-i", str(src)]
        vf = []
        v = d["value"]
        if m == "fps":
            vf.append(f"fps={num(v)}")
        elif m == "every":
            vf.append(f"fps=1/{num(v)}")
        elif m == "count":
            info = media_info(src)
            if not info or not info.duration:
                raise UserError(f"Durée inconnue pour {src.name}")
            dur = (end if end is not None else info.duration) - (start or 0)
            vf.append(f"fps={num(v / max(dur, 0.001))}")
        elif m == "scene":
            vf.append(f"select=gt(scene\\,{d['scene']:g})")
        if d["width"]:
            vf.append(f"scale={d['width']}:-1:flags={d['algo']}")
        if vf:
            a += ["-vf", ",".join(vf)]
        if m in ("key", "scene", "all"):
            a += ["-fps_mode", "vfr" if m != "all" else "passthrough"]
        if ext == "jpg":
            a += ["-q:v", str(d["jpg_q"])]
        elif ext == "webp":
            a += ["-c:v", "libwebp", "-quality", str(d["webp_q"])]
        a += ["-start_number", str(d["start_number"])]
        a += self.extra_args()
        a.append(str(folder / f"{prefix}%0{d['digits']}d.{ext}"))
        return Job(title=src.name, operation=f"Extraire images ({ext.upper()})", args=a,
                   mkdirs=[folder] if d["subdir"] else [], reveal=folder, probe_path=src, clip=(start, end))

    def warnings(self):
        w = []
        if not self.subdir.isChecked() and "{nom}" not in self.prefix.text():
            w.append("Sans sous-dossier ni {nom} dans le préfixe, les images de plusieurs vidéos s'écraseront.")
        if self.mode.currentData() == "all":
            w.append("« Toutes les images » peut produire des milliers de fichiers (25 à 60 par seconde de vidéo).")
        return w
