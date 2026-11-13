"""One application per settings profile, with acknowledged local open requests."""
import hashlib
import json

from PySide6.QtCore import QObject, QLockFile, QThread, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

from .preferences import settings_path
from . import legacy


class InstanceBroker(QObject):
    requested = Signal(list)

    def __init__(self):
        super().__init__()
        path = settings_path().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Stable local protocol identifier, including arbitrary profile filenames,
        # so an older process can acknowledge requests during an upgrade.
        self.name = legacy.SLUG + "-" + hashlib.sha256(str(path).encode()).hexdigest()[:40]
        self.lock = QLockFile(str(path.with_suffix(".instance.lock")))
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.server.newConnection.connect(self._accept)
        self.sockets = {}

    def start_or_forward(self, paths):
        if self.lock.tryLock(0):
            QLocalServer.removeServer(self.name)
            if not self.server.listen(self.name):
                self.lock.unlock()
                return "unavailable"
            return "primary"
        # Another process may be between taking the lock and starting its server.
        for _ in range(10):
            socket = QLocalSocket()
            socket.connectToServer(self.name)
            if not socket.waitForConnected(200):
                socket.abort()
                QThread.msleep(80)
                continue
            socket.write(json.dumps({"paths": paths}, ensure_ascii=False).encode() + b"\n")
            socket.waitForBytesWritten(500)
            if (socket.canReadLine() or socket.waitForReadyRead(1500)) and bytes(socket.readAll()) == b"OK\n":
                socket.disconnectFromServer()
                return "forwarded"
            return "unavailable"
        return "unavailable"

    def _accept(self):
        while self.server.hasPendingConnections():
            socket = self.server.nextPendingConnection()
            self.sockets[socket] = bytearray()
            socket.readyRead.connect(lambda connection=socket: self._read(connection))
            socket.disconnected.connect(lambda connection=socket: self._drop(connection))
            self._read(socket)

    def _drop(self, socket):
        self.sockets.pop(socket, None)
        socket.deleteLater()

    def _read(self, socket):
        if socket not in self.sockets:
            return
        buffer = self.sockets[socket]
        if buffer is None:
            return
        buffer.extend(bytes(socket.readAll()))
        if len(buffer) > 1024 * 1024:
            socket.abort()
            return
        if b"\n" not in buffer:
            return
        try:
            value = json.loads(bytes(buffer))
            paths = value["paths"]
            if not isinstance(paths, list) or len(paths) > 5000 or any(not isinstance(path, str) or "\0" in path for path in paths):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            socket.abort()
            return
        self.sockets[socket] = None
        self.requested.emit(paths)
        socket.write(b"OK\n")
        socket.flush()
        socket.disconnectFromServer()

    def close(self):
        self.server.close()
        for socket in list(self.sockets):
            socket.abort()
        self.lock.unlock()
