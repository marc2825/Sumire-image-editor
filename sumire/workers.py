"""Small Qt thread-pool adapter; error strings cannot disclose image metadata."""
from __future__ import annotations
from .i18n import tr

import threading
from collections.abc import Callable

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

from .export import Cancelled
from .imaging import ImageProblem


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()
    progress = Signal(int, int)


class Job(QRunnable):
    def __init__(self, function: Callable, *, progress=False):
        super().__init__()
        self.signals = Signals()
        self.function = function
        self.cancel = threading.Event()
        self.report_progress = progress

    @Slot()
    def run(self):
        try:
            result = self.function(self.cancel, self.signals.progress.emit) if self.report_progress else self.function(self.cancel)
            self.signals.done.emit(result)
        except Cancelled:
            self.signals.cancelled.emit()
        except ImageProblem as error:
            self.signals.failed.emit(str(error))
        except Exception:
            self.signals.failed.emit(tr("処理できませんでした。空き容量・アクセス権・画像形式を確認してください。"))
        finally:
            self.signals.finished.emit()

