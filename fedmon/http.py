"""带重试的 HTTP 会话。"""
import time

import requests

from .config import USER_AGENT

_session = None


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        s.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
        _session = s
    return _session


def get(url: str, *, params=None, timeout=60, retries=3, **kw) -> requests.Response:
    last = None
    for i in range(retries):
        try:
            r = session().get(url, params=params, timeout=timeout, **kw)
            if r.status_code == 200:
                return r
            last = RuntimeError(f"HTTP {r.status_code} for {url}")
            if r.status_code in (400, 403, 404):
                break
        except requests.RequestException as e:  # 网络错误才重试
            last = e
        time.sleep(2 ** (i + 1))
    raise last
