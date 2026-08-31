"""多多进宝 (PDD Open Platform) 引擎。

API 文档: https://open.pinduoduo.com/application/document/api
签名方式: MD5(secret + sorted_kv + secret).upper()
接口: pdd.ddk.goods.search (商品搜索)
"""

from __future__ import annotations

import json
import logging
import time

from src.config import settings
from src.engines.base import BaseEngine, _mock_coupons, _mock_products
from src.models import Coupon, Platform, Product

logger = logging.getLogger(__name__)


class PDDEngine(BaseEngine):
    """多多进宝搜索引擎"""

    platform = Platform.PDD
    base_url = "https://gw-api.pinduoduo.com/api/router"

    def __init__(self) -> None:
        cfg = settings.pdd
        super().__init__(cfg.client_id, cfg.client_secret)
        self.pid = cfg.pid

    def _sign(self, params: dict[str, str]) -> str:
        from src.engines.base import pdd_sign

        return pdd_sign(params, self.app_secret)

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

    def _parse_product(self, item: dict) -> Product:
        """解析拼多多 API 返回的商品数据。

        关键字段映射:
        - item["min_group_price"]  → 拼单价 (分，需 /100)
        - item["coupon_discount"]  → 优惠券面额 (分)
        - item["promotion_rate"]   → 佣金比例 (‱ 万分比)
        - item["goods_image_url"]  → 主图
        - item["goods_name"]       → 商品名
        - item["sold_quantity"]    → 已拼件数
        """
        # PDD 价格单位: 分
        min_group_price = float(item.get("min_group_price", 0))
        price = min_group_price / 100.0

        coupon_discount = float(item.get("coupon_discount", 0))
        coupon_amount = coupon_discount / 100.0
        final_price = max(0.0, price - coupon_amount)

        # 佣金比例: 万分比 → 百分比
        promotion_rate = float(item.get("promotion_rate", 0))
        commission_rate = promotion_rate / 100.0

        # 推广链接
        search_id = item.get("search_id", "")
        goods_sign = item.get("goods_sign", "")
        detail_url = f"https://mobile.yangkeduo.com/goods.html?goods_id={item.get('goods_id', '')}"

        # 已拼件数
        sold = item.get("sold_quantity", item.get("sold_num", 0))

        coupons = []
        if coupon_amount > 0:
            coupon_start = float(item.get("coupon_min_order_amount", 0)) / 100.0
            coupons.append(
                Coupon(
                    platform=self.platform,
                    coupon_id=str(item.get("coupon_id", "")),
                    title=f"满{coupon_start:.0f}减{coupon_amount:.0f}",
                    discount=coupon_amount,
                    min_spend=coupon_start,
                    url=item.get("coupon_url", ""),
                )
            )

        return Product(
            platform=self.platform,
            product_id=str(item.get("goods_id", "")),
            title=item.get("goods_name", ""),
            price=price,
            coupon_amount=coupon_amount,
            final_price=final_price,
            original_price=price,
            url=item.get("goods_detail_url", detail_url),
            coupon_url=item.get("coupon_url", ""),
            image_url=item.get("goods_image_url", ""),
            detail_url=detail_url,
            shop_name=item.get("mall_name", ""),
            sales_volume=int(sold) if sold else 0,
            commission_rate=commission_rate,
            coupons=coupons,
        )

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """搜索多多进宝商品 (pdd.ddk.goods.search)"""
        if self.dry_run:
            return _mock_products(keyword, self.platform, page_size)

        resp = await self._pdd_request(
            "pdd.ddk.goods.search",
            {
                "keyword": keyword,
                "page": page,
                "page_size": page_size,
                "pid": self.pid,
                "sort_type": 6,  # 按价格升序
            },
        )
        try:
            result = resp.get("goods_search_response", {})
            items = result.get("goods_list", [])
            return [self._parse_product(item) for item in items]
        except (KeyError, TypeError) as e:
            logger.warning("拼多多搜索解析失败: %s, resp=%s", e, json.dumps(resp, ensure_ascii=False)[:500])
            return []

    async def detail(self, product_id: str) -> Product:
        """获取拼多多商品详情 (pdd.ddk.goods.detail)"""
        if self.dry_run:
            products = _mock_products("detail", self.platform, 1)
            p = products[0]
            p.product_id = product_id
            return p

        resp = await self._pdd_request(
            "pdd.ddk.goods.detail",
            {"goods_id_list": json.dumps([product_id]), "pid": self.pid},
        )
        try:
            result = resp.get("goods_detail_response", {})
            items = result.get("goods_details", [])
            if items:
                return self._parse_product(items[0])
            raise ValueError(f"商品 {product_id} 未找到")
        except (KeyError, TypeError) as e:
            logger.warning("拼多多详情解析失败: %s", e)
            raise

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """搜索拼多多优惠券 (pdd.ddk.goods.search 内置优惠券信息)"""
        if self.dry_run:
            return _mock_coupons(keyword, self.platform)

        # PDD 的优惠券信息嵌入在商品搜索结果中
        products = await self.search(keyword, page, page_size=20)
        coupons = []
        for p in products:
            coupons.extend(p.coupons)
        return coupons
