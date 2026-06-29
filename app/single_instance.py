"""Single-instance support.

Double-clicking a ``.md`` file in the file manager launches a fresh process;
without coordination that means a second copy of the app. This module lets the
first process own a named local socket: later processes connect to it, hand off
the path to open (in a new tab) and exit, so there is always just one window.
"""

from __future__ import annotations

import getpass

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

_CONNECT_TIMEOUT_MS = 300
_IO_TIMEOUT_MS = 1000


def _default_key() -> str:
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - fall back to a fixed key
        user = "default"
    return f"MdReader-singleton-{user}"


class SingleInstance(QObject):
    """Owns (or talks to) the primary instance over a local socket."""

    message_received = Signal(str)  # payload forwarded by a later instance

    def __init__(self, key: str | None = None) -> None:
        super().__init__()
        self._key = key or _default_key()
        self._server: QLocalServer | None = None
        self.is_primary = False

    def try_become_primary(self) -> bool:
        """Return True if no other instance is running and we now own the
        server; False if another instance already holds it."""
        probe = QLocalSocket()
        probe.connectToServer(self._key)
        if probe.waitForConnected(_CONNECT_TIMEOUT_MS):
            probe.abort()
            return False

        # No server responding — clear any stale socket left by a crash, then
        # start listening ourselves.
        QLocalServer.removeServer(self._key)
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_new_connection)
        if not self._server.listen(self._key):
            self._server = None
            return False
        self.is_primary = True
        return True

    def send_to_primary(self, payload: str) -> bool:
        """Forward ``payload`` (a path, or "") to the running instance."""
        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if not socket.waitForConnected(_IO_TIMEOUT_MS):
            return False
        socket.write(payload.encode("utf-8"))
        socket.flush()
        socket.waitForBytesWritten(_IO_TIMEOUT_MS)
        socket.disconnectFromServer()
        if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
            socket.waitForDisconnected(_IO_TIMEOUT_MS)
        return True

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        socket = self._server.nextPendingConnection()
        if socket is None:
            return
        if socket.waitForReadyRead(_IO_TIMEOUT_MS):
            payload = bytes(socket.readAll().data()).decode("utf-8", errors="replace")
            self.message_received.emit(payload)
        socket.disconnectFromServer()
        socket.deleteLater()
