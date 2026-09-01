"""淘宝联盟 (Taobao客 TOP API) 引擎。

API 文档: https://open.taobao.com/api.htm?docId=28541&docType=2
网关地址: https://eco.taobao.com/router/rest
签名方式: MD5(secret + sorted_kv + secret).upper()

公共参数:
- method: 接口名称
- app_key: 开发者 AppKey
- timestamp: YYYY-MM-DD HH:MM:SS (北京时间)
- format: json
- v: 2.0
- sign_method: md5

业务参数 (material.optional):
- adzone_id: 推广位 ID
- q: 搜索关键词
- page_no / page_size: 分页
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone, timedelta

import src.config as _cfg
from src.engines.base import (
    ApiBusinessError,
    BaseEngine,
    _mock_coupons,
    _mock_products,
)
from src.models import Coupon, Platform, Product

logger = logging.getLogger(__name__)

_CST = timezone(timedelta(hours=8))

# 淘宝 TOP API 已知业务错误码
_TB_SIGN_ERRORS = {"Invalid Sign", "Invalid Signature"}
_TB_AUTH_ERRORS = {"Invalid AppKey", "Unauthorized", "Invalid Session"}
_TB_RATE_LIMIT = {"流量限制", "Fail Flow Limit", "THIRDPART_TRAFFIC_LIMIT"}


def taobao_sign(params: dict[str, str], secret: str) -> str:
    """淘宝 TOP API 签名算法。

    1. 剔除 sign 字段
    2. 所有参数按 Key 的 ASCII 码升序排序
    3. 拼接: secret + key1value1key2value2... + secret
    4. MD5 → 大写 32 位十六进制
    """
    filtered = {k: v for k, v in params.items() if k != "sign"}
    sorted_params = sorted(filtered.items())
    sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


class TaobaoEngine(BaseEngine):
    """淘宝联盟搜索引擎

    使用 taobao.tbk.dg.material.optional 接口搜索商品。
    """

    platform = Platform.TAOBAO
    base_url = "https://eco.taobao.com/router/rest"

    def __init__(self) -> None:
        super().__init__(_cfg.settings.tb_app_key, _cfg.settings.tb_app_secret)
        self.adzone_id = _cfg.settings.tb_adzone_id

    def _sign(self, params: dict[str, str]) -> str:
        return taobao_sign(params, self.app_secret)

    def _common_params(self, method: str) -> dict[str, str]:
        return {
            "method": method,
            "app_key": self.app_key,
            "timestamp": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "2.0",
            "sign_method": "md5",
        }

    async def _top_request(self, method: str, biz_params: dict[str, str]) -> dict:
        """发送 TOP API 请求 (带业务错误检查)"""
        params = self._common_params(method)
        params.update(biz_params)
        params["sign"] = self._sign(params)
        resp = await self._request("POST", self.base_url, params=params)
        self._check_business_error(resp)
        return resp

    def _check_business_error(self, resp: dict) -> None:
        if "error_response" not in resp:
            return
        err = resp["error_response"]
        code = str(err.get("code", ""))
        sub_code = str(err.get("sub_code", ""))
        msg = err.get("msg", "") or err.get("sub_msg", "")

        if sub_code in _TB_SIGN_ERRORS or "sign" in sub_code.lower():
            logger.error("🔴 淘宝签名错误: %s — 请检查 TB_APP_SECRET", sub_code)
            raise ApiBusinessError(
                f"淘宝签名错误: {sub_code} — {msg}",
                platform=self.platform, error_code=code, sub_code=sub_code,
            )
        if sub_code in _TB_AUTH_ERRORS:
            logger.error("🔴 淘宝鉴权失败: %s — 请检查 TB_APP_KEY/SECRET", sub_code)
            raise ApiBusinessError(
                f"淘宝鉴权失败: {sub_code} — {msg}",
                platform=self.platform, error_code=code, sub_code=sub_code,
            )
        if sub_code in _TB_RATE_LIMIT:
            logger.warning("🟡 淘宝限流: %s — 稍后重试", sub_code)
            raise ApiBusinessError(
                f"淘宝限流: {sub_code} — {msg}",
                platform=self.platform, error_code=code, sub_code=sub_code,
            )
        logger.warning("淘宝业务错误 [%s/%s]: %s", code, sub_code, msg)
        raise ApiBusinessError(
            f"淘宝错误 [{code}/{sub_code}]: {msg}",
            platform=self.platform, error_code=code, sub_code=sub_code,
        )

    def _parse_product(self, item: dict) -> Product:
        """解析淘宝商品数据。

        字段映射 (对照 API 文档):
        - title: 商品标题
        - zk_final_price: 一口价/券前价
        - coupon_amount: 优惠券面额 (元)
        - coupon_start_fee: 券使用门槛
        - coupon_click_url: 领券链接
        - volume: 30天销量
        - click_url / url: 推广链接
        - pict_url: 主图
        - shop_title: 店铺名
        - commission_rate: 佣金比例 (%)
        """
        # 价格
        price = float(item.get("zk_final_price", 0) or item.get("reserve_price", 0))

        # 优惠券
        coupon_amount = float(item.get("coupon_amount", 0) or 0)
        final_price = max(0.0, price - coupon_amount)

        # 推广链接
        click_url = item.get("click_url", item.get("url", ""))

        # 销量
        volume = int(item.get("volume", item.get("tk_total_sales", 0)) or 0)

        coupons = []
        if coupon_amount > 0:
            coupons.append(Coupon(
                platform=self.platform,
                coupon_id=str(item.get("coupon_id", "")),
                title=item.get("coupon_info", f"满减{coupon_amount}元"),
                discount=coupon_amount,
                min_spend=float(item.get("coupon_start_fee", price) or price),
                url=item.get("coupon_click_url", item.get("coupon_share_url", "")),
            ))

        return Product(
            platform=self.platform,
            product_id=str(item.get("num_iid", item.get("item_id", ""))),
            title=item.get("title", ""),
            price=price,
            coupon_amount=coupon_amount,
            final_price=final_price,
            original_price=float(item.get("reserve_price", 0) or 0),
            url=click_url,
            coupon_url=item.get("coupon_share_url", item.get("coupon_click_url", "")),
            tkl_or_command=item.get("tkl", ""),
            image_url=item.get("pict_url", ""),
            detail_url=item.get("item_url", ""),
            shop_name=item.get("shop_title", item.get("nick", "")),
            sales_volume=volume,
            commission_rate=float(item.get("commission_rate", 0) or 0),
            coupons=coupons,
        )

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """商品搜索 (taobao.tbk.dg.material.optional)"""
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
            logger.warning("淘宝搜索解析失败: %s", e)
            return []

    async def detail(self, product_id: str) -> Product:
        """商品详情 (taobao.tbk.item.info.get)"""
        if self.dry_run:
            products = _mock_products("detail", self.platform, 1)
            p = products[0]
            p.product_id = product_id
            return p

        resp = await self._top_request("taobao.tbk.item.info.get", {"num_iids": product_id})
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
        """优惠券查询 (taobao.tbk.coupon.get)"""
        if self.dry_run:
            return _mock_coupons(keyword, self.platform)

        resp = await self._top_request(
            "taobao.tbk.coupon.get",
            {"adzone_id": self.adzone_id, "search": keyword, "page_no": str(page), "page_size": "20"},
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
