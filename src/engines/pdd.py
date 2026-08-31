"""多多进宝 (PDD Open Platform) 引擎。

API 文档: https://open.pinduoduo.com/application/document/api
签名方式: HMAC-SHA256
"""

from __future__ import annotations

import json
import time

from src.config import settings
from src.engines.base import BaseEngine
from src.models import Coupon, Platform, Product


class PDDEngine(BaseEngine):
    """多多进宝搜索引擎"""

    platform = Platform.PDD
    base_url = "https://gw-api.pinduoduo.com/api/router"

    def __init__(self) -> None:
        cfg = settings.pdd
        super().__init__(cfg.client_id, cfg.client_secret)
        self.pid = cfg.pid

    def _sign(self, params: dict[str, str]) -> str:
        return self._hmac_sha256_sign(params, self.app_secret)

    async def _pdd_request(self, api_type: str, biz_params: dict) -> dict:
        params = {
            "type": api_type,
            "client_id": self.app_key,
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
        }
        params.update({k: str(v) for k, v in biz_params.items()})
        params["sign"] = self._sign(params)
        return await self._request("POST", self.base_url, json_body=params)

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """搜索多多进宝商品 (pdd.ddk.goods.search)"""
        resp = await self._pdd_request(
            "pdd.ddk.goods.search",
            {
                "keyword": keyword,
                "page": page,
                "page_size": page_size,
                "pid": self.pid,
            },
        )
        # TODO: 解析 resp → list[Product]
        return []

    async def detail(self, product_id: str) -> Product:
        """获取拼多多商品详情"""
        # TODO: 调用 pdd.ddk.goods.detail
        raise NotImplementedError("拼多多商品详情 — Phase 2 实现")

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """搜索拼多多优惠券"""
        # TODO: pdd.ddk.goods.search 已内置优惠券信息
        return []
