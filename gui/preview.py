"""Serve one downloaded site on localhost for a live view."""

import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


class _QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        return


def _handler_for(directory):
    root = str(directory)

    class Handler(_QuietHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=root, **kwargs)

    return Handler


class PreviewServer:
    """One local server. Starting a different site replaces the previous one."""

    def __init__(self):
        self._httpd = None
        self._thread = None
        self._directory = None
        self.url = None

    def serve(self, directory):
        directory = Path(directory).resolve()
        if not directory.is_dir():
            raise FileNotFoundError(f"No downloaded site at {directory}")
        if self._httpd is not None and self._directory == directory and self.url:
            return self.url
        self.stop()
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(directory))
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        self._httpd = httpd
        self._thread = thread
        self._directory = directory
        host, port = httpd.server_address
        self.url = f"http://{host}:{port}/"
        return self.url

    def stop(self):
        httpd = self._httpd
        thread = self._thread
        self._httpd = None
        self._thread = None
        self._directory = None
        self.url = None
        if httpd is not None:
            httpd.shutdown()
            httpd.server_close()
        if thread is not None:
            thread.join(timeout=3)
