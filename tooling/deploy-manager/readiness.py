"""Waits until a task service accepts connections on its Unix socket (gRPC)."""

import socket
import time


def wait_for_socket(path: str, timeout: float = 30, interval: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1)
        try:
            if s.connect_ex(path) == 0:
                return True
        except OSError:
            pass
        finally:
            s.close()
        time.sleep(interval)
    return False
