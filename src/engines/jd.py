"""京东联盟 (JD Union Open Platform) 引擎。

API 文档: https://union.jd.com/openplatform/api
网关地址: https://api.jd.com/routerjson
签名方式: MD5(secret + sorted_kv + secret).upper()

当前使用接口:
- jd.union.open.goods.jingfen.query: 京粉精选 (基础账号可用)
- jd.union.open.goods.promotiongoodsinfo.query: 单品详情 (需V1)
- jd.union.open.promotion.common.get: 转链

客户端关键词过滤: 从精选池中匹配标题，不足时补充热门商品。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
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
_MIN_KEYWORD_MATCHES = 3
_OVERFETCH_MULTIPLIER = 3


class JDPermissionDenied(ApiBusinessError):
    """京东 API 权限不足 (403)"""
    pass


def jd_sign(params: dict[str, str], secret: str) -> str:
    """京东联盟签名: MD5(secret + sorted_kv + secret).upper()

    注意: SDK 使用 latin1 编码 (不是 utf-8)。
    """
    sorted_params = sorted(params.items())
    sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hashlib.md5(sign_str.encode("latin1")).hexdigest().upper()


def _keyword_match_score(title: str, keyword: str) -> float:
    """计算标题与关键词匹配分数。"""
    if not keyword:
        return 1.0
    title_lower = title.lower()
    kw_lower = keyword.lower()
    if kw_lower in title_lower:
        return 1.0
    tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", keyword)
    if not tokens:
        return 1.0
    matched = sum(1 for t in tokens if t.lower() in title_lower)
    score = matched / len(tokens)
    return score if score >= 0.3 else 0.0


class JDEngine(BaseEngine):
    """京东联盟搜索引擎

    使用 jd.union.open.goods.jingfen.query 获取精选商品。
    支持客户端关键词过滤。
    """

    platform = Platform.JD
    base_url = "https://api.jd.com/routerjson"  # SDK 用 gw.api.360buy.com 但 SSL 证书不匹配

    def __init__(self) -> None:
        super().__init__(_cfg.settings.jd_app_key, _cfg.settings.jd_app_secret)
        self.site_id = _cfg.settings.jd_site_id

    def _sign(self, params: dict[str, str]) -> str:
        return jd_sign(params, self.app_secret)

    def _common_params(self, method: str) -> dict[str, str]:
        return {
            "method": method,
            "app_key": self.app_key,
            "timestamp": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S.000+0800"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
        }

    async def _jd_request(self, method: str, biz_params: dict) -> dict:
        params = self._common_params(method)
        # SDK 使用 360buy_param_json 作为业务参数 key (不是 param_json)
        params["360buy_param_json"] = json.dumps(biz_params, separators=(",", ":"))
        params["sign"] = self._sign(params)
        resp = await self._request("POST", self.base_url, params=params)
        self._check_business_error(resp, method)
        return resp

    def _check_business_error(self, resp: dict, method: str) -> None:
        resp_key = method.replace(".", "_") + "_responce"
        wrapper = resp.get(resp_key, resp)
        code = wrapper.get("code", 200)
        if str(code) in ("0", "200"):
            try:
                inner_str = wrapper.get("queryResult", wrapper.get("result", "{}"))
                inner = json.loads(inner_str) if isinstance(inner_str, str) else inner_str
                result_code = inner.get("code", 200)
                if str(result_code) not in ("0", "200"):
                    msg = inner.get("message", "")
                    if str(result_code) == "403":
                        logger.warning("🟡 JD API 权限受限 [%s]: %s", result_code, msg)
                        raise JDPermissionDenied(
                            f"京东权限不足 [{result_code}]: {msg}",
                            platform=self.platform, error_code=str(result_code),
                        )
                    self._classify_jd_error(str(result_code), msg)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            return
        msg = wrapper.get("message", "")
        self._classify_jd_error(str(code), msg)

    def _classify_jd_error(self, code: str, msg: str) -> None:
        msg_lower = msg.lower()
        if "sign" in msg_lower or code in ("3", "11"):
            logger.error("🔴 京东签名错误 [%s]: %s", code, msg)
            raise ApiBusinessError(f"京东签名错误 [{code}]: {msg}", platform=self.platform, error_code=code)
        if "auth" in msg_lower or "unauthorized" in msg_lower or code in ("12", "13"):
            logger.error("🔴 京东鉴权失败 [%s]: %s", code, msg)
            raise ApiBusinessError(f"京东鉴权失败 [{code}]: {msg}", platform=self.platform, error_code=code)
        if "limit" in msg_lower or "rate" in msg_lower or code == "28":
            logger.warning("🟡 京东限流 [%s]: %s", code, msg)
            raise ApiBusinessError(f"京东限流 [{code}]: {msg}", platform=self.platform, error_code=code)
        logger.warning("京东业务错误 [%s]: %s", code, msg)
        raise ApiBusinessError(f"京东错误 [{code}]: {msg}", platform=self.platform, error_code=code)

    def _parse_product(self, item: dict) -> Product:
        price_info = item.get("priceInfo", {})
        price = float(price_info.get("price", 0))

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
        promotion_info = item.get("promotionInfo", {})
        click_url = promotion_info.get("clickURL", "")
        shop_info = item.get("shopInfo", {})
        in_order_count = item.get("inOrderCount30Days", item.get("inOrderCount30DaysSku", 0))
        image_list = item.get("imageInfo", {}).get("imageList", [])
        image_url = image_list[0].get("url", "") if image_list else ""
        commission_info = item.get("commissionInfo", {})
        commission_rate = float(commission_info.get("commissionShare", 0) or 0)

        coupons = []
        if best_discount > 0:
            coupons.append(Coupon(
                platform=self.platform, coupon_id=coupon_id,
                title=f"满{min_spend:.0f}减{best_discount:.0f}",
                discount=best_discount, min_spend=min_spend, url=coupon_url,
            ))

        return Product(
            platform=self.platform,
            product_id=str(item.get("skuId", "")),
            title=item.get("skuName", ""),
            price=price, coupon_amount=best_discount, final_price=final_price,
            original_price=price, url=click_url, coupon_url=coupon_url,
            image_url=image_url,
            detail_url=f"https://item.jd.com/{item.get('skuId', '')}.html",
            shop_name=shop_info.get("shopName", ""),
            sales_volume=int(in_order_count) if in_order_count else 0,
            commission_rate=commission_rate, coupons=coupons,
        )

    def _filter_by_keyword(self, products: list[Product], keyword: str) -> list[Product]:
        if not keyword:
            return products
        scored = [(p, _keyword_match_score(p.title, keyword)) for p in products]
        matched = [p for p, score in scored if score > 0]
        matched.sort(key=lambda p: _keyword_match_score(p.title, keyword), reverse=True)
        # 只返回真正匹配的商品，不回填无关热销品
        return matched

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """京粉精选商品搜索 (jd.union.open.goods.jingfen.query)

        尝试多个 eliteId 池以扩大覆盖面:
        - 1: 好券商品
        - 22: 实时热销榜
        - 24: 数码家电
        客户端关键词过滤: 从合并池中匹配标题。
        """
        if self.dry_run:
            return _mock_products(keyword, self.platform, page_size)

        # 多个精英池并发请求
        elite_ids = [1, 22, 24]
        fetch_size = min(page_size * _OVERFETCH_MULTIPLIER, 50)

        async def _fetch_pool(elite_id: int) -> list[Product]:
            biz_params = {
                "goodsReq": {
                    "eliteId": elite_id,
                    "pageIndex": page,
                    "pageSize": fetch_size,
                    "sortName": "price",
                    "sort": "asc",
                }
            }
            try:
                resp = await self._jd_request("jd.union.open.goods.jingfen.query", biz_params)
                result = resp.get("jd_union_open_goods_jingfen_query_responce", {})
                data = json.loads(result.get("queryResult", "{}"))
                items = data.get("data", [])
                return [self._parse_product(item) for item in items]
            except JDPermissionDenied:
                return []
            except ApiBusinessError as e:
                logger.warning("🟡 JD jingfen.query eliteId=%d 失败: %s", elite_id, e)
                return []

        import asyncio
        pools = await asyncio.gather(*[_fetch_pool(eid) for eid in elite_ids])
        all_products = [p for pool in pools for p in pool]

        # 客户端关键词过滤
        filtered = self._filter_by_keyword(all_products, keyword)
        return filtered[:page_size]

    async def detail(self, product_id: str) -> Product:
        if self.dry_run:
            products = _mock_products("detail", self.platform, 1)
            p = products[0]
            p.product_id = product_id
            return p

        biz_params = {"skuIds": product_id}
        try:
            resp = await self._jd_request(
                "jd.union.open.goods.promotiongoodsinfo.query", biz_params
            )
        except JDPermissionDenied:
            raise ValueError(f"商品 {product_id} 查询受限 (V0 权限)")
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

    async def get_promotion_url(self, material_url: str) -> str:
        if self.dry_run:
            return f"https://u.jd.com/MOCK{hash(material_url) % 100000}"

        biz_params = {"promotionCodeReq": {"materialElUrl": material_url, "siteId": self.site_id}}
        try:
            resp = await self._jd_request("jd.union.open.promotion.common.get", biz_params)
        except (JDPermissionDenied, ApiBusinessError):
            return ""
        try:
            result = resp.get("jd_union_open_promotion_common_get_responce", {})
            data = json.loads(result.get("getResult", "{}"))
            return data.get("data", {}).get("clickURL", "")
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("京东转链失败: %s", e)
            return ""

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        if self.dry_run:
            return _mock_coupons(keyword, self.platform)
        products = await self.search(keyword, page, page_size=20)
        return [c for p in products for c in p.coupons]
