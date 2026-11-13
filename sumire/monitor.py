"""Directory notifications with bounded, asynchronous discovery and a fallback scan."""
import os
from time import monotonic

from PySide6.QtCore import QFileSystemWatcher, QObject, QThreadPool, Signal

from .export import check_cancel
from .imaging import SUPPORTED
from .workers import Job


class FolderMonitor(QObject):
    discovered = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(self.changed)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.folders = set()
        self.candidates = {}
        self.generation = 0
        self.serial = 0
        self.dirty = False
        self.last_scan = 0
        self.job = None
        self.jobs = set()
        self.closed = False

    def changed(self, *_):
        self.serial += 1
        self.dirty = True

    def set_scope(self, folders):
        folders = set(folders)
        if folders == self.folders:
            return
        self.generation += 1
        self.folders = folders
        self.candidates.clear()
        for job in self.jobs:
            job.cancel.set()
        registered = set(self.watcher.directories())
        removed = registered - {str(folder) for folder in folders}
        added = {str(folder) for folder in folders} - registered
        if removed:
            self.watcher.removePaths(list(removed))
        if added:
            self.watcher.addPaths(list(added))
        self.changed()

    @staticmethod
    def scan(folders, known, cancel):
        found = {}
        for folder in folders:
            check_cancel(cancel)
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        check_cancel(cancel)
                        path = folder / entry.name
                        if path.suffix.lower() not in SUPPORTED or path in known:
                            continue
                        if not entry.is_file():
                            continue
                        if entry.is_symlink():
                            path = path.resolve()
                            if path in known:
                                continue
                        stat = entry.stat()
                        found[path] = stat.st_size, stat.st_mtime_ns
            except OSError:
                continue
        return found

    def poll(self, known):
        if self.closed or self.job is not None or not self.folders:
            return
        if not self.dirty and monotonic() - self.last_scan < 30:
            return
        generation, serial = self.generation, self.serial
        folders, known = set(self.folders), set(known)
        previous = dict(self.candidates)
        job = Job(lambda cancel: self.scan(folders, known, cancel))
        self.job = job
        self.jobs.add(job)

        def done(found):
            if self.closed or generation != self.generation:
                return
            stable = [path for path, value in found.items() if value[0] and previous.get(path) == value]
            self.candidates = found
            self.dirty = bool(found) or self.serial != serial
            self.last_scan = monotonic()
            if stable:
                self.discovered.emit(stable)

        def finished():
            self.jobs.discard(job)
            if self.job is job:
                self.job = None

        job.signals.done.connect(done)
        job.signals.finished.connect(finished)
        self.pool.start(job)

    def close(self):
        self.closed = True
        self.generation += 1
        for job in self.jobs:
            job.cancel.set()
        self.pool.waitForDone()
