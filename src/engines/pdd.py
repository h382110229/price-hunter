"""多多进宝 (PDD Open Platform) 引擎。

API 文档: https://open.pinduoduo.com/application/document/api
签名方式: MD5(secret + sorted_kv + secret).upper()

已知接口状态 (2026-08):
- pdd.ddk.goods.search      → 已下线
- pdd.ddk.goods.detail      → 已下线 (需用 goods_sign)
- pdd.ddk.goods.recommend.get → 免费，不需要用户授权 ✅

关键注意:
- pid 和 channel_type 参数会触发"授权备案"检查，在未完成备案前不可传
- 价格单位: 分 (÷100 = 元)
- 佣金比例: 千分比 (÷10 = 百分比)
- goods_id 已下线，统一使用 goods_sign
"""

from __future__ import annotations

import json
import logging
import time

from src.config import settings as _cfg
from src.engines.base import (
    ApiBusinessError,
    BaseEngine,
    _mock_coupons,
    _mock_products,
)
from src.models import Coupon, Platform, Product

logger = logging.getLogger(__name__)

_PDD_SIGN_ERRORS = {10019, 10020}
_PDD_AUTH_ERRORS = {10001, 10002}


class PDDEngine(BaseEngine):
    """多多进宝搜索引擎

    使用 pdd.ddk.goods.recommend.get 接口获取商品 (免费，不需要用户授权)。
    默认返回 channel_type=5 (实时热销榜)。
    """

    platform = Platform.PDD
    base_url = "https://gw-api.pinduoduo.com/api/router"

    def __init__(self) -> None:
        super().__init__(_cfg.pdd_client_id, _cfg.pdd_client_secret)
        self.pid = _cfg.pdd_pid

    def _sign(self, params: dict[str, str]) -> str:
        from src.engines.base import pdd_sign
        return pdd_sign(params, self.app_secret)

    async def _pdd_request(self, api_type: str, biz_params: dict) -> dict:
        """发送 PDD API 请求。

        所有参数统一转字符串后签名和发送。
        数组类型参数需要调用方先 json.dumps() 再传入。
        """
        params: dict = {
            "type": api_type,
            "client_id": self.app_key,
            "timestamp": str(int(time.time())),
            "data_type": "JSON",
        }
        params.update({k: str(v) for k, v in biz_params.items()})
        params["sign"] = self._sign(params)
        resp = await self._request("POST", self.base_url, json_body=params)
        self._check_business_error(resp)
        return resp

    def _check_business_error(self, resp: dict) -> None:
        """检查 PDD 业务级错误。error_response 仅在错误时出现。"""
        if "error_response" not in resp:
            return
        err = resp["error_response"]
        code = err.get("error_code", 0)
        msg = err.get("error_msg", "")
        sub_msg = err.get("sub_msg", "")

        if code in _PDD_SIGN_ERRORS:
            logger.error("🔴 拼多多签名错误 [%s]: %s — 请检查 PDD_CLIENT_SECRET", code, msg)
            raise ApiBusinessError(
                f"拼多多签名错误 [{code}]: {msg}", platform=self.platform, error_code=str(code),
            )
        if code in _PDD_AUTH_ERRORS:
            logger.error("🔴 拼多多鉴权失败 [%s]: %s — 请检查 PDD_CLIENT_ID", code, msg)
            raise ApiBusinessError(
                f"拼多多鉴权失败 [{code}]: {msg}", platform=self.platform, error_code=str(code),
            )
        if code == 10016:
            logger.warning("🟡 拼多多限流 [%s]: %s", code, msg)
            raise ApiBusinessError(
                f"拼多多限流 [{code}]: {msg}", platform=self.platform, error_code=str(code),
            )
        logger.warning("拼多多业务错误 [%s]: %s — %s", code, msg, sub_msg)
        raise ApiBusinessError(
            f"拼多多错误 [{code}]: {msg}", platform=self.platform, error_code=str(code),
        )

    def _parse_recommend_item(self, item: dict) -> Product:
        """解析 recommend.get 返回的商品数据。

        单位转换 (对照 API 文档):
        - min_group_price: 分 → 元 (÷100)
        - min_normal_price: 分 → 元 (÷100)
        - coupon_discount: 分 → 元 (÷100)
        - extra_coupon_amount: 分 → 元 (÷100)
        - coupon_min_order_amount: 分 → 元 (÷100)
        - promotion_rate: 千分比 → 百分比 (÷10)
        """
        # 价格
        min_group_price = float(item.get("min_group_price", 0))
        price = min_group_price / 100.0

        # 优惠券 (extra_coupon_amount 可能与 coupon_discount 重叠，不累加)
        coupon_discount = float(item.get("coupon_discount", 0))
        coupon_amount = coupon_discount / 100.0

        final_price = max(0.0, price - coupon_amount)

        # 佣金
        promotion_rate = float(item.get("promotion_rate", 0))
        commission_rate = promotion_rate / 10.0  # 千分比 → 百分比

        # 商品标识 (goods_id 已下线，统一用 goods_sign)
        goods_id = str(item.get("goods_id", ""))
        goods_sign = item.get("goods_sign", "")
        product_id = goods_sign or goods_id
        detail_url = f"https://mobile.yangkeduo.com/goods.html?goods_id={goods_id}"

        # 销量 (字符串类型，如 "1.2万")
        sales = item.get("sales_tip", item.get("realtime_sales_tip", "0"))
        try:
            sales_str = str(sales).replace("+", "").replace("万", "0000")
            sales_int = int(float(sales_str))
        except (ValueError, TypeError):
            sales_int = 0

        # 优惠券对象
        coupons = []
        if coupon_amount > 0:
            coupon_start = float(item.get("coupon_min_order_amount", 0)) / 100.0
            coupons.append(Coupon(
                platform=self.platform,
                coupon_id=goods_sign,
                title=f"满{coupon_start:.0f}减{coupon_amount:.0f}",
                discount=coupon_amount,
                min_spend=coupon_start,
            ))

        return Product(
            platform=self.platform,
            product_id=product_id,
            title=item.get("goods_name", ""),
            price=price,
            coupon_amount=coupon_amount,
            final_price=final_price,
            original_price=float(item.get("min_normal_price", 0)) / 100.0,
            url=detail_url,
            coupon_url="",
            image_url=item.get("goods_image_url", ""),
            detail_url=detail_url,
            shop_name=item.get("mall_name", ""),
            sales_volume=sales_int,
            commission_rate=commission_rate,
            coupons=coupons,
        )

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """获取推荐商品。

        PDD 已下线 goods.search 接口，使用 recommend.get 替代。
        默认返回 channel_type=5 (实时热销榜)。
        keyword 参数当前无法直接用于搜索 (API 限制)。
        """
        if self.dry_run:
            return _mock_products(keyword, self.platform, page_size)

        offset = (page - 1) * page_size
        # 不传 pid 和 channel_type — 都会触发授权备案检查
        resp = await self._pdd_request("pdd.ddk.goods.recommend.get", {
            "offset": offset,
            "limit": page_size,
        })
        try:
            result = resp.get("goods_basic_detail_response", {})
            items = result.get("list", [])
            return [self._parse_recommend_item(item) for item in items]
        except (KeyError, TypeError) as e:
            logger.warning("拼多多推荐解析失败: %s", e)
            return []

    async def detail(self, product_id: str) -> Product:
        """获取商品详情 (通过 goods_sign 相似商品推荐)。

        product_id 应为 goods_sign (非 goods_id)。
        """
        if self.dry_run:
            products = _mock_products("detail", self.platform, 1)
            p = products[0]
            p.product_id = product_id
            return p

        # goods_sign_list 需要传 JSON 字符串形式的数组
        resp = await self._pdd_request("pdd.ddk.goods.recommend.get", {
            "goods_sign_list": json.dumps([product_id]),
            "limit": 1,
        })
        try:
            result = resp.get("goods_basic_detail_response", {})
            items = result.get("list", [])
            if items:
                return self._parse_recommend_item(items[0])
            raise ValueError(f"商品 {product_id} 未找到 (goods_sign)")
        except (KeyError, TypeError) as e:
            logger.warning("拼多多详情解析失败: %s", e)
            raise

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """获取推荐商品的优惠券 (从 search 结果中提取)"""
        if self.dry_run:
            return _mock_coupons(keyword, self.platform)

        products = await self.search(keyword, page, page_size=20)
        return [c for p in products for c in p.coupons]
