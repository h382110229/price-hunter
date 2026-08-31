"""淘宝联盟 (Taobao客 TOP API) 引擎。

API 文档: https://open.taobao.com/api.htm?docId=28541&docType=2
签名方式: MD5 (TOP 通用签名)
"""

from __future__ import annotations

from datetime import datetime

from src.config import settings
from src.engines.base import BaseEngine
from src.models import Coupon, Platform, Product


class TaobaoEngine(BaseEngine):
    """淘宝联盟搜索引擎"""

    platform = Platform.TAOBAO
    base_url = "https://eco.taobao.com/router/rest"

    def __init__(self) -> None:
        cfg = settings.taobao
        super().__init__(cfg.app_key, cfg.app_secret)
        self.adzone_id = cfg.adzone_id

    def _sign(self, params: dict[str, str]) -> str:
        return self._md5_sign(params, self.app_secret)

    def _common_params(self, method: str) -> dict[str, str]:
        """TOP API 公共参数"""
        return {
            "method": method,
            "app_key": self.app_key,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
        }

    async def _top_request(self, method: str, biz_params: dict[str, str]) -> dict:
        """发送 TOP API 请求"""
        params = self._common_params(method)
        params.update(biz_params)
        params["sign"] = self._sign(params)
        return await self._request("POST", self.base_url, params=params)

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """搜索淘宝联盟商品 (taobao.tbk.dg.material.optional)"""
        resp = await self._top_request(
            "taobao.tbk.dg.material.optional",
            {
                "adzone_id": self.adzone_id,
                "q": keyword,
                "page_no": str(page),
                "page_size": str(page_size),
            },
        )
        # TODO: 解析 resp → list[Product]
        return []

    async def detail(self, product_id: str) -> Product:
        """获取淘宝商品详情"""
        # TODO: 调用 taobao.tbk.item.info.get
        raise NotImplementedError("淘宝商品详情 — Phase 2 实现")

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """搜索淘宝优惠券"""
        # TODO: 调用 taobao.tbk.coupon.get
        return []
