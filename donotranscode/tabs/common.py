"""Blocs partagés : encodeur vidéo, encodeur audio, listes de choix communes."""
from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox

from ..settings_form import Binder, combo, dspin, spin

X26X_PRESETS = [(p, p) for p in ("ultrafast", "superfast", "veryfast", "faster", "fast",
                                 "medium", "slow", "slower", "veryslow")]
NV_PRESETS = [("p1", "p1 — le plus rapide"), ("p2", "p2"), ("p3", "p3"), ("p4", "p4"),
              ("p5", "p5 — équilibré"), ("p6", "p6"), ("p7", "p7 — meilleure qualité")]

ENCODERS = {
    "libx264": dict(label="H.264 — x264 (processeur)", crf=(0, 51, 23), presets=X26X_PRESETS, preset="medium",
                    tunes=["film", "animation", "grain", "stillimage", "fastdecode", "zerolatency"]),
    "h264_nvenc": dict(label="H.264 — NVENC (carte graphique)", crf=(0, 51, 23), presets=NV_PRESETS, preset="p5"),
    "libx265": dict(label="H.265 / HEVC — x265 (processeur)", crf=(0, 51, 26), presets=X26X_PRESETS, preset="medium",
                    tunes=["animation", "grain", "fastdecode", "zerolatency", "psnr", "ssim"]),
    "hevc_nvenc": dict(label="H.265 / HEVC — NVENC (carte graphique)", crf=(0, 51, 26), presets=NV_PRESETS, preset="p5"),
    "libsvtav1": dict(label="AV1 — SVT-AV1 (processeur)", crf=(0, 63, 32),
                      presets=[(str(i), f"{i}" + (" — le plus lent" if i == 0 else " — le plus rapide" if i == 13 else ""))
                               for i in range(14)], preset="8"),
    "libvpx-vp9": dict(label="VP9 — libvpx (processeur)", crf=(0, 63, 31),
                       presets=[(str(i), f"cpu-used {i}" + (" — le plus lent" if i == 0 else " — le plus rapide" if i == 5 else ""))
                                for i in range(6)], preset="2"),
    "copy": dict(label="Copier sans réencoder (très rapide)"),
}

CONTAINERS = [("mp4", "MP4"), ("mkv", "MKV"), ("webm", "WebM"), ("mov", "MOV"), ("avi", "AVI")]
SCALERS = [("lanczos", "Lanczos (net)"), ("bicubic", "Bicubique"), ("bilinear", "Bilinéaire (rapide)"),
           ("neighbor", "Plus proche voisin (pixel art)"), ("area", "Area (réduction)")]
ROTATIONS = [("none", "Aucune"), ("cw", "90° sens horaire"), ("ccw", "90° sens anti-horaire"), ("180", "180°"),
             ("hflip", "Miroir horizontal"), ("vflip", "Miroir vertical")]
ROT_FILTER = {"cw": "transpose=1", "ccw": "transpose=2", "180": "hflip,vflip", "hflip": "hflip", "vflip": "vflip"}
SAMPLE_RATES = [("", "Originale"), ("22050", "22 050 Hz"), ("44100", "44 100 Hz"), ("48000", "48 000 Hz"),
                ("96000", "96 000 Hz")]
CHANNELS = [("", "Originaux"), ("1", "Mono"), ("2", "Stéréo"), ("6", "5.1")]
BITRATES = ["64k", "96k", "128k", "160k", "192k", "224k", "256k", "320k"]


def audio_bitrate(text: str, codec: str) -> str:
    """Nettoie le débit saisi ; Opus est limité à 256k par ffmpeg."""
    text = (text or "").strip().lower() or "192k"
    if codec == "libopus":
        try:
            kb = float(text.rstrip("k"))
            if kb > 256:
                return "256k"
        except ValueError:
            pass
    return text


def opus_too_high(text: str) -> bool:
    try:
        return float((text or "").strip().lower().rstrip("k")) > 256
    except ValueError:
        return False


class VideoEncoderBox(QGroupBox):
    def __init__(self, binder: Binder, prefix="venc.", allow_copy=True, title="Encodage vidéo",
                 default="libx264", default_pix="auto"):
        super().__init__(title)
        f = self.f = QFormLayout(self)
        items = [(k, v["label"]) for k, v in ENCODERS.items() if allow_copy or k != "copy"]
        self.encoder = binder.add(prefix + "encoder", combo(items, default))
        self.mode = binder.add(prefix + "mode", combo([("crf", "Qualité constante (CRF / CQ)"),
                                                        ("bitrate", "Débit moyen visé")]))
        self.crf = binder.add(prefix + "crf", spin(0, 51, 23))
        self.crf.setToolTip("Plus le chiffre est bas, meilleure est la qualité (et plus gros est le fichier).")
        self.bitrate = binder.add(prefix + "bitrate", spin(100, 300000, 5000, " kb/s", step=500))
        self.maxrate = binder.add(prefix + "maxrate", spin(0, 300000, 0, " kb/s", step=500, special="aucun"))
        self.preset = binder.add(prefix + "preset", combo([]))
        self.preset.setToolTip("Vitesse d'encodage : plus lent = meilleure compression à qualité égale.")
        self.tune = binder.add(prefix + "tune", combo([("none", "Aucun")]))
        self.pix = binder.add(prefix + "pix_fmt", combo([
            ("auto", "Automatique"), ("yuv420p", "8 bits 4:2:0 (le plus compatible)"),
            ("yuv420p10le", "10 bits 4:2:0"), ("yuv444p", "8 bits 4:4:4")], default_pix))
        self.gop = binder.add(prefix + "gop", spin(0, 1000, 0, " images", special="auto"))
        self.gop.setToolTip("Intervalle entre images clés (0 = automatique).")
        f.addRow("Encodeur", self.encoder)
        f.addRow("Mode", self.mode)
        f.addRow("Qualité (CRF / CQ)", self.crf)
        f.addRow("Débit vidéo", self.bitrate)
        f.addRow("Débit maximum", self.maxrate)
        f.addRow("Preset", self.preset)
        f.addRow("Tune", self.tune)
        f.addRow("Format de pixels", self.pix)
        f.addRow("Image clé tous les", self.gop)
        self.encoder.currentIndexChanged.connect(self._on_encoder)
        self.mode.currentIndexChanged.connect(self._update_rows)
        self._on_encoder()

    def _on_encoder(self, *_):
        spec = ENCODERS[self.encoder.currentData()]
        if "crf" in spec:
            lo, hi, d = spec["crf"]
            self.crf.setRange(lo, hi)
            self.crf.setValue(d)
        for box, items, default in ((self.preset, spec.get("presets", []), spec.get("preset")),
                                    (self.tune, [("none", "Aucun")] + [(t, t) for t in spec.get("tunes", [])], "none")):
            box.blockSignals(True)
            box.clear()
            for data, label in items:
                box.addItem(label, data)
            i = box.findData(default)
            box.setCurrentIndex(max(i, 0))
            box.blockSignals(False)
        self._update_rows()

    def _update_rows(self, *_):
        enc = self.encoder.currentData()
        copy = enc == "copy"
        crf = self.mode.currentData() == "crf"
        f = self.f
        for w in (self.mode, self.preset, self.pix, self.gop):
            f.setRowVisible(w, not copy)
        f.setRowVisible(self.crf, not copy and crf)
        f.setRowVisible(self.bitrate, not copy and not crf)
        f.setRowVisible(self.maxrate, not copy and not crf)
        f.setRowVisible(self.tune, bool(ENCODERS[enc].get("tunes")))

    def is_copy(self) -> bool:
        return self.encoder.currentData() == "copy"

    def is_nvenc(self) -> bool:
        return "nvenc" in self.encoder.currentData()

    def args(self) -> list[str]:
        enc = self.encoder.currentData()
        if enc == "copy":
            return ["-c:v", "copy"]
        nv = "nvenc" in enc
        a = ["-c:v", enc]
        if self.mode.currentData() == "crf":
            q = str(self.crf.value())
            if nv:
                a += ["-rc", "vbr", "-cq", q, "-b:v", "0"]
            elif enc == "libvpx-vp9":
                a += ["-crf", q, "-b:v", "0"]
            else:
                a += ["-crf", q]
        else:
            if nv:
                a += ["-rc", "vbr"]
            a += ["-b:v", f"{self.bitrate.value()}k"]
            if self.maxrate.value():
                a += ["-maxrate", f"{self.maxrate.value()}k", "-bufsize", f"{self.maxrate.value() * 2}k"]
        preset = self.preset.currentData()
        if enc == "libvpx-vp9":
            a += ["-deadline", "good", "-cpu-used", preset, "-row-mt", "1"]
        elif preset:
            a += ["-preset", preset]
        tune = self.tune.currentData()
        if tune and tune != "none":
            a += ["-tune", tune]
        pix = self.pix.currentData()
        if pix != "auto":
            a += ["-pix_fmt", "p010le" if nv and pix == "yuv420p10le" else pix]
        if self.gop.value():
            a += ["-g", str(self.gop.value())]
        if enc == "libx265":
            a += ["-x265-params", "log-level=error"]
        return a

    def warnings(self, container: str | None = None) -> list[str]:
        enc = self.encoder.currentData()
        w = []
        if enc == "h264_nvenc" and self.pix.currentData() in ("yuv420p10le", "yuv444p"):
            w.append("NVENC H.264 sur RTX 2060 ne gère que le 8 bits 4:2:0 : choisis HEVC NVENC pour du 10 bits.")
        if container == "webm" and enc not in ("libvpx-vp9", "libsvtav1", "copy"):
            w.append("WebM n'accepte que VP9 ou AV1 en vidéo.")
        if container == "avi" and enc in ("libsvtav1", "libvpx-vp9", "libx265", "hevc_nvenc"):
            w.append("AVI est peu compatible avec ce codec : préfère MP4 ou MKV.")
        return w


class AudioEncoderBox(QGroupBox):
    CODECS = [("aac", "AAC"), ("libopus", "Opus"), ("libmp3lame", "MP3"), ("flac", "FLAC (sans perte)"),
              ("pcm_s16le", "PCM 16 bits (non compressé)"), ("ac3", "AC-3 (Dolby Digital)"),
              ("copy", "Copier sans réencoder"), ("none", "Pas d'audio")]

    def __init__(self, binder: Binder, prefix="aenc.", allow_copy=True, allow_none=True, title="Audio",
                 default="aac"):
        super().__init__(title)
        f = self.f = QFormLayout(self)
        items = [c for c in self.CODECS if (allow_copy or c[0] != "copy") and (allow_none or c[0] != "none")]
        self.codec = binder.add(prefix + "codec", combo(items, default))
        self.bitrate = binder.add(prefix + "bitrate", combo(BITRATES, "192k", editable=True))
        self.rate = binder.add(prefix + "samplerate", combo(SAMPLE_RATES, ""))
        self.channels = binder.add(prefix + "channels", combo(CHANNELS, ""))
        self.volume = binder.add(prefix + "volume", dspin(-30, 30, 0, 1, " dB", 0.5))
        f.addRow("Codec", self.codec)
        f.addRow("Débit", self.bitrate)
        f.addRow("Fréquence", self.rate)
        f.addRow("Canaux", self.channels)
        f.addRow("Volume", self.volume)
        self.codec.currentIndexChanged.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        c = self.codec.currentData()
        simple = c in ("copy", "none")
        for w in (self.rate, self.channels, self.volume):
            self.f.setRowVisible(w, not simple)
        self.f.setRowVisible(self.bitrate, not simple and c not in ("flac", "pcm_s16le"))

    def codec_name(self) -> str:
        return self.codec.currentData()

    def args(self) -> list[str]:
        c = self.codec.currentData()
        if c == "none":
            return ["-an"]
        if c == "copy":
            return ["-c:a", "copy"]
        a = ["-c:a", c]
        if c not in ("flac", "pcm_s16le"):
            a += ["-b:a", audio_bitrate(self.bitrate.currentText(), c)]
        if self.rate.currentData():
            a += ["-ar", self.rate.currentData()]
        if self.channels.currentData():
            a += ["-ac", self.channels.currentData()]
        if self.volume.value():
            a += ["-af", f"volume={self.volume.value():g}dB"]
        return a

    def warnings(self, container: str | None = None) -> list[str]:
        c = self.codec.currentData()
        w = []
        if container == "webm" and c not in ("libopus", "none", "copy"):
            w.append("WebM n'accepte que Opus (ou Vorbis) en audio.")
        if container == "mp4" and c == "pcm_s16le":
            w.append("MP4 ne gère pas bien le PCM : préfère MKV ou MOV.")
        if c == "libopus" and self.rate.currentData() in ("22050", "44100"):
            w.append("Opus n'accepte pas cette fréquence : laisse « Originale » ou choisis 48 000 Hz.")
        if c == "libopus" and opus_too_high(self.bitrate.currentText()):
            w.append("Opus est limité à 256 kb/s : le débit sera ramené à 256k.")
        return w
