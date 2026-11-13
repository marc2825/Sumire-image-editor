import json
import os
from pathlib import Path
import subprocess
import sys
import time

import pytest


SERVER = r'''
import json, sys
from pathlib import Path
from PySide6.QtCore import QCoreApplication, QTimer
from sumire.instance import InstanceBroker
app = QCoreApplication([])
broker = InstanceBroker()
if broker.start_or_forward([]) != 'primary':
    sys.exit(77)
folder = Path(sys.argv[1])
def received(paths):
    (folder / 'received.json').write_text(json.dumps(paths), encoding='utf-8')
    QTimer.singleShot(150, app.quit)
broker.requested.connect(received)
(folder / 'ready').write_text('ready')
QTimer.singleShot(10000, app.quit)
app.exec()
broker.close()
'''
CLIENT = r'''
import sys
from PySide6.QtCore import QCoreApplication
from sumire.instance import InstanceBroker
app = QCoreApplication([])
broker = InstanceBroker()
print(broker.start_or_forward(sys.argv[1:]))
'''


@pytest.mark.parametrize("crash", [False, True])
def test_second_process_forwards_unicode_paths_and_recovers_stale_lock(tmp_path, crash):
    server = subprocess.Popen([sys.executable, "-c", SERVER, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 5
        while not (tmp_path / "ready").exists() and server.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        if server.poll() == 77:
            pytest.skip("Local sockets unavailable in this execution sandbox")
        assert (tmp_path / "ready").exists(), server.stderr.read() if server.poll() is not None else "server did not start"
        if crash:
            server.kill()
            server.wait(timeout=5)
            (tmp_path / "ready").unlink()
            server = subprocess.Popen([sys.executable, "-c", SERVER, str(tmp_path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            deadline = time.monotonic() + 5
            while not (tmp_path / "ready").exists() and server.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            assert (tmp_path / "ready").exists()
        paths = [str(tmp_path / "日本語の 画像.png"), str(tmp_path / "別のフォルダー")]
        client = subprocess.run([sys.executable, "-c", CLIENT, *paths], capture_output=True, timeout=7)
        assert client.returncode == 0, client.stderr.decode()
        assert client.stdout.strip() == b"forwarded"
        server.wait(timeout=5)
        assert json.loads((tmp_path / "received.json").read_text()) == paths
    finally:
        if server.poll() is None:
            server.kill()
        server.communicate(timeout=5)
