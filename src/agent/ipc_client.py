"""
Python IPC client for communicating with the DotE Agent Mod.

Uses raw TCP sockets with 4-byte big-endian length-prefixed JSON framing,
matching the C# IpcBridge implementation.

Port 5555: State channel (mod -> Python) - receives game state
Port 5556: Action channel (Python -> mod -> Python) - sends commands, receives results
"""

import json
import socket
import struct
import time
from typing import Optional


class IpcClient:
    """
    TCP client for two-way communication with the DotE BepInEx mod.

    Usage:
        client = IpcClient()
        client.connect()
        state = client.receive_state()
        result = client.send_action("MOVE_HERO", {"hero_name": "Max O'Kane", "target_room_index": 1})
        client.disconnect()
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        state_port: int = 5555,
        action_port: int = 5556,
        connect_timeout: float = 300.0,
        recv_timeout: float = 30.0,
    ):
        self.host = host
        self.state_port = state_port
        self.action_port = action_port
        self.connect_timeout = connect_timeout
        self.recv_timeout = recv_timeout

        self._state_sock: Optional[socket.socket] = None
        self._action_sock: Optional[socket.socket] = None

    @property
    def is_connected(self) -> bool:
        """True if both state and action sockets are connected."""
        return self._state_sock is not None and self._action_sock is not None

    def connect(self, retry_interval: float = 2.0) -> None:
        """
        Connect to both the state and action ports.
        Retries until connected or timeout is reached.
        """
        self._state_sock = self._connect_with_retry(self.state_port, retry_interval)
        self._action_sock = self._connect_with_retry(self.action_port, retry_interval)

    def disconnect(self) -> None:
        """Disconnect from both ports."""
        if self._state_sock:
            try:
                self._state_sock.close()
            except Exception:
                pass
            self._state_sock = None

        if self._action_sock:
            try:
                self._action_sock.close()
            except Exception:
                pass
            self._action_sock = None

    def receive_state(self, timeout: Optional[float] = None) -> dict:
        """
        Receive a game state message from the mod (port 5555).
        Blocks until a message arrives or timeout is reached.

        Returns:
            Parsed JSON dict of the GameStatePayload.

        Raises:
            ConnectionError: If the connection is closed.
            TimeoutError: If no message arrives within timeout.
        """
        if self._state_sock is None:
            raise ConnectionError("Not connected to state port")

        effective_timeout = timeout if timeout is not None else self.recv_timeout
        self._state_sock.settimeout(effective_timeout)

        try:
            return self._receive_message(self._state_sock)
        except socket.timeout:
            raise TimeoutError(
                f"No state received within {effective_timeout}s"
            )

    def send_action(self, command: str, parameters: Optional[dict] = None) -> dict:
        """
        Send an action command to the mod and wait for the result.

        Args:
            command: The action verb (e.g., "MOVE_HERO", "OPEN_DOOR")
            parameters: Dict of command parameters

        Returns:
            Parsed JSON dict of the ActionResult (has 'success', 'error', 'metadata').

        Raises:
            ConnectionError: If the connection is closed.
            TimeoutError: If no response arrives within timeout.
        """
        if self._action_sock is None:
            raise ConnectionError("Not connected to action port")

        payload = {
            "command": command,
            "parameters": parameters or {},
            "timestamp": int(time.time() * 1000),
        }

        self._send_message(self._action_sock, payload)

        self._action_sock.settimeout(self.recv_timeout)
        try:
            return self._receive_message(self._action_sock)
        except socket.timeout:
            raise TimeoutError(
                f"No action response within {self.recv_timeout}s"
            )

    def wait_for_state(
        self,
        condition=None,
        timeout: float = 300.0,
    ) -> dict:
        """
        Keep receiving state messages until a condition is met.

        Args:
            condition: A callable(state_dict) -> bool. If None, returns first state.
            timeout: Maximum time to wait.

        Returns:
            The state dict that satisfied the condition.

        Raises:
            TimeoutError: If condition not met within timeout.
        """
        if self._state_sock is None:
            raise ConnectionError("Not connected to state port")

        start = time.time()
        while time.time() - start < timeout:
            remaining = timeout - (time.time() - start)
            if remaining <= 0:
                break

            self._state_sock.settimeout(min(remaining, 5.0))
            try:
                state = self._receive_message(self._state_sock)
                if condition is None or condition(state):
                    return state
            except socket.timeout:
                continue

        raise TimeoutError(f"State condition not met within {timeout}s")

    # --- Private helpers ---

    def _connect_with_retry(self, port: int, retry_interval: float) -> socket.socket:
        """Connect to a port, retrying until timeout."""
        start = time.time()
        while time.time() - start < self.connect_timeout:
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.host, port))
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                return sock
            except (ConnectionRefusedError, OSError, socket.timeout):
                sock.close()
                time.sleep(retry_interval)

        raise ConnectionError(
            f"Could not connect to {self.host}:{port} within {self.connect_timeout}s"
        )

    def _send_message(self, sock: socket.socket, payload: dict) -> None:
        """Send a length-prefixed JSON message."""
        json_bytes = json.dumps(payload).encode("utf-8")
        length_prefix = struct.pack(">I", len(json_bytes))
        sock.sendall(length_prefix + json_bytes)

    def _receive_message(self, sock: socket.socket) -> dict:
        """Receive a length-prefixed JSON message."""
        raw_len = self._recv_exact(sock, 4)
        msg_len = struct.unpack(">I", raw_len)[0]
        payload = self._recv_exact(sock, msg_len)
        return json.loads(payload.decode("utf-8"))

    def _recv_exact(self, sock: socket.socket, n: int) -> bytes:
        """Receive exactly n bytes."""
        data = b""
        while len(data) < n:
            chunk = sock.recv(n - len(data))
            if not chunk:
                raise ConnectionError("Connection closed by remote")
            data += chunk
        return data

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
        return False

    def __del__(self):
        self.disconnect()
