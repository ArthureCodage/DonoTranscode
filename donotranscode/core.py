from __future__ import annotations

import shlex
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

WAITING = "En attente"
RUNNING = "En cours"
PAUSED = "En pause"
DONE = "Terminé"
ERROR = "Erreur"
CANCELLED = "Annulé"
ACTIVE = (WAITING, RUNNING, PAUSED)


class UserError(Exception):
    """Erreur à montrer telle quelle à l'utilisateur."""


@dataclass(eq=False)
class Job:
    title: str
    operation: str
    args: list[str]
    outputs: list[Path] = field(default_factory=list)   # fichiers produits
    reveal: Path | None = None                          # quoi montrer dans l'Explorateur
    mkdirs: list[Path] = field(default_factory=list)    # dossiers à créer avant
    temp_content: dict = field(default_factory=dict)    # Path -> texte écrit avant, supprimé après
    duration: float = 0.0                               # pour la progression
    probe_path: Path | None = None                      # sinon durée lue ici au lancement
    clip: tuple | None = None                           # (début, fin) appliqués à probe_path
    status: str = WAITING
    progress: float = 0.0
    speed: str = ""
    log: list[str] = field(default_factory=list)
    error: str = ""
    started: float = 0.0
    paused_at: float = 0.0
    paused_total: float = 0.0
    elapsed: float = 0.0

    def all_paths(self) -> list[Path]:
        return [*self.outputs, *self.mkdirs]


def temp_list_path() -> Path:
    return Path(tempfile.gettempdir()) / "DonoTranscode" / f"liste_{uuid.uuid4().hex[:10]}.txt"


def parse_extra(text: str) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    try:
        parts = shlex.split(text, posix=False)
    except ValueError as e:
        raise UserError(f"Arguments en plus invalides : {e}")
    return [p[1:-1] if len(p) >= 2 and p[0] == p[-1] == '"' else p for p in parts]
