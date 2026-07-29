import subprocess
import time

from infrastructure.config import settings


class CRGServerManager:
    def __init__(self, server_url: str | None = None) -> None:
        self._server_url = server_url or settings.crg_server_url
        self._process: subprocess.Popen | None = None

    def start(self) -> None:
        if self._process is not None:
            return
        self._process = subprocess.Popen(
            ["code-review-graph", "serve", "--http", "--port", "5555"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    def stop(self) -> None:
        if self._process is None:
            return
        self._process.terminate()
        self._process.wait(timeout=10)
        self._process = None

    def health_check(self, timeout: float = 10.0) -> bool:
        import urllib.request
        import urllib.error

        start = time.time()
        while time.time() - start < timeout:
            try:
                urllib.request.urlopen(self._server_url, timeout=2)
                return True
            except urllib.error.URLError:
                time.sleep(0.5)
        return False
