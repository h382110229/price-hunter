"""京东联盟 (JD Union Open Platform) 引擎。

API 文档: https://union.jd.com/openplatform/api
签名方式: MD5 (京东联盟通用签名)
"""

from __future__ import annotations

from datetime import datetime

from src.config import settings
from src.engines.base import BaseEngine
from src.models import Coupon, Platform, Product


class JDEngine(BaseEngine):
    """京东联盟搜索引擎"""

    platform = Platform.JD
    base_url = "https://api.jd.com/routerjson"

    def __init__(self) -> None:
        cfg = settings.jd
        super().__init__(cfg.app_key, cfg.app_secret)
        self.site_id = cfg.site_id

    def _sign(self, params: dict[str, str]) -> str:
        return self._md5_sign(params, self.app_secret)

    def _common_params(self, method: str) -> dict[str, str]:
        return {
            "method": method,
            "app_key": self.app_key,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
        }

    async def _jd_request(self, method: str, param_json: str) -> dict:
        params = self._common_params(method)
        params["param_json"] = param_json
        params["sign"] = self._sign(params)
        return await self._request("POST", self.base_url, params=params)

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """搜索京东联盟商品 (jd.union.open.goods.query)"""
        import json

        param = json.dumps(
            {
                "goodsReq": {
                    "keyword": keyword,
                    "pageIndex": page,
                    "pageSize": page_size,
                    "siteId": self.site_id,
                }
            }
        )
        resp = await self._jd_request("jd.union.open.goods.query", param)
        # TODO: 解析 resp → list[Product]
        return []

    async def detail(self, product_id: str) -> Product:
        """获取京东商品详情"""
        # TODO: 调用 jd.union.open.goods.promotiongoodsinfo.query
        raise NotImplementedError("京东商品详情 — Phase 2 实现")

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """搜索京东优惠券"""
        # TODO: 调用 jd.union.open.coupon.query
        return []
