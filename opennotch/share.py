"""Share one explicitly selected local file with a phone on the same network."""
from http.server import BaseHTTPRequestHandler, HTTPServer
import ipaddress
import json
import os
import secrets
import stat
import subprocess
import threading
import time
from urllib.parse import quote

DURATION_SECONDS = 300


def local_interface():
    """Use the LAN address of the route selected by the host, without sending a packet."""
    def run(*args):
        return json.loads(subprocess.check_output(["ip", "-j", *args], text=True, timeout=1))

    try:
        route = run("route", "get", "192.0.2.1")[0]
        info = run("-4", "address", "show", "dev", route["dev"])[0]["addr_info"]
        selected = next(value for value in info if value["local"] == route["prefsrc"])
        interface = ipaddress.IPv4Interface(f"{selected['local']}/{selected['prefixlen']}")
        if interface.ip.is_private and not interface.ip.is_loopback:
            return interface
    except (OSError, subprocess.SubprocessError, ValueError, IndexError, KeyError, StopIteration):
        pass
    raise ValueError("Connect this computer and your phone to the same local network.")


class ShareSession:
    def __init__(self, path, interface, duration=DURATION_SECONDS):
        self.stop = threading.Event()
        self.deadline = time.monotonic() + duration
        self.route = "/" + secrets.token_urlsafe(20)
        self.network = interface.network
        self.basename = os.path.basename(path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        self.file = os.fdopen(fd, "rb")
        try:
            info = os.fstat(self.file.fileno())
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Only ordinary files can be shared.")
            self.size = info.st_size
            self.server = HTTPServer((str(interface.ip), 0), _DownloadHandler)
        except (OSError, ValueError):
            self.file.close()
            raise
        self.server.share = self
        self.server.timeout = 0.25
        self.url = f"http://{interface.ip}:{self.server.server_port}{self.route}"
        self.worker = threading.Thread(target=self._serve, daemon=True, name="opennotch-share")
        self.worker.start()

    def _serve(self):
        try:
            while self.active:
                self.server.handle_request()
        finally:
            self.server.server_close()
            self.file.close()

    @property
    def active(self):
        return not self.stop.is_set() and time.monotonic() < self.deadline

    def close(self):
        self.stop.set()


class _DownloadHandler(BaseHTTPRequestHandler):
    def setup(self):
        self.request.settimeout(4)
        super().setup()

    def _allowed(self):
        share = self.server.share
        return (share.active and ipaddress.IPv4Address(self.client_address[0]) in share.network and
                secrets.compare_digest(self.path.encode("utf-8"), share.route.encode("ascii")))

    def do_HEAD(self):
        if not self._allowed():
            self.send_error(404)
            return False
        share = self.server.share
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(share.size))
        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(share.basename, safe=""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        return True

    def do_GET(self):
        if not self.do_HEAD():
            return
        share = self.server.share
        share.file.seek(0)
        remaining = share.size
        try:
            while remaining and share.active:
                data = share.file.read(min(65536, remaining))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)
        except (OSError, TimeoutError):
            return

    def log_message(self, *_args):
        return
