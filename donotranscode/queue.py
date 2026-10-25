"""File d'attente : exécute les tâches ffmpeg une par une, avec progression, pause et annulation."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QProcess, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QHBoxLayout, QHeaderView, QLabel,
                               QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .core import ACTIVE, CANCELLED, DONE, ERROR, PAUSED, RUNNING, WAITING, Job
from .ffmpeg import FFMPEG, cmdline, fmt_short, media_info

BASE_ARGS = ["-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats"]

STATUS_COLORS = {
    RUNNING: "#5aa2ff", PAUSED: "#ffb648", DONE: "#55c27a", ERROR: "#ff6b6b", CANCELLED: "#a0a4ab",
}


def _suspend(pid: int, resume: bool) -> bool:
    """Met en pause / reprend un processus (Windows : NtSuspendProcess)."""
    if sys.platform != "win32":
        import signal
        os.kill(pid, signal.SIGCONT if resume else signal.SIGSTOP)
        return True
    import ctypes
    from ctypes import wintypes
    k32, ntdll = ctypes.windll.kernel32, ctypes.windll.ntdll
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    fn = ntdll.NtResumeProcess if resume else ntdll.NtSuspendProcess
    fn.argtypes = [wintypes.HANDLE]
    h = k32.OpenProcess(0x0800, False, pid)  # PROCESS_SUSPEND_RESUME
    if not h:
        return False
    try:
        return fn(h) == 0
    finally:
        k32.CloseHandle(h)


def reveal_in_explorer(path: Path):
    path = Path(path)
    if sys.platform == "win32":
        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        elif path.is_dir():
            os.startfile(str(path))
        elif path.parent.is_dir():
            os.startfile(str(path.parent))


class QueueWidget(QWidget):
    all_done = Signal(int, int)       # réussis, erreurs
    changed = Signal()

    COLS = ["Fichier", "Opération", "Statut", "Progression", "Temps", "Sortie"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.jobs: list[Job] = []
        self.bars: list[QProgressBar] = []
        self.proc: QProcess | None = None
        self.current: Job | None = None
        self.running = False
        self._cancel_current = False
        self._buf = b""
        self._ok = self._err = 0

        v = QVBoxLayout(self)
        v.setContentsMargins(6, 0, 6, 6)
        bar = QHBoxLayout()
        title = QLabel("File d'attente")
        f = title.font()
        f.setBold(True)
        title.setFont(f)
        bar.addWidget(title)
        self.btn_start = QPushButton("▶  Démarrer")
        self.btn_start.setObjectName("primary")
        self.btn_pause = QPushButton("⏸  Pause")
        self.btn_cancel = QPushButton("✕  Annuler la sélection")
        self.btn_stop = QPushButton("■  Tout arrêter")
        self.btn_retry = QPushButton("↻  Relancer")
        self.btn_remove = QPushButton("Retirer")
        self.btn_clear = QPushButton("Vider les terminés")
        self.btn_open = QPushButton("📂  Ouvrir la sortie")
        for b in (self.btn_start, self.btn_pause, self.btn_cancel, self.btn_stop, self.btn_retry,
                  self.btn_remove, self.btn_clear, self.btn_open):
            bar.addWidget(b)
        bar.addStretch(1)
        self.chk_auto = QCheckBox("Démarrer automatiquement")
        self.chk_auto.setChecked(True)
        self.chk_log = QCheckBox("Journal")
        self.summary = QLabel("")
        self.summary.setObjectName("hint")
        bar.addWidget(self.summary)
        bar.addWidget(self.chk_auto)
        bar.addWidget(self.chk_log)
        v.addLayout(bar)

        self.split = QSplitter(Qt.Horizontal)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels(self.COLS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        h = self.table.horizontalHeader()
        for i, w in enumerate((260, 170, 90, 160, 110)):
            self.table.setColumnWidth(i, w)
        h.setSectionResizeMode(5, QHeaderView.Stretch)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setFont(QFont("Consolas", 9))
        self.log.setPlaceholderText("Sélectionne une tâche pour voir la sortie de ffmpeg.")
        self.log.setVisible(False)
        self.split.addWidget(self.table)
        self.split.addWidget(self.log)
        self.split.setSizes([800, 400])
        v.addWidget(self.split, 1)

        self.btn_start.clicked.connect(self.start)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_cancel.clicked.connect(self.cancel_selected)
        self.btn_stop.clicked.connect(self.stop_all)
        self.btn_retry.clicked.connect(self.retry_selected)
        self.btn_remove.clicked.connect(self.remove_selected)
        self.btn_clear.clicked.connect(self.clear_finished)
        self.btn_open.clicked.connect(self.open_selected)
        self.chk_log.toggled.connect(self.log.setVisible)
        self.table.itemSelectionChanged.connect(self._on_selection)
        self.table.cellDoubleClicked.connect(lambda *_: self.open_selected())

        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self._update_buttons()

    # ---------- ajout / affichage ----------

    def add_jobs(self, jobs: list[Job]):
        for job in jobs:
            self.jobs.append(job)
            row = self.table.rowCount()
            self.table.insertRow(row)
            for col in range(len(self.COLS)):
                if col != 3:
                    self.table.setItem(row, col, QTableWidgetItem())
            pb = QProgressBar()
            pb.setRange(0, 1000)
            self.bars.append(pb)
            self.table.setCellWidget(row, 3, pb)
            self._refresh(job)
        self._update_buttons()

    def reserved(self) -> set[str]:
        return {os.path.normcase(str(p)) for j in self.jobs if j.status in ACTIVE for p in j.all_paths()}

    def is_busy(self) -> bool:
        return self.proc is not None

    def pending_count(self) -> int:
        return sum(j.status in ACTIVE for j in self.jobs)

    def _row(self, job: Job) -> int:
        try:
            return self.jobs.index(job)
        except ValueError:
            return -1

    def _refresh(self, job: Job):
        row = self._row(job)
        if row < 0:
            return
        out = job.reveal or (job.outputs[0] if job.outputs else None)
        texts = [job.title, job.operation, job.status, None, self._time_text(job),
                 str(out) if out else ""]
        for col, text in enumerate(texts):
            if text is None:
                continue
            item = self.table.item(row, col)
            item.setText(text)
            if col == 0:
                item.setToolTip(job.title)
            if col == 2:
                item.setForeground(QColor(STATUS_COLORS.get(job.status, "#e2e4e8")))
                item.setToolTip(job.error or job.status)
            if col == 5:
                item.setToolTip(text)
        pb = self.bars[row]
        pb.setValue(int(job.progress * 1000))
        pb.setFormat(f"{job.progress * 100:.1f} %" + (f"  ×{job.speed}" if job.speed and job.status == RUNNING else ""))

    def _active_time(self, job: Job) -> float:
        now = time.monotonic()
        paused = job.paused_total + ((now - job.paused_at) if job.status == PAUSED else 0)
        return now - job.started - paused

    def _time_text(self, job: Job) -> str:
        if job.status in (RUNNING, PAUSED):
            t = self._active_time(job)
            if job.progress > 0.01:
                return f"reste ~{fmt_short(t * (1 - job.progress) / job.progress)}"
            return fmt_short(t)
        if job.status == DONE:
            return f"en {fmt_short(job.elapsed)}"
        return ""

    def _tick(self):
        if self.current:
            self._refresh(self.current)
        self._update_summary()

    def _update_summary(self):
        n = {s: 0 for s in (WAITING, DONE, ERROR)}
        for j in self.jobs:
            if j.status in n:
                n[j.status] += 1
        parts = []
        if n[WAITING]:
            parts.append(f"{n[WAITING]} en attente")
        if n[DONE]:
            parts.append(f"{n[DONE]} terminée(s)")
        if n[ERROR]:
            parts.append(f"{n[ERROR]} erreur(s)")
        self.summary.setText("  ·  ".join(parts))

    def _update_buttons(self):
        has_waiting = any(j.status == WAITING for j in self.jobs)
        self.btn_start.setEnabled(has_waiting and not self.running)
        self.btn_pause.setEnabled(self.current is not None)
        self.btn_pause.setText("▶  Reprendre" if self.current and self.current.status == PAUSED else "⏸  Pause")
        self.btn_stop.setEnabled(self.running or self.current is not None)
        self._update_summary()
        self.changed.emit()

    def selected_jobs(self) -> list[Job]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.jobs[r] for r in rows if r < len(self.jobs)]

    def _on_selection(self):
        sel = self.selected_jobs()
        self.log.setPlainText("\n".join(sel[0].log) if sel else "")
        self.log.moveCursor(self.log.textCursor().MoveOperation.End)

    # ---------- exécution ----------

    def start(self):
        if not any(j.status == WAITING for j in self.jobs):
            return
        if not self.running:
            self._ok = self._err = 0
        self.running = True
        self._next()

    def _next(self):
        if self.proc is not None:
            return
        job = next((j for j in self.jobs if j.status == WAITING), None) if self.running else None
        if job is None:
            was_running = self.running
            self.running = False
            self._update_buttons()
            if was_running:
                self.all_done.emit(self._ok, self._err)
            return
        try:
            for d in job.mkdirs:
                d.mkdir(parents=True, exist_ok=True)
            for o in job.outputs:
                o.parent.mkdir(parents=True, exist_ok=True)
            for p, text in job.temp_content.items():
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
        except OSError as e:
            job.status, job.error = ERROR, f"Impossible de préparer la sortie : {e}"
            job.log.append(job.error)
            self._err += 1
            self._refresh(job)
            QTimer.singleShot(0, self._next)
            return
        if job.duration <= 0 and job.probe_path:
            info = media_info(job.probe_path)
            if info and info.duration:
                s, e = job.clip or (None, None)
                job.duration = max((e if e is not None else info.duration) - (s or 0), 0)

        self.current, self._buf, self._cancel_current = job, b"", False
        job.log = ["$ " + cmdline(["ffmpeg", *BASE_ARGS, *job.args]), ""]
        job.status, job.progress, job.error, job.speed = RUNNING, 0.0, "", ""
        job.started, job.paused_total = time.monotonic(), 0.0
        p = QProcess(self)
        p.setProgram(FFMPEG)
        p.setArguments(BASE_ARGS + job.args)
        p.readyReadStandardOutput.connect(self._on_stdout)
        p.readyReadStandardError.connect(self._on_stderr)
        p.finished.connect(lambda code, status: self._finish(code == 0 and status == QProcess.NormalExit))
        p.errorOccurred.connect(self._on_proc_error)
        self.proc = p
        self._refresh(job)
        self._update_buttons()
        if self.selected_jobs()[:1] == [job]:
            self._on_selection()
        p.start()

    def _on_proc_error(self, err):
        if err == QProcess.FailedToStart and self.current:
            self.current.error = f"Impossible de lancer ffmpeg ({FFMPEG})"
            self.current.log.append(self.current.error)
            self._finish(False)

    def _on_stdout(self):
        job, proc = self.current, self.proc
        if not job or not proc:
            return
        self._buf += bytes(proc.readAllStandardOutput())
        *lines, self._buf = self._buf.split(b"\n")
        for raw in lines:
            key, _, val = raw.decode("utf-8", "ignore").strip().partition("=")
            if key == "out_time_us" and job.duration > 0:
                try:
                    job.progress = min(max(int(val) / 1e6 / job.duration, 0.0), 0.999)
                except ValueError:
                    pass
            elif key == "speed":
                job.speed = val.strip().rstrip("x") if val.strip() not in ("N/A", "") else ""
            elif key == "progress" and val == "end":
                job.progress = 1.0
        self._refresh(job)

    def _on_stderr(self):
        job, proc = self.current, self.proc
        if not job or not proc:
            return
        text = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
        lines = [ln for ln in text.replace("\r", "\n").split("\n") if ln.strip()]
        job.log.extend(lines)
        if len(job.log) > 4000:
            del job.log[2:len(job.log) - 3000]
        if self.selected_jobs()[:1] == [job]:
            for ln in lines:
                self.log.appendPlainText(ln)

    def _finish(self, ok: bool):
        job, proc = self.current, self.proc
        if job is None or proc is None:
            return
        self._on_stderr()
        job.elapsed = self._active_time(job)
        if self._cancel_current:
            job.status = CANCELLED
            self._delete_outputs(job)
        elif ok and job.mkdirs and not job.outputs and not any(d.is_dir() and any(d.iterdir()) for d in job.mkdirs):
            job.status, job.error = ERROR, "Terminé, mais aucun fichier produit (aucune image ne correspond aux réglages)."
            job.log.append(job.error)
            self._err += 1
        elif ok:
            job.status, job.progress = DONE, 1.0
            self._ok += 1
        else:
            job.status = ERROR
            if not job.error:
                useful = [ln for ln in job.log[2:] if ln.strip()]
                job.error = useful[-1] if useful else f"ffmpeg a échoué (code {proc.exitCode()})"
            self._err += 1
            self._delete_outputs(job)
        for p in job.temp_content:
            try:
                p.unlink()
            except OSError:
                pass
        self.current, self.proc = None, None
        proc.deleteLater()
        self._refresh(job)
        self._update_buttons()
        QTimer.singleShot(0, self._next)

    @staticmethod
    def _delete_outputs(job: Job):
        for o in job.outputs:
            try:
                if o.is_file():
                    o.unlink()
            except OSError:
                pass

    # ---------- actions ----------

    def toggle_pause(self):
        job, proc = self.current, self.proc
        if not job or not proc:
            return
        pid = proc.processId()
        if job.status == RUNNING and _suspend(pid, resume=False):
            job.status, job.paused_at = PAUSED, time.monotonic()
        elif job.status == PAUSED and _suspend(pid, resume=True):
            job.paused_total += time.monotonic() - job.paused_at
            job.status = RUNNING
        self._refresh(job)
        self._update_buttons()

    def _kill_current(self):
        if self.proc and self.current:
            self._cancel_current = True
            if self.current.status == PAUSED:
                _suspend(self.proc.processId(), resume=True)
            self.proc.kill()

    def cancel_selected(self):
        for job in self.selected_jobs():
            if job is self.current:
                self._kill_current()
            elif job.status == WAITING:
                job.status = CANCELLED
                self._refresh(job)
        self._update_buttons()

    def stop_all(self):
        self.running = False
        self._kill_current()
        self._update_buttons()

    def retry_selected(self):
        for job in self.selected_jobs():
            if job.status in (ERROR, CANCELLED):
                job.status, job.progress, job.error, job.duration = WAITING, 0.0, "", 0.0 if job.probe_path else job.duration
                self._refresh(job)
        self._update_buttons()
        if self.chk_auto.isChecked():
            self.start()

    def _remove(self, jobs):
        for job in jobs:
            if job is self.current:
                continue
            row = self._row(job)
            if row >= 0:
                self.table.removeRow(row)
                del self.jobs[row]
                del self.bars[row]
        self._update_buttons()

    def remove_selected(self):
        self._remove(self.selected_jobs())

    def clear_finished(self):
        self._remove([j for j in self.jobs if j.status in (DONE, CANCELLED)])

    def open_selected(self):
        sel = self.selected_jobs() or [j for j in reversed(self.jobs) if j.status == DONE][:1]
        if sel:
            job = sel[0]
            target = job.reveal or (job.outputs[0] if job.outputs else None)
            if target:
                reveal_in_explorer(target)

    def shutdown(self):
        self.running = False
        self._kill_current()
        if self.proc:
            self.proc.waitForFinished(3000)
