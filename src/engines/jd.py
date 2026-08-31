"""京东联盟 (JD Union Open Platform) 引擎。

API 文档: https://union.jd.com/openplatform/api
签名方式: MD5(secret + sorted_kv + secret).upper()
接口: jd.union.open.goods.query (商品查询)
"""

from __future__ import annotations

import json
import logging
from datetime import datetime

from src.config import settings
from src.engines.base import BaseEngine, _mock_coupons, _mock_products
from src.models import Coupon, Platform, Product

logger = logging.getLogger(__name__)


class JDEngine(BaseEngine):
    """京东联盟搜索引擎"""

    platform = Platform.JD
    base_url = "https://api.jd.com/routerjson"

    def __init__(self) -> None:
        cfg = settings.jd
        super().__init__(cfg.app_key, cfg.app_secret)
        self.site_id = cfg.site_id

    def _sign(self, params: dict[str, str]) -> str:
        from src.engines.base import md5_sign

        return md5_sign(params, self.app_secret)

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

    def _parse_product(self, item: dict) -> Product:
        """解析京东 API 返回的商品数据。

        关键字段映射:
        - item["priceInfo"]["price"]          → 面价
        - item["couponInfo"]["couponList"]    → 优惠券列表
        - item["promotionInfo"]["clickURL"]   → 推广链接
        - item["shopInfo"]["shopName"]        → 店铺名
        """
        price_info = item.get("priceInfo", {})
        price = float(price_info.get("price", 0))

        # 提取最优优惠券
        coupon_info = item.get("couponInfo", {})
        coupon_list = coupon_info.get("couponList", [])
        best_discount = 0.0
        coupon_url = ""
        coupon_id = ""
        min_spend = 0.0
        if coupon_list:
            best = max(coupon_list, key=lambda c: float(c.get("discount", 0)))
            best_discount = float(best.get("discount", 0))
            coupon_url = best.get("link", "")
            coupon_id = str(best.get("couponId", ""))
            min_spend = float(best.get("quota", 0))

        final_price = max(0.0, price - best_discount)

        # 推广链接
        promotion_info = item.get("promotionInfo", {})
        click_url = promotion_info.get("clickURL", "")

        # 店铺
        shop_info = item.get("shopInfo", {})

        # 销量
        in_order_count = item.get("inOrderCount30Days", item.get("inOrderCount30DaysSku", 0))

        coupons = []
        if best_discount > 0:
            coupons.append(
                Coupon(
                    platform=self.platform,
                    coupon_id=coupon_id,
                    title=f"满{min_spend:.0f}减{best_discount:.0f}",
                    discount=best_discount,
                    min_spend=min_spend,
                    url=coupon_url,
                )
            )

        return Product(
            platform=self.platform,
            product_id=str(item.get("skuId", "")),
            title=item.get("skuName", ""),
            price=price,
            coupon_amount=best_discount,
            final_price=final_price,
            original_price=float(price_info.get("price", 0)),
            url=click_url,
            coupon_url=coupon_url,
            image_url=item.get("imageInfo", {}).get("imageList", [{}])[0].get("url", "")
            if item.get("imageInfo", {}).get("imageList")
            else "",
            detail_url=f"https://item.jd.com/{item.get('skuId', '')}.html",
            shop_name=shop_info.get("shopName", ""),
            sales_volume=int(in_order_count) if in_order_count else 0,
            commission_rate=float(item.get("commissionInfo", {}).get("commissionShare", 0) or 0),
            coupons=coupons,
        )

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """搜索京东联盟商品 (jd.union.open.goods.query)"""
        if self.dry_run:
            return _mock_products(keyword, self.platform, page_size)

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
        try:
            result = resp.get("jd_union_open_goods_query_responce", {})
            data = json.loads(result.get("queryResult", "{}"))
            items = data.get("data", [])
            return [self._parse_product(item) for item in items]
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("京东搜索解析失败: %s, resp=%s", e, json.dumps(resp, ensure_ascii=False)[:500])
            return []

    async def detail(self, product_id: str) -> Product:
        """获取京东商品详情 (jd.union.open.goods.promotiongoodsinfo.query)"""
        if self.dry_run:
            products = _mock_products("detail", self.platform, 1)
            p = products[0]
            p.product_id = product_id
            return p

        param = json.dumps({"skuIds": product_id})
        resp = await self._jd_request(
            "jd.union.open.goods.promotiongoodsinfo.query", param
        )
        try:
            result = resp.get("jd_union_open_goods_promotiongoodsinfo_query_responce", {})
            data = json.loads(result.get("queryResult", "{}"))
            items = data.get("data", [])
            if items:
                return self._parse_product(items[0])
            raise ValueError(f"商品 {product_id} 未找到")
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("京东详情解析失败: %s", e)
            raise

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """搜索京东优惠券 (jd.union.open.coupon.query)"""
        if self.dry_run:
            return _mock_coupons(keyword, self.platform)

        param = json.dumps(
            {"couponUrls": [], "pageIndex": page, "pageSize": 20}
        )
        resp = await self._jd_request("jd.union.open.coupon.query", param)
        try:
            result = resp.get("jd_union_open_coupon_query_responce", {})
            data = json.loads(result.get("queryResult", "{}"))
            items = data.get("data", [])
            return [
                Coupon(
                    platform=self.platform,
                    coupon_id=str(c.get("couponId", "")),
                    title=c.get("couponName", ""),
                    discount=float(c.get("discount", 0)),
                    min_spend=float(c.get("quota", 0)),
                    url=c.get("link", ""),
                )
                for c in items
            ]
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("京东优惠券解析失败: %s", e)
            return []
