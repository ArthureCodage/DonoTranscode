from __future__ import annotations

from ..core import Job
from ..ffmpeg import IMAGE_EXT
from ..settings_form import check, combo, dspin, form_group, spin
from .base import BaseTab
from .common import ROT_FILTER, ROTATIONS, SCALERS

FORMATS = [("same", "Même format que l'original"), ("jpg", "JPG"), ("png", "PNG"), ("webp", "WebP"),
           ("bmp", "BMP"), ("tiff", "TIFF")]
KIND = {".jpg": "jpg", ".jpeg": "jpg", ".jfif": "jpg", ".png": "png", ".webp": "webp", ".bmp": "bmp",
        ".tif": "tiff", ".tiff": "tiff", ".gif": "gif", ".tga": "tga"}
RATIOS = [("1:1", "1:1 (carré)"), ("4:3", "4:3"), ("3:4", "3:4"), ("3:2", "3:2"), ("2:3", "2:3"),
          ("16:9", "16:9"), ("9:16", "9:16"), ("21:9", "21:9"), ("custom", "Personnalisé")]
RESIZE = [("none", "Aucun"), ("width", "Largeur fixe"), ("height", "Hauteur fixe"),
          ("fit", "Tenir dans L×H (ratio conservé)"), ("fill", "Remplir L×H (recadre l'excédent)"),
          ("exact", "Taille exacte L×H (déforme)")]


class ImagesTab(BaseTab):
    tab_id = "images"
    title = "Images"
    extensions = IMAGE_EXT
    files_title = "Images à traiter"
    files_hint = "Glisse des images ou des dossiers ici\n(PNG, JPG, WebP, BMP, TIFF…)"
    BUILTINS = {
        "Dataset LoRA — 1024×1024 PNG (carré centré)": {
            "format": "png", "crop_mode": "ratio", "ratio": "1:1", "resize": "exact", "w": 1024, "h": 1024},
        "Dataset LoRA — 1024 px côté long, PNG": {
            "format": "png", "resize": "fit", "w": 1024, "h": 1024, "no_upscale": False},
        "JPG web — 1920 px max": {
            "format": "jpg", "jpg_q": 3, "resize": "fit", "w": 1920, "h": 1920, "no_upscale": True,
            "strip_meta": True},
        "WebP léger — qualité 80": {"format": "webp", "webp_q": 80},
        "PNG → JPG haute qualité": {"format": "jpg", "jpg_q": 2, "jpg_chroma": "yuvj444p"},
    }

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Format de sortie")
        self.f_fmt = f
        self.fmt = b.add("format", combo(FORMATS, "same"))
        self.jpg_q = b.add("jpg_q", spin(1, 31, 2))
        self.jpg_q.setToolTip("1–2 = excellente qualité, 31 = très compressé")
        self.jpg_chroma = b.add("jpg_chroma", combo([("yuvj420p", "4:2:0 (standard, plus léger)"),
                                                      ("yuvj444p", "4:4:4 (couleurs plus fines)")]))
        self.webp_q = b.add("webp_q", spin(0, 100, 90))
        self.webp_lossless = b.add("webp_lossless", check("Sans perte"))
        self.webp_level = b.add("webp_level", spin(0, 6, 4))
        self.webp_level.setToolTip("Effort de compression : 6 = plus petit mais plus lent")
        self.png_level = b.add("png_level", spin(0, 9, 6))
        self.tiff_comp = b.add("tiff_comp", combo([("deflate", "Deflate"), ("lzw", "LZW"),
                                                    ("packbits", "PackBits"), ("raw", "Aucune")]))
        f.addRow("Format", self.fmt)
        f.addRow("Qualité JPG (1 = meilleure)", self.jpg_q)
        f.addRow("Couleurs JPG", self.jpg_chroma)
        f.addRow("Qualité WebP (0–100)", self.webp_q)
        f.addRow("", self.webp_lossless)
        f.addRow("Effort WebP (0–6)", self.webp_level)
        f.addRow("Compression PNG (0–9)", self.png_level)
        f.addRow("Compression TIFF", self.tiff_comp)
        layout.addWidget(g)

        g, f = form_group("Recadrage (avant redimensionnement)")
        self.f_crop = f
        self.crop_mode = b.add("crop_mode", combo([("none", "Aucun"), ("ratio", "Ratio, centré"),
                                                    ("manual", "Manuel (pixels)")]))
        self.ratio = b.add("ratio", combo(RATIOS, "1:1"))
        self.ratio_w = b.add("ratio_w", spin(1, 100, 5))
        self.ratio_h = b.add("ratio_h", spin(1, 100, 4))
        self.cw = b.add("crop_w", spin(1, 32768, 1000, " px"))
        self.ch = b.add("crop_h", spin(1, 32768, 1000, " px"))
        self.cx = b.add("crop_x", spin(0, 32768, 0, " px"))
        self.cy = b.add("crop_y", spin(0, 32768, 0, " px"))
        self.ccenter = b.add("crop_center", check("Centrer (ignore X et Y)", True))
        f.addRow("Mode", self.crop_mode)
        f.addRow("Ratio", self.ratio)
        f.addRow("Ratio largeur", self.ratio_w)
        f.addRow("Ratio hauteur", self.ratio_h)
        f.addRow("Largeur", self.cw)
        f.addRow("Hauteur", self.ch)
        f.addRow("", self.ccenter)
        f.addRow("X", self.cx)
        f.addRow("Y", self.cy)
        layout.addWidget(g)

        g, f = form_group("Redimensionnement")
        self.f_res = f
        self.resize = b.add("resize", combo(RESIZE, "none"))
        self.w = b.add("w", spin(1, 32768, 1024, " px"))
        self.h = b.add("h", spin(1, 32768, 1024, " px"))
        self.no_up = b.add("no_upscale", check("Ne jamais agrandir une image plus petite"))
        self.algo = b.add("algo", combo(SCALERS, "lanczos"))
        f.addRow("Mode", self.resize)
        f.addRow("Largeur", self.w)
        f.addRow("Hauteur", self.h)
        f.addRow("", self.no_up)
        f.addRow("Algorithme", self.algo)
        layout.addWidget(g)

        g, f = form_group("Orientation et couleurs")
        self.rot = b.add("rotation", combo(ROTATIONS, "none"))
        self.bright = b.add("brightness", dspin(-1, 1, 0, 2, step=0.05))
        self.contrast = b.add("contrast", dspin(0, 3, 1, 2, step=0.05))
        self.sat = b.add("saturation", dspin(0, 3, 1, 2, step=0.05))
        self.gamma = b.add("gamma", dspin(0.1, 10, 1, 2, step=0.05))
        self.gray = b.add("grayscale", check("Noir et blanc"))
        self.strip = b.add("strip_meta", check("Supprimer les métadonnées (EXIF…)"))
        f.addRow("Rotation", self.rot)
        f.addRow("Luminosité (0 = normal)", self.bright)
        f.addRow("Contraste (1 = normal)", self.contrast)
        f.addRow("Saturation (1 = normal)", self.sat)
        f.addRow("Gamma (1 = normal)", self.gamma)
        f.addRow("", self.gray)
        f.addRow("", self.strip)
        layout.addWidget(g)

        for w in (self.fmt, self.crop_mode, self.ratio, self.resize):
            w.currentIndexChanged.connect(self._update_rows)
        self.ccenter.toggled.connect(self._update_rows)
        self.webp_lossless.toggled.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        fmt = self.fmt.currentData()
        show = lambda k: fmt in (k, "same")
        f = self.f_fmt
        f.setRowVisible(self.jpg_q, show("jpg"))
        f.setRowVisible(self.jpg_chroma, show("jpg"))
        f.setRowVisible(self.webp_q, show("webp") and not self.webp_lossless.isChecked())
        f.setRowVisible(self.webp_lossless, show("webp"))
        f.setRowVisible(self.webp_level, show("webp"))
        f.setRowVisible(self.png_level, show("png"))
        f.setRowVisible(self.tiff_comp, show("tiff"))
        cm = self.crop_mode.currentData()
        f = self.f_crop
        f.setRowVisible(self.ratio, cm == "ratio")
        custom = cm == "ratio" and self.ratio.currentData() == "custom"
        f.setRowVisible(self.ratio_w, custom)
        f.setRowVisible(self.ratio_h, custom)
        for w in (self.cw, self.ch, self.ccenter):
            f.setRowVisible(w, cm == "manual")
        for w in (self.cx, self.cy):
            f.setRowVisible(w, cm == "manual" and not self.ccenter.isChecked())
        rm = self.resize.currentData()
        f = self.f_res
        f.setRowVisible(self.w, rm in ("width", "fit", "fill", "exact"))
        f.setRowVisible(self.h, rm in ("height", "fit", "fill", "exact"))
        f.setRowVisible(self.no_up, rm in ("width", "height", "fit"))
        f.setRowVisible(self.algo, rm != "none")

    def filters(self, d) -> list[str]:
        vf = []
        cm = d["crop_mode"]
        if cm == "ratio":
            if d["ratio"] == "custom":
                rw, rh = d["ratio_w"], d["ratio_h"]
            else:
                rw, rh = (int(x) for x in d["ratio"].split(":"))
            r = f"{rw}/{rh}"
            vf.append(f"crop=w=min(iw\\,ih*{r}):h=min(ih\\,iw/({r}))")
        elif cm == "manual":
            pos = "" if d["crop_center"] else f":x={d['crop_x']}:y={d['crop_y']}"
            vf.append(f"crop=w=min({d['crop_w']}\\,iw):h=min({d['crop_h']}\\,ih){pos}")
        rm, w, h, algo = d["resize"], d["w"], d["h"], d["algo"]
        W = f"min({w}\\,iw)" if d["no_upscale"] else str(w)
        H = f"min({h}\\,ih)" if d["no_upscale"] else str(h)
        if rm == "width":
            vf.append(f"scale=w={W}:h=-1:flags={algo}")
        elif rm == "height":
            vf.append(f"scale=w=-1:h={H}:flags={algo}")
        elif rm == "fit":
            vf.append(f"scale=w={W}:h={H}:force_original_aspect_ratio=decrease:flags={algo}")
        elif rm == "fill":
            vf.append(f"scale=w={w}:h={h}:force_original_aspect_ratio=increase:flags={algo},crop={w}:{h}")
        elif rm == "exact":
            vf.append(f"scale={w}:{h}:flags={algo}")
        if d["rotation"] != "none":
            vf.append(ROT_FILTER[d["rotation"]])
        eq = []
        if d["brightness"]:
            eq.append(f"brightness={d['brightness']:g}")
        if d["contrast"] != 1:
            eq.append(f"contrast={d['contrast']:g}")
        if d["saturation"] != 1:
            eq.append(f"saturation={d['saturation']:g}")
        if d["gamma"] != 1:
            eq.append(f"gamma={d['gamma']:g}")
        if eq:
            vf.append("eq=" + ":".join(eq))
        if d["grayscale"]:
            vf.append("hue=s=0")
        return vf

    def make_job(self, src, root, preview):
        d = self.binder.get()
        if d["format"] == "same":
            ext = src.suffix.lower().lstrip(".")
            kind = KIND.get(src.suffix.lower(), "png")
        else:
            ext = kind = d["format"]
        out = self.out_file(src, root, src.stem, ext, preview)
        if out is None:
            return None
        a = ["-i", str(src)]
        vf = self.filters(d)
        if vf:
            a += ["-vf", ",".join(vf)]
        if kind == "jpg":
            a += ["-q:v", str(d["jpg_q"]), "-pix_fmt", d["jpg_chroma"]]
        elif kind == "webp":
            a += ["-c:v", "libwebp", "-lossless", "1" if d["webp_lossless"] else "0",
                  "-quality", str(100 if d["webp_lossless"] else d["webp_q"]),
                  "-compression_level", str(d["webp_level"])]
        elif kind == "png":
            a += ["-compression_level", str(d["png_level"])]
        elif kind == "tiff":
            a += ["-compression_algo", d["tiff_comp"]]
        if d["strip_meta"]:
            a += ["-map_metadata", "-1"]
        a += ["-frames:v", "1", "-update", "1"]
        a += self.extra_args()
        a.append(str(out))
        return Job(title=src.name, operation=f"Image → {ext.upper()}", args=a, outputs=[out])

    def warnings(self):
        w = []
        if self.fmt.currentData() == "jpg":
            w.append("Le JPG ne gère pas la transparence : les zones transparentes deviennent unies.")
        return w if self.files and self.files.items() and \
            any(p.suffix.lower() in (".png", ".webp", ".tga", ".gif") for p, _ in self.files.items()[:50]) else []
