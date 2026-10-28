"""The hosting server: a second waitress server that serves published sites (and nothing else).

It can listen on the LAN (0.0.0.0) so phones/other computers can open the sites, while the editor stays
on 127.0.0.1. It is started/stopped from the settings page without restarting the app.
"""
import logging
import socket
import threading

from waitress.server import create_server

from buildweb import config

from .middleware import PUBLIC_ENV_KEY

log = logging.getLogger("buildweb")


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def port_free(port, host="0.0.0.0"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


class HostingServer:
    def __init__(self):
        self._server = None
        self._thread = None
        self._lock = threading.Lock()
        self.error = ""
        self.port = None
        self.lan = False

    @property
    def running(self):
        return self._server is not None

    def _app(self):
        from django.core.wsgi import get_wsgi_application

        django_app = get_wsgi_application()

        def app(environ, start_response):
            environ[PUBLIC_ENV_KEY] = True
            return django_app(environ, start_response)

        return app

    def start(self, port, lan):
        with self._lock:
            self._stop_locked()
            host = "0.0.0.0" if lan else "127.0.0.1"
            try:
                server = create_server(self._app(), host=host, port=int(port), threads=8, ident="BuildWeb")
            except OSError as e:
                self.error = f"เปิดพอร์ต {port} ไม่ได้: {e.strerror or e}"
                log.warning(self.error)
                return False
            self._server, self.port, self.lan, self.error = server, int(port), bool(lan), ""
            self._thread = threading.Thread(target=self._serve, args=(server,), daemon=True, name="hosting")
            self._thread.start()
            log.info("hosting on %s:%s", host, port)
            return True

    def _serve(self, server):
        try:
            server.run()
        except Exception as e:  # closed by stop() raises in asyncore loop on some platforms
            if self._server is server:
                self.error = str(e)

    def _stop_locked(self):
        if self._server is not None:
            server, self._server = self._server, None
            try:
                server.close()
            except Exception:
                pass
            if self._thread:
                self._thread.join(timeout=3)
            self._thread = None

    def stop(self):
        with self._lock:
            self._stop_locked()

    def apply_config(self):
        h = config.load()["hosting"]
        if h["enabled"]:
            return self.start(h["port"], h["lan"])
        self.stop()
        return True

    def status(self):
        h = config.load()["hosting"]
        ip = lan_ip()
        urls = []
        if self.running:
            urls.append(f"http://127.0.0.1:{self.port}/")
            if self.lan:
                urls.append(f"http://{ip}:{self.port}/")
        return {
            "enabled": h["enabled"], "running": self.running, "port": h["port"], "lan": h["lan"],
            "default_site": h["default_site"], "error": self.error, "urls": urls, "lan_ip": ip,
            "base": urls[-1] if urls else "",
        }


server = HostingServer()
