from __future__ import annotations
from .i18n import tr
from . import i18n

import sys
import subprocess
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QTimer, QTranslator
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from .explorer import normalize_inputs
from .instance import InstanceBroker
from . import DISPLAY_VERSION


QT_LOCALES = {"ja": (QLocale.Language.Japanese, QLocale.Country.Japan),
              "zh_CN": (QLocale.Language.Chinese, QLocale.Country.China)}


def install_translations(app):
    """Show Qt's own texts (standard buttons, file and colour dialogs) in the interface language.

    English needs no translation. Returns the translator, or None when there is none.
    """
    locale = QT_LOCALES.get(i18n.language())
    if locale is None:
        return None
    translator = QTranslator(app)
    folder = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
    if not translator.load(QLocale(*locale), "qtbase", "_", folder):
        return None
    app.installTranslator(translator)
    return translator


def choose_language():
    """The language saved in the settings; Japanese until one is chosen."""
    from .preferences import Preferences
    try:
        saved = i18n.saved_language(Preferences())
    except (OSError, ValueError):
        saved = None
    return saved or i18n.DEFAULT


def window_class():
    """Imported after the language is set: some texts are made when the interface modules load."""
    from .workspace_tabs import WorkspaceWindow
    return WorkspaceWindow


def configure(app):
    """Set up the application after the language is chosen; the self-test uses the same steps.

    Returns Qt's translator (or None) and the bundled font families that loaded.
    """
    translator = install_translations(app)
    from .theme import install_fonts
    families = install_fonts()
    app.setApplicationName("Sumīre")
    app.setOrganizationName("Sumīre")
    app.setApplicationVersion(DISPLAY_VERSION)
    app.setStyle("Fusion")
    # A code-drawn icon keeps the entire distribution self-contained.
    icon = QPixmap(64, 64)
    icon.fill(QColor("#25362e"))
    painter = QPainter(icon)
    for x, y, color in [(14, 14, "#a8dfc2"), (34, 14, "#7da78f"), (14, 34, "#648873"), (34, 34, "#a8dfc2")]:
        painter.fillRect(x, y, 16, 16, QColor(color))
    painter.end()
    app.setWindowIcon(QIcon(icon))
    return translator, families


def unregister():
    """``sumire.exe --unregister``: remove 「Sumīreで開く」 from the right-click menu.

    For uninstalling: run it (or unregister-context-menu.cmd) before deleting the folder.
    """
    from PySide6.QtWidgets import QMessageBox
    from .explorer import configure_context_menu
    app = QApplication.instance() or QApplication(sys.argv[:1])
    i18n.set_language(choose_language())
    configure(app)
    title = tr("右クリックの登録を解除")
    try:
        configure_context_menu(remove=True)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        QMessageBox.warning(None, title, tr("解除できませんでした。\n{error}").format(error=error))
        return 1
    QMessageBox.information(None, title, tr("右クリックの「Sumīreで開く」を解除しました。\nこのフォルダーを削除しても、登録は残りません。"))
    return 0


def main():
    if sys.argv[1:2] == ["--unregister"]:
        return unregister()
    if sys.argv[1:2] in (["--self-test"], ["--self-test-ui"]):
        # Checks a built copy without a visible window; see selftest.py.
        from .selftest import main as self_test
        return self_test(sys.argv[1:])
    app = QApplication(sys.argv)
    i18n.set_language(choose_language())
    configure(app)
    arguments = sys.argv[1:]
    if arguments[:1] == ["--open"]:
        arguments = arguments[1:]
    inputs = []
    if arguments:
        try:
            inputs = [str(Path(path).resolve()) for path in normalize_inputs(arguments)]
        except (OSError, ValueError, subprocess.CalledProcessError):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(None, tr("画像を開けません"), tr("Windowsのパスを変換できません。WSLとの接続を確認してください。"))
            return 1
    broker = InstanceBroker()
    state = broker.start_or_forward(inputs)
    if state == "forwarded":
        return 0
    if state != "primary":
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, tr("Sumīreを起動できません"), tr("起動中のSumīreへ接続できませんでした。少し待ってから開き直してください。"))
        return 1
    window = window_class()()
    broker.requested.connect(getattr(window, "receive_external", window.open_inputs))
    window.show()

    def start():
        # Ask for the save method before anything can be saved on a new profile.
        window.first_run_setup()
        window.open_inputs(inputs) if inputs else window.resume_session()

    QTimer.singleShot(0, start)
    try:
        return app.exec()
    finally:
        broker.close()


if __name__ == "__main__":
    raise SystemExit(main())
