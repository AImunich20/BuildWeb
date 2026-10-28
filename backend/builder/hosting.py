"""The hosting servers: waitress servers that serve published sites (and nothing else).

- The main port (default 8090) serves every published site at /<slug>/ (and a chosen default site at /).
- A site with its own ``host_port`` is also served at / of that port, so several sites can be hosted
  side by side, each at the root of its own address.
- Optionally everything is published through Tailscale (`serve` for the tailnet, `funnel` for the
  internet) as https://<machine>.ts.net[:port]/.

Servers listen on the LAN (0.0.0.0) when enabled; the editor itself always stays on 127.0.0.1.
They are started/stopped from the settings page without restarting the app.
"""
import logging
import socket
import threading

from waitress.server import create_server

from buildweb import config

from .middleware import PUBLIC_ENV_KEY, SITE_ENV_KEY

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


class _Server:
    def __init__(self, server, thread, port, site=None):
        self.server, self.thread, self.port, self.site = server, thread, port, site


class HostingServer:
    def __init__(self):
        self._servers = {}  # key: "main" or site slug
        self._lock = threading.Lock()
        self.error = ""
        self.site_errors = {}
        self.lan = False
        self.ts_error = ""
        self._ts_published = set()  # https ports we published through tailscale

    # -- servers ---------------------------------------------------------------------------------
    @property
    def running(self):
        return "main" in self._servers

    @property
    def port(self):
        s = self._servers.get("main")
        return s.port if s else None

    def _app(self, site_slug=None):
        from django.core.wsgi import get_wsgi_application

        django_app = get_wsgi_application()

        def app(environ, start_response):
            environ[PUBLIC_ENV_KEY] = True
            if site_slug:
                environ[SITE_ENV_KEY] = site_slug
            return django_app(environ, start_response)

        return app

    def _start_one(self, key, port, lan, site_slug=None):
        host = "0.0.0.0" if lan else "127.0.0.1"
        server = create_server(self._app(site_slug), host=host, port=int(port), threads=8, ident="BuildWeb")
        thread = threading.Thread(target=self._serve, args=(server,), daemon=True, name=f"hosting-{key}")
        self._servers[key] = _Server(server, thread, int(port), site_slug)
        thread.start()
        log.info("hosting %s on %s:%s", key, host, port)

    @staticmethod
    def _serve(server):
        try:
            server.run()
        except Exception:  # closing the socket from stop() ends the loop with an error on some platforms
            pass

    def _stop_all_locked(self):
        for s in list(self._servers.values()):
            try:
                s.server.close()
            except Exception:
                pass
            s.thread.join(timeout=3)
        self._servers.clear()

    def start(self, port, lan, sites=()):
        """Start the main server and one server per (slug, port) in ``sites``."""
        with self._lock:
            self._stop_all_locked()
            self.site_errors = {}
            try:
                self._start_one("main", port, lan)
            except OSError as e:
                self.error = f"เปิดพอร์ต {port} ไม่ได้: {e.strerror or e}"
                log.warning(self.error)
                return False
            self.error, self.lan = "", bool(lan)
            for slug, sport in sites:
                if int(sport) == int(port):
                    self.site_errors[slug] = "พอร์ตซ้ำกับพอร์ตหลัก"
                    continue
                try:
                    self._start_one(slug, sport, lan, slug)
                except OSError as e:
                    self.site_errors[slug] = f"เปิดพอร์ต {sport} ไม่ได้: {e.strerror or e}"
            return True

    def stop(self):
        with self._lock:
            self._stop_all_locked()

    def site_ports(self):
        from .models import Site

        return list(Site.objects.filter(published=True, host_port__isnull=False).values_list("slug", "host_port"))

    def apply_config(self):
        h = config.load()["hosting"]
        ok = True
        if h["enabled"]:
            ok = self.start(h["port"], h["lan"], self.site_ports())
        else:
            self.stop()
        self.apply_tailscale(h if ok else {**h, "enabled": False})
        return ok

    # -- tailscale -------------------------------------------------------------------------------
    def apply_tailscale(self, h=None):
        from . import tailscale

        h = h or config.load()["hosting"]
        self.ts_error = ""
        want = {}
        if h["enabled"] and h.get("tailscale") and self.running:
            want[int(h.get("tailscale_port") or 443)] = (self.port, bool(h.get("funnel")))
            for s in self._servers.values():
                if s.site and s.port not in want:
                    want[s.port] = (s.port, False)  # per-site port: same number over HTTPS, tailnet only
        try:
            for port in self._ts_published - set(want):
                tailscale.unpublish(port)
            for https_port, (local, funnel) in want.items():
                tailscale.publish(local, https_port, funnel=funnel)
            self._ts_published = set(want)
        except (RuntimeError, OSError) as e:
            self.ts_error = str(e)
            log.warning("tailscale: %s", e)

    def shutdown(self):
        """App is quitting: stop servers and take our tailscale publications down."""
        from . import tailscale

        for port in list(self._ts_published):
            try:
                tailscale.unpublish(port)
            except Exception:
                pass
        self._ts_published.clear()
        self.stop()

    # -- status ----------------------------------------------------------------------------------
    def status(self, with_tailscale=True):
        from .models import Site

        h = config.load()["hosting"]
        ip = lan_ip()
        urls = []
        if self.running:
            urls.append(f"http://127.0.0.1:{self.port}/")
            if self.lan:
                urls.append(f"http://{ip}:{self.port}/")
        ts = {}
        if with_tailscale:
            from . import tailscale

            ts = tailscale.status()
        ts_host = ts.get("dns_name") if ts.get("running") else ""
        if ts_host and self.running and self.lan:
            urls.append(f"http://{ts_host}:{self.port}/")
        ts_port = int(h.get("tailscale_port") or 443)
        ts_url = ""
        if ts_host and h.get("tailscale") and int(ts_port) in self._ts_published:
            ts_url = f"https://{ts_host}/" if ts_port == 443 else f"https://{ts_host}:{ts_port}/"
        sites = []
        for s in Site.objects.filter(host_port__isnull=False).order_by("name"):
            srv = self._servers.get(s.slug)
            surls = []
            if srv:
                surls.append(f"http://127.0.0.1:{srv.port}/")
                if self.lan:
                    surls.append(f"http://{ip}:{srv.port}/")
                if ts_host and srv.port in self._ts_published:
                    surls.append(f"https://{ts_host}:{srv.port}/")
            sites.append({"slug": s.slug, "name": s.name, "port": s.host_port, "published": s.published,
                          "running": bool(srv), "urls": surls, "error": self.site_errors.get(s.slug, "")})
        return {
            "enabled": h["enabled"], "running": self.running, "port": h["port"], "lan": h["lan"],
            "default_site": h["default_site"], "error": self.error, "urls": urls, "lan_ip": ip,
            "base": ts_url or (urls[-1] if urls else ""), "site_ports": sites,
            "tailscale": {**ts, "enabled": bool(h.get("tailscale")), "port": ts_port, "funnel": bool(h.get("funnel")),
                          "url": ts_url, "error": self.ts_error},
        }


server = HostingServer()
