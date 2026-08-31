"""淘宝联盟 (Taobao客 TOP API) 引擎。

API 文档: https://open.taobao.com/api.htm?docId=28541&docType=2
签名方式: MD5(secret + sorted_kv + secret).upper()
接口: taobao.tbk.dg.material.optional (物料搜索)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.config import settings
from src.engines.base import BaseEngine, _mock_coupons, _mock_products
from src.models import Coupon, Platform, Product

logger = logging.getLogger(__name__)


class TaobaoEngine(BaseEngine):
    """淘宝联盟搜索引擎"""

    platform = Platform.TAOBAO
    base_url = "https://eco.taobao.com/router/rest"

    def __init__(self) -> None:
        cfg = settings.taobao
        super().__init__(cfg.app_key, cfg.app_secret)
        self.adzone_id = cfg.adzone_id

    def _sign(self, params: dict[str, str]) -> str:
        from src.engines.base import md5_sign

        return md5_sign(params, self.app_secret)

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

    def _parse_product(self, item: dict) -> Product:
        """解析淘宝 API 返回的商品数据为统一 Product 模型。

        关键字段映射:
        - item["zk_final_price"] → 商品折后价
        - item["coupon_amount"]  → 优惠券面额
        - item["coupon_info"]    → 券信息 (如 "满199减50")
        - item["coupon_click_url"] → 领券链接
        - item["url"] / item["click_url"] → 推广链接
        - item["tk_total_sales"] → 月销量
        """
        price = float(item.get("zk_final_price", 0) or item.get("reserve_price", 0))
        coupon_amount = float(item.get("coupon_amount", 0) or 0)
        final_price = max(0.0, price - coupon_amount)

        coupons = []
        if coupon_amount > 0:
            coupons.append(
                Coupon(
                    platform=self.platform,
                    coupon_id=str(item.get("coupon_id", "")),
                    title=item.get("coupon_info", f"满减{coupon_amount}元"),
                    discount=coupon_amount,
                    min_spend=float(
                        item.get("coupon_start_fee", price) or price
                    ),
                    url=item.get("coupon_click_url", ""),
                )
            )

        return Product(
            platform=self.platform,
            product_id=str(item.get("num_iid", item.get("item_id", ""))),
            title=item.get("title", ""),
            price=price,
            coupon_amount=coupon_amount,
            final_price=final_price,
            original_price=float(item.get("reserve_price", 0) or 0),
            url=item.get("click_url", item.get("url", "")),
            coupon_url=item.get("coupon_click_url", ""),
            tkl_or_command=item.get("tkl", ""),
            image_url=item.get("pict_url", ""),
            detail_url=item.get("item_url", ""),
            shop_name=item.get("shop_title", item.get("nick", "")),
            sales_volume=int(item.get("tk_total_sales", 0) or 0),
            commission_rate=float(item.get("commission_rate", 0) or 0),
            coupons=coupons,
        )

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """搜索淘宝联盟商品 (taobao.tbk.dg.material.optional)"""
        if self.dry_run:
            return _mock_products(keyword, self.platform, page_size)

        resp = await self._top_request(
            "taobao.tbk.dg.material.optional",
            {
                "adzone_id": self.adzone_id,
                "q": keyword,
                "page_no": str(page),
                "page_size": str(page_size),
            },
        )
        try:
            result = resp.get("tbk_dg_material_optional_response", {})
            items = result.get("result_list", {}).get("map_data", [])
            return [self._parse_product(item) for item in items]
        except (KeyError, TypeError) as e:
            logger.warning("淘宝搜索解析失败: %s, resp=%s", e, json.dumps(resp, ensure_ascii=False)[:500])
            return []

    async def detail(self, product_id: str) -> Product:
        """获取淘宝商品详情 (taobao.tbk.item.info.get)"""
        if self.dry_run:
            products = _mock_products("detail", self.platform, 1)
            p = products[0]
            p.product_id = product_id
            return p

        resp = await self._top_request(
            "taobao.tbk.item.info.get",
            {"num_iids": product_id},
        )
        try:
            result = resp.get("tbk_item_info_get_response", {})
            items = result.get("results", {}).get("n_tbk_item", [])
            if items:
                return self._parse_product(items[0])
            raise ValueError(f"商品 {product_id} 未找到")
        except (KeyError, TypeError) as e:
            logger.warning("淘宝详情解析失败: %s", e)
            raise

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """搜索淘宝优惠券 (taobao.tbk.coupon.get)"""
        if self.dry_run:
            return _mock_coupons(keyword, self.platform)

        resp = await self._top_request(
            "taobao.tbk.coupon.get",
            {
                "adzone_id": self.adzone_id,
                "search": keyword,
                "page_no": str(page),
                "page_size": "20",
            },
        )
        try:
            result = resp.get("tbk_coupon_get_response", {})
            data = result.get("data", {})
            items = data if isinstance(data, list) else data.get("results", {}).get("tbk_coupon", [])
            return [
                Coupon(
                    platform=self.platform,
                    coupon_id=str(c.get("coupon_id", "")),
                    title=c.get("coupon_info", ""),
                    discount=float(c.get("coupon_amount", 0)),
                    min_spend=float(c.get("coupon_start_fee", 0)),
                    url=c.get("coupon_click_url", ""),
                )
                for c in items
            ]
        except (KeyError, TypeError) as e:
            logger.warning("淘宝优惠券解析失败: %s", e)
            return []
