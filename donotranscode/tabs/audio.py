from __future__ import annotations

from ..core import Job, UserError
from ..ffmpeg import AUDIO_EXT, VIDEO_EXT, media_info, num
from ..settings_form import check, combo, dspin, form_group, spin
from ..widgets import TimeEdit
from .base import BaseTab
from .common import BITRATES, CHANNELS, SAMPLE_RATES, audio_bitrate, opus_too_high

FORMATS = [("mp3", "MP3"), ("m4a", "M4A (AAC)"), ("opus", "Opus"), ("ogg", "OGG (Opus)"),
           ("flac", "FLAC (sans perte)"), ("wav", "WAV (non compressé)"),
           ("mka", "MKA — copie de la piste, sans réencoder")]
CODEC = {"mp3": "libmp3lame", "m4a": "aac", "opus": "libopus", "ogg": "libopus", "flac": "flac"}


class AudioTab(BaseTab):
    tab_id = "audio"
    title = "Audio"
    extensions = VIDEO_EXT | AUDIO_EXT
    files_title = "Vidéos ou fichiers audio"
    files_hint = "Glisse des vidéos (pour en extraire le son)\nou des fichiers audio à convertir"
    BUILTINS = {
        "MP3 320 kb/s": {"format": "mp3", "mp3_mode": "cbr", "bitrate": "320k"},
        "MP3 VBR V0 (excellent, plus léger)": {"format": "mp3", "mp3_mode": "vbr", "vbr_q": 0},
        "WAV 48 kHz 16 bits": {"format": "wav", "wav_depth": "pcm_s16le", "samplerate": "48000"},
        "FLAC sans perte": {"format": "flac", "flac_level": 8},
        "Opus 128 kb/s": {"format": "opus", "bitrate": "128k"},
        "Normaliser le volume (MP3 320)": {"format": "mp3", "bitrate": "320k", "loudnorm": True},
    }

    def build_form(self, layout):
        b = self.binder
        g, f = form_group("Format")
        self.f = f
        self.fmt = b.add("format", combo(FORMATS, "mp3"))
        self.mp3_mode = b.add("mp3_mode", combo([("cbr", "Débit constant (CBR)"), ("vbr", "Débit variable (VBR)")]))
        self.bitrate = b.add("bitrate", combo(BITRATES, "320k", editable=True))
        self.vbr_q = b.add("vbr_q", spin(0, 9, 2))
        self.vbr_q.setToolTip("0 = meilleure qualité (~245 kb/s), 9 = la plus faible")
        self.wav = b.add("wav_depth", combo([("pcm_s16le", "16 bits"), ("pcm_s24le", "24 bits"),
                                             ("pcm_f32le", "32 bits flottant")]))
        self.flac = b.add("flac_level", spin(0, 12, 5))
        self.rate = b.add("samplerate", combo(SAMPLE_RATES, ""))
        self.channels = b.add("channels", combo(CHANNELS, ""))
        f.addRow("Format", self.fmt)
        f.addRow("Mode MP3", self.mp3_mode)
        f.addRow("Débit", self.bitrate)
        f.addRow("Qualité VBR (0 = meilleure)", self.vbr_q)
        f.addRow("Profondeur", self.wav)
        f.addRow("Compression FLAC (0–12)", self.flac)
        f.addRow("Fréquence", self.rate)
        f.addRow("Canaux", self.channels)
        layout.addWidget(g)

        g, f = form_group("Son")
        self.g_fx = g
        self.volume = b.add("volume", dspin(-30, 30, 0, 1, " dB", 0.5))
        self.loudnorm = b.add("loudnorm", check("Normaliser le volume (EBU R128)"))
        self.target = b.add("lufs", dspin(-40, -5, -16, 1, " LUFS", 1))
        self.target.setToolTip("-16 : musique / podcast · -23 : télévision · -14 : Spotify / YouTube")
        self.fade_in = b.add("fade_in", dspin(0, 60, 0, 1, " s", 0.5, special="aucun"))
        self.fade_out = b.add("fade_out", dspin(0, 60, 0, 1, " s", 0.5, special="aucun"))
        f.addRow("Volume", self.volume)
        f.addRow("", self.loudnorm)
        f.addRow("Niveau visé", self.target)
        f.addRow("Fondu d'entrée", self.fade_in)
        f.addRow("Fondu de sortie", self.fade_out)
        layout.addWidget(g)
        self.f_fx = f

        g, f = form_group("Source")
        self.track = b.add("track", spin(1, 32, 1))
        self.track.setToolTip("Pour les vidéos avec plusieurs langues : 1 = première piste audio")
        self.start = b.add("start", TimeEdit("vide = depuis le début"))
        self.end = b.add("end", TimeEdit("vide = jusqu'à la fin"))
        self.strip = b.add("strip_meta", check("Supprimer les métadonnées"))
        f.addRow("Piste audio n°", self.track)
        f.addRow("Début", self.start)
        f.addRow("Fin", self.end)
        f.addRow("", self.strip)
        layout.addWidget(g)

        for w in (self.fmt, self.mp3_mode):
            w.currentIndexChanged.connect(self._update_rows)
        self.loudnorm.toggled.connect(self._update_rows)
        self._update_rows()

    def _update_rows(self, *_):
        fmt = self.fmt.currentData()
        f = self.f
        mp3 = fmt == "mp3"
        vbr = mp3 and self.mp3_mode.currentData() == "vbr"
        f.setRowVisible(self.mp3_mode, mp3)
        f.setRowVisible(self.bitrate, fmt in ("mp3", "m4a", "opus", "ogg") and not vbr)
        f.setRowVisible(self.vbr_q, vbr)
        f.setRowVisible(self.wav, fmt == "wav")
        f.setRowVisible(self.flac, fmt == "flac")
        f.setRowVisible(self.rate, fmt != "mka")
        f.setRowVisible(self.channels, fmt != "mka")
        self.g_fx.setEnabled(fmt != "mka")
        self.f_fx.setRowVisible(self.target, self.loudnorm.isChecked())

    def make_job(self, src, root, preview):
        d = self.binder.get()
        fmt = d["format"]
        start = self.start.seconds("Début")
        end = self.end.seconds("Fin")
        if start is not None and end is not None and end <= start:
            raise UserError("La fin doit être après le début.")
        out = self.out_file(src, root, src.stem, fmt, preview)
        if out is None:
            return None
        a = []
        if start is not None:
            a += ["-ss", num(start)]
        if end is not None:
            a += ["-to", num(end)]
        a += ["-i", str(src), "-map", f"0:a:{d['track'] - 1}"]
        if fmt == "mka":
            a += ["-c:a", "copy"]
        else:
            if fmt == "wav":
                a += ["-c:a", d["wav_depth"]]
            else:
                a += ["-c:a", CODEC[fmt]]
            if fmt == "mp3" and d["mp3_mode"] == "vbr":
                a += ["-q:a", str(d["vbr_q"])]
            elif fmt in ("mp3", "m4a", "opus", "ogg"):
                a += ["-b:a", audio_bitrate(self.bitrate.currentText(), CODEC[fmt])]
            if fmt == "flac":
                a += ["-compression_level", str(d["flac_level"])]
            if d["samplerate"]:
                a += ["-ar", d["samplerate"]]
            if d["channels"]:
                a += ["-ac", d["channels"]]
            af = []
            if d["volume"]:
                af.append(f"volume={d['volume']:g}dB")
            if d["loudnorm"]:
                af.append(f"loudnorm=I={d['lufs']:g}:TP=-1.5:LRA=11")
            if d["fade_in"]:
                af.append(f"afade=t=in:st=0:d={d['fade_in']:g}")
            if d["fade_out"]:
                info = media_info(src)
                if not info or not info.duration:
                    raise UserError(f"Durée inconnue pour {src.name} (fondu de sortie impossible)")
                dur = (end if end is not None else info.duration) - (start or 0)
                af.append(f"afade=t=out:st={num(max(dur - d['fade_out'], 0))}:d={d['fade_out']:g}")
            if af:
                a += ["-af", ",".join(af)]
            if d["loudnorm"] and not d["samplerate"]:
                a += ["-ar", "48000"]
        if d["strip_meta"]:
            a += ["-map_metadata", "-1"]
        a += self.extra_args()
        a.append(str(out))
        return Job(title=src.name, operation=f"Audio → {fmt.upper()}", args=a, outputs=[out],
                   probe_path=src, clip=(start, end))

    def warnings(self):
        w = []
        if self.fmt.currentData() in ("opus", "ogg") and self.rate.currentData() in ("22050", "44100"):
            w.append("Opus n'accepte pas cette fréquence : laisse « Originale » ou choisis 48 000 Hz.")
        if self.fmt.currentData() in ("opus", "ogg") and opus_too_high(self.bitrate.currentText()):
            w.append("Opus est limité à 256 kb/s : le débit sera ramené à 256k.")
        return w
