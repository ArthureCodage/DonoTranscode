"""Accès à ffmpeg / ffprobe et petits outils autour (temps, tailles, infos)."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


def app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _find_tool(name: str) -> str:
    bases = [app_root() / "bin"]
    if hasattr(sys, "_MEIPASS"):
        bases.append(Path(sys._MEIPASS) / "bin")
    for base in bases:
        exe = base / f"{name}.exe"
        if exe.exists():
            return str(exe)
    return shutil.which(name) or name


FFMPEG = _find_tool("ffmpeg")
FFPROBE = _find_tool("ffprobe")
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

VIDEO_EXT = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".m4v", ".mpg", ".mpeg",
             ".ts", ".m2ts", ".mts", ".3gp", ".ogv", ".vob", ".gif"}
AUDIO_EXT = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".aif",
             ".mka", ".ac3", ".alac", ".amr"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".jfif", ".webp", ".bmp", ".tif", ".tiff", ".tga", ".gif"}
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT | IMAGE_EXT


def run(args: list[str], timeout: float = 60) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, timeout=timeout, stdin=subprocess.DEVNULL,
                          creationflags=CREATE_NO_WINDOW)


def ffmpeg_version() -> str:
    try:
        out = run([FFMPEG, "-version"], timeout=10).stdout.decode("utf-8", "replace")
        m = re.search(r"ffmpeg version (\S+)", out)
        return m.group(1).split("-")[0] if m else "?"
    except Exception:
        return "introuvable"


@dataclass
class MediaInfo:
    path: Path
    size: int = 0
    duration: float = 0.0
    format_name: str = ""
    bitrate: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    vcodec: str = ""
    pix_fmt: str = ""
    acodec: str = ""
    sample_rate: int = 0
    channels: int = 0
    audio_tracks: int = 0
    subtitle_tracks: int = 0
    is_image: bool = False

    @property
    def has_video(self) -> bool:
        return bool(self.vcodec)

    @property
    def has_audio(self) -> bool:
        return self.audio_tracks > 0


def _rate(text: str) -> float:
    try:
        if "/" in text:
            n, d = text.split("/")
            return float(n) / float(d) if float(d) else 0.0
        return float(text)
    except (ValueError, ZeroDivisionError):
        return 0.0


_cache: dict[tuple, MediaInfo] = {}


def media_info(path: Path | str) -> MediaInfo | None:
    """Lit les infos d'un fichier avec ffprobe (résultat mis en cache)."""
    path = Path(path)
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_mtime_ns, st.st_size)
    if key in _cache:
        return _cache[key]
    try:
        r = run([FFPROBE, "-v", "error", "-print_format", "json",
                 "-show_format", "-show_streams", str(path)], timeout=30)
    except Exception:
        return None
    if r.returncode != 0:
        return None
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError:
        return None
    fmt = data.get("format", {})
    info = MediaInfo(path=path, size=st.st_size)
    info.format_name = fmt.get("format_long_name") or fmt.get("format_name", "")
    info.duration = float(fmt.get("duration") or 0)
    info.bitrate = int(float(fmt.get("bit_rate") or 0))
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind == "video" and not info.vcodec and not s.get("disposition", {}).get("attached_pic"):
            info.vcodec = s.get("codec_name", "")
            info.width = int(s.get("width") or 0)
            info.height = int(s.get("height") or 0)
            info.pix_fmt = s.get("pix_fmt", "")
            info.fps = _rate(s.get("avg_frame_rate") or "") or _rate(s.get("r_frame_rate") or "")
            if not info.duration:
                info.duration = float(s.get("duration") or 0)
        elif kind == "audio":
            info.audio_tracks += 1
            if not info.acodec:
                info.acodec = s.get("codec_name", "")
                info.sample_rate = int(s.get("sample_rate") or 0)
                info.channels = int(s.get("channels") or 0)
        elif kind == "subtitle":
            info.subtitle_tracks += 1
    fname = fmt.get("format_name", "")
    info.is_image = (path.suffix.lower() in IMAGE_EXT and path.suffix.lower() != ".gif") \
        or fname == "image2" or fname.endswith("_pipe")
    _cache[key] = info
    return info


def thumbnail(path: Path, info: MediaInfo | None, width: int = 480) -> bytes:
    """Renvoie une miniature PNG (octets) ou b'' si impossible."""
    args = [FFMPEG, "-v", "error"]
    if info and not info.is_image and info.duration > 2:
        args += ["-ss", f"{info.duration * 0.1:.2f}"]
    args += ["-i", str(path), "-frames:v", "1", "-vf", f"scale='min({width},iw)':-2",
             "-f", "image2pipe", "-c:v", "png", "-"]
    try:
        r = run(args, timeout=30)
        return r.stdout if r.returncode == 0 else b""
    except Exception:
        return b""


# ---------- outils ----------

def parse_time(text: str) -> float | None:
    """'90', '1:30', '00:01:30.5' -> secondes. Vide -> None. Invalide -> ValueError."""
    text = (text or "").strip().replace(",", ".")
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError(text)
    total = 0.0
    for p in parts:
        total = total * 60 + float(p)
    if total < 0:
        raise ValueError(text)
    return total


def fmt_time(sec: float, ms: bool = True) -> str:
    sec = max(sec, 0.0)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h:02d}:{m:02d}:{s:06.3f}" if ms else f"{h:02d}:{m:02d}:{int(s):02d}"


def fmt_short(sec: float) -> str:
    sec = int(max(sec, 0))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(n: float) -> str:
    for unit in ("o", "Ko", "Mo", "Go"):
        if n < 1024 or unit == "Go":
            return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} To"


def num(x: float) -> str:
    """Nombre lisible pour ffmpeg (sans zéros inutiles)."""
    return f"{x:.3f}".rstrip("0").rstrip(".")


def cmdline(args: list[str]) -> str:
    return subprocess.list2cmdline(args)


def natural_key(p) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(p).lower())]


def concat_escape(path: Path) -> str:
    """Chemin pour un fichier de liste du démuxeur concat."""
    return str(path).replace("\\", "/").replace("'", "'\\''")


def safe_name(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip().rstrip(".")
    return name or "sortie"
