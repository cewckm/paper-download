"""Minimal CDP client over raw websocket (stdlib only). Launch Edge with remote debugging first."""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PROFILE = r"C:\Users\32464\Desktop\wenxian\_tools\edge-profile"
PORT = 9333


class WS:
    def __init__(self, url):
        # ws://host:port/path
        assert url.startswith("ws://")
        rest = url[5:]
        hostport, _, path = rest.partition("/")
        path = "/" + path
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RuntimeError("handshake failed")
            buf += chunk
        head, _, tail = buf.partition(b"\r\n\r\n")
        if b"101" not in head.split(b"\r\n")[0]:
            raise RuntimeError("handshake rejected: " + head.decode("latin1"))
        self.buf = tail
        self.msgid = 0

    def _recv(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise RuntimeError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def send(self, text):
        payload = text.encode()
        mask = os.urandom(4)
        header = bytearray([0x81])
        n = len(payload)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", n)
        header += mask
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def recv(self):
        while True:
            b1, b2 = self._recv(2)
            opcode = b1 & 0x0F
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv(8))[0]
            payload = self._recv(length) if length else b""
            if opcode == 0x9:  # ping
                self.sock.sendall(b"\x8a\x80" + os.urandom(4))
                continue
            if opcode == 0x8:
                raise RuntimeError("closed by peer")
            if opcode in (0x1, 0x2):
                return payload.decode("utf-8", "replace")

    def call(self, method, params=None, timeout=60):
        self.msgid += 1
        mid = self.msgid
        self.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = json.loads(self.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)


def ensure_edge():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=3) as r:
            return json.loads(r.read())
    except Exception:
        pass
    args = [
        EDGE,
        f"--remote-debugging-port={PORT}",
        f"--user-data-dir={PROFILE}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=msEdgeSidebarV2",
        "about:blank",
    ]
    subprocess.Popen(args, close_fds=True)
    for _ in range(40):
        time.sleep(0.5)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=3) as r:
                return json.loads(r.read())
        except Exception:
            continue
    raise RuntimeError("Edge did not expose CDP")


if __name__ == "__main__":
    v = ensure_edge()
    print("EDGE:", json.dumps(v, ensure_ascii=False)[:400])
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/list", timeout=5) as r:
        tabs = json.loads(r.read())
    for t in tabs:
        print(t.get("type"), t.get("url", "")[:120], t.get("webSocketDebuggerUrl", "")[:80])
