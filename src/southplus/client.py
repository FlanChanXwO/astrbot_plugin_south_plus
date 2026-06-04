"""South Plus 共享 HTTP 会话。

持有单个 ``httpx.Client`` 实例复用连接池，所有 API 模块共享。
仅 ``SouthPlusLoginAttempt`` 因需要独立 cookie jar 而创建临时 client。
"""

from __future__ import annotations

import httpx

from .models import SouthPlusEndpoints

__all__ = ["SouthPlusSession"]


class SouthPlusSession:
    """共享 HTTP 会话 — 持有单个 ``httpx.Client`` 复用连接池。

    典型用法::

        session = SouthPlusSession(endpoints, http_proxy=proxy)
        # session.client 是持久 httpx.Client，API 模块直接用。
        response = session.client.get(url, headers={...})
        # 用完后关闭：
        session.close()

    也可以当 context manager::

        with SouthPlusSession(endpoints) as session:
            ...
    """

    def __init__(
        self,
        endpoints: SouthPlusEndpoints,
        *,
        http_proxy: str | None = None,
    ) -> None:
        self.endpoints = endpoints
        self._proxy = http_proxy
        self._client: httpx.Client | None = httpx.Client(
            headers={"User-Agent": endpoints.user_agent},
            follow_redirects=True,
            timeout=20.0,
            proxy=http_proxy,
        )

    @property
    def client(self) -> httpx.Client:
        """共享的持久 ``httpx.Client`` 实例。"""
        assert self._client is not None, "SouthPlusSession already closed"
        return self._client

    def create_isolated_client(
        self,
        *,
        headers: dict[str, str] | None = None,
        timeout: float = 20.0,
    ) -> httpx.Client:
        """创建独立的 ``httpx.Client``（用于需要独立 cookie jar 的场景，如登录）。

        调用方负责用 ``with`` 管理生命周期::

            with session.create_isolated_client(headers={...}) as client:
                ...
        """
        base_headers: dict[str, str] = {
            "User-Agent": self.endpoints.user_agent,
        }
        if headers:
            base_headers.update(headers)
        return httpx.Client(
            headers=base_headers,
            follow_redirects=True,
            timeout=timeout,
            proxy=self._proxy,
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> SouthPlusSession:
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.close()
