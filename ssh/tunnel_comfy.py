"""Forward local 127.0.0.1:8188 to the remote Qwen-Image 2.1 ComfyUI at :8189."""

import select
import socket
import sys
import threading
from pathlib import Path

import paramiko

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _target import password, target  # noqa: E402


def relay(client_socket: socket.socket, transport: paramiko.Transport) -> None:
    channel = None
    try:
        channel = transport.open_channel(
            "direct-tcpip", ("127.0.0.1", 8189), client_socket.getpeername()
        )
        if channel is None:
            return
        while True:
            readable, _, _ = select.select([client_socket, channel], [], [])
            if client_socket in readable:
                data = client_socket.recv(65536)
                if not data:
                    break
                channel.sendall(data)
            if channel in readable:
                data = channel.recv(65536)
                if not data:
                    break
                client_socket.sendall(data)
    finally:
        if channel is not None:
            channel.close()
        client_socket.close()


def main() -> None:
    host, port = target()
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        host,
        port=port,
        username="root",
        password=password(),
        timeout=25,
        banner_timeout=25,
        auth_timeout=25,
    )
    transport = ssh.get_transport()
    if transport is None:
        raise RuntimeError("SSH transport is unavailable")

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 8188))
    listener.listen(32)
    print(f"READY 127.0.0.1:8188 -> {host}:{port} -> 127.0.0.1:8189", flush=True)
    try:
        while transport.is_active():
            client_socket, _ = listener.accept()
            threading.Thread(
                target=relay, args=(client_socket, transport), daemon=True
            ).start()
    finally:
        listener.close()
        ssh.close()


if __name__ == "__main__":
    main()
