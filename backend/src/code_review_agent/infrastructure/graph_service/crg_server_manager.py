import time

from infrastructure.config import settings


class CRGServerManager:
    def __init__(self, server_url: str | None = None) -> None:
        self._server_url = server_url or settings.crg_server_url

    def ensure_connected(self, timeout: float = 10.0) -> None:
        import urllib.error
        import urllib.request

        start = time.time()
        while time.time() - start < timeout:
            try:
                urllib.request.urlopen(self._server_url, timeout=2)
                return
            except urllib.error.HTTPError:
                return
            except urllib.error.URLError:
                time.sleep(0.5)

        raise RuntimeError(
            f"CRG server unreachable at {self._server_url} "
            f"after {timeout}s. Ensure it is running."
        )
