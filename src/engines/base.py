"""搜索引擎基类与签名抽象。

每个平台引擎需实现:
- _sign()       → 请求签名
- search()      → 商品搜索
- detail()      → 商品详情
- get_coupons() → 优惠券查询
"""

from __future__ import annotations

import hashlib
import hmac
import time
from abc import ABC, abstractmethod
from typing import Any

import httpx

from src.models import Coupon, Platform, Product


class BaseEngine(ABC):
    """联盟 API 引擎抽象基类"""

    platform: Platform
    base_url: str

    def __init__(self, app_key: str, app_secret: str) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self._client = httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        await self._client.aclose()

    # ── 签名工具 ──────────────────────────────────────────

    @staticmethod
    def _md5_sign(params: dict[str, str], secret: str) -> str:
        """TOP API 通用 MD5 签名 (淘宝/京东)。

        1. 参数按 key 排序
        2. 拼接为 key1value1key2value2...secret...
        3. MD5 → 大写 hex
        """
        sorted_params = sorted(params.items())
        sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
        return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()

    @staticmethod
    def _hmac_sha256_sign(params: dict[str, str], secret: str) -> str:
        """HMAC-SHA256 签名 (拼多多)"""
        sorted_params = sorted(params.items())
        sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
        return hmac.new(
            secret.encode("utf-8"),
            sign_str.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest().upper()

    @abstractmethod
    def _sign(self, params: dict[str, str]) -> str:
        """生成平台签名 — 由子类选择签名算法"""
        ...

    # ── 通用请求 ──────────────────────────────────────────

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """发送 HTTP 请求，返回 JSON 响应"""
        resp = await self._client.request(
            method, url, params=params, json=json_body
        )
        resp.raise_for_status()
        return resp.json()

    # ── 业务接口 (子类实现) ──────────────────────────────

    @abstractmethod
    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """按关键词搜索商品"""
        ...

    @abstractmethod
    async def detail(self, product_id: str) -> Product:
        """获取商品详情"""
        ...

    @abstractmethod
    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """搜索优惠券"""
        ...

    # ── 上下文管理器 ──────────────────────────────────────

    async def __aenter__(self) -> "BaseEngine":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
