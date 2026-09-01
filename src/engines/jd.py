"""京东联盟 (JD Union Open Platform) 引擎。

API 文档: https://union.jd.com/openplatform/api
网关地址: https://api.jd.com/routerjson
签名方式: MD5(secret + sorted_kv + secret).upper()

公共系统参数:
- method: 接口名称
- app_key: 开发者 AppKey
- timestamp: YYYY-MM-DD HH:MM:SS (北京时间)
- format: json
- v: 1.0
- sign_method: md5
- param_json: 业务参数 JSON 字符串 (紧凑无空格)

业务错误码:
- code: 200=成功, 其他=失败
- message: 错误描述 (含 "sign" 关键词表示签名错误)
"""

from __future__ import annotations

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

# 北京时间 UTC+8
_CST = timezone(timedelta(hours=8))


def jd_sign(params: dict[str, str], secret: str) -> str:
    """京东联盟签名算法。

    1. 将所有参数按 Key 的 ASCII 码升序排序
    2. 拼接: app_secret + key1value1key2value2... + app_secret
    3. MD5 → 大写 32 位十六进制
    """
    from src.engines.base import md5_sign
    return md5_sign(params, secret)


class JDEngine(BaseEngine):
    """京东联盟搜索引擎

    支持接口:
    - jd.union.open.goods.query: 商品检索
    - jd.union.open.promotion.common.get: 转链直达链接
    """

    platform = Platform.JD
    base_url = "https://api.jd.com/routerjson"

    def __init__(self) -> None:
        super().__init__(_cfg.settings.jd_app_key, _cfg.settings.jd_app_secret)
        self.site_id = _cfg.settings.jd_site_id

    def _sign(self, params: dict[str, str]) -> str:
        return jd_sign(params, self.app_secret)

    def _common_params(self, method: str) -> dict[str, str]:
        """公共系统参数 (对照 API 文档)"""
        return {
            "method": method,
            "app_key": self.app_key,
            "timestamp": datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S"),
            "format": "json",
            "v": "1.0",
            "sign_method": "md5",
        }

    async def _jd_request(self, method: str, biz_params: dict) -> dict:
        """发送京东联盟 API 请求。

        流程:
        1. 构造公共系统参数
        2. 将业务参数序列化为 param_json (紧凑 JSON)
        3. 签名: 对所有参数 (含 param_json) 计算 MD5
        4. POST 发送 (form-encoded body)
        """
        params = self._common_params(method)
        # param_json: 业务参数的 JSON 字符串 (紧凑无空格)
        params["param_json"] = json.dumps(biz_params, separators=(",", ":"))
        params["sign"] = self._sign(params)
        # 发送 POST 请求 (form-encoded body)
        resp = await self._request("POST", self.base_url, params=params)
        self._check_business_error(resp, method)
        return resp

    def _check_business_error(self, resp: dict, method: str) -> None:
        """检查京东联盟业务级错误。

        响应结构: {method}_responce → {code, message, result/queryResult}
        京东外层 code: "0" 或 200 均表示调用成功。
        """
        resp_key = method.replace(".", "_") + "_responce"
        wrapper = resp.get(resp_key, resp)

        code = wrapper.get("code", 200)
        # JD 返回 code="0"(字符串) 或 200(整数) 均为成功
        if str(code) in ("0", "200"):
            # 检查内层 result/queryResult
            try:
                inner_str = wrapper.get("queryResult", wrapper.get("result", "{}"))
                inner = json.loads(inner_str) if isinstance(inner_str, str) else inner_str
                result_code = inner.get("code", 200)
                if str(result_code) not in ("0", "200"):
                    msg = inner.get("message", "")
                    self._classify_jd_error(str(result_code), msg)
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
            return

        msg = wrapper.get("message", "")
        self._classify_jd_error(str(code), msg)

    def _classify_jd_error(self, code: str, msg: str) -> None:
        """分类京东错误码"""
        msg_lower = msg.lower()
        if "sign" in msg_lower or code in ("3", "11"):
            logger.error("🔴 京东签名错误 [%s]: %s — 请检查 JD_APP_SECRET", code, msg)
            raise ApiBusinessError(
                f"京东签名错误 [{code}]: {msg}",
                platform=self.platform, error_code=code,
            )
        if "auth" in msg_lower or "unauthorized" in msg_lower or code in ("12", "13"):
            logger.error("🔴 京东鉴权失败 [%s]: %s — 请检查 JD_APP_KEY", code, msg)
            raise ApiBusinessError(
                f"京东鉴权失败 [{code}]: {msg}",
                platform=self.platform, error_code=code,
            )
        if "limit" in msg_lower or "rate" in msg_lower or code == "28":
            logger.warning("🟡 京东限流 [%s]: %s", code, msg)
            raise ApiBusinessError(
                f"京东限流 [{code}]: {msg}",
                platform=self.platform, error_code=code,
            )
        logger.warning("京东业务错误 [%s]: %s", code, msg)
        raise ApiBusinessError(
            f"京东错误 [{code}]: {msg}",
            platform=self.platform, error_code=code,
        )

    def _parse_product(self, item: dict) -> Product:
        """解析京东商品数据。

        字段映射 (对照 API 文档):
        - priceInfo.price: 面价
        - couponInfo.couponList: 优惠券列表
        - promotionInfo.clickURL: 推广链接
        - shopInfo.shopName: 店铺名
        - inOrderCount30Days: 30天引单数 (销量)
        - commissionInfo.commissionShare: 佣金比例 (%)
        """
        price_info = item.get("priceInfo", {})
        price = float(price_info.get("price", 0))

        # 提取最优优惠券 (最大面额)
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

        # 销量 (30天引单数)
        in_order_count = item.get("inOrderCount30Days", item.get("inOrderCount30DaysSku", 0))

        # 图片
        image_list = item.get("imageInfo", {}).get("imageList", [])
        image_url = image_list[0].get("url", "") if image_list else ""

        # 佣金
        commission_info = item.get("commissionInfo", {})
        commission_rate = float(commission_info.get("commissionShare", 0) or 0)

        coupons = []
        if best_discount > 0:
            coupons.append(Coupon(
                platform=self.platform,
                coupon_id=coupon_id,
                title=f"满{min_spend:.0f}减{best_discount:.0f}",
                discount=best_discount,
                min_spend=min_spend,
                url=coupon_url,
            ))

        return Product(
            platform=self.platform,
            product_id=str(item.get("skuId", "")),
            title=item.get("skuName", ""),
            price=price,
            coupon_amount=best_discount,
            final_price=final_price,
            original_price=price,
            url=click_url,
            coupon_url=coupon_url,
            image_url=image_url,
            detail_url=f"https://item.jd.com/{item.get('skuId', '')}.html",
            shop_name=shop_info.get("shopName", ""),
            sales_volume=int(in_order_count) if in_order_count else 0,
            commission_rate=commission_rate,
            coupons=coupons,
        )

    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        """商品检索 (jd.union.open.goods.query)

        param_json 结构: {"goodsReqDTO": {"keyword": ..., "pageIndex": ..., "pageSize": ...}}
        """
        if self.dry_run:
            return _mock_products(keyword, self.platform, page_size)

        biz_params = {
            "goodsReqDTO": {
                "keyword": keyword,
                "pageIndex": page,
                "pageSize": page_size,
            }
        }
        resp = await self._jd_request("jd.union.open.goods.query", biz_params)
        try:
            result = resp.get("jd_union_open_goods_query_responce", {})
            data = json.loads(result.get("queryResult", "{}"))
            items = data.get("data", [])
            return [self._parse_product(item) for item in items]
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("京东搜索解析失败: %s", e)
            return []

    async def detail(self, product_id: str) -> Product:
        """商品详情 (jd.union.open.goods.promotiongoodsinfo.query)"""
        if self.dry_run:
            products = _mock_products("detail", self.platform, 1)
            p = products[0]
            p.product_id = product_id
            return p

        biz_params = {"skuIds": product_id}
        resp = await self._jd_request(
            "jd.union.open.goods.promotiongoodsinfo.query", biz_params
        )
        try:
            result = resp.get(
                "jd_union_open_goods_promotiongoodsinfo_query_responce", {}
            )
            data = json.loads(result.get("queryResult", "{}"))
            items = data.get("data", [])
            if items:
                return self._parse_product(items[0])
            raise ValueError(f"商品 {product_id} 未找到")
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("京东详情解析失败: %s", e)
            raise

    async def get_promotion_url(self, material_url: str) -> str:
        """转链直达链接 (jd.union.open.promotion.common.get)

        Args:
            material_url: 商品链接或 SKU 页面 URL

        Returns:
            推广短链 (clickURL)，失败返回空字符串
        """
        if self.dry_run:
            return f"https://u.jd.com/MOCK{hash(material_url) % 100000}"

        biz_params = {
            "promotionCodeReq": {
                "materialElUrl": material_url,
                "siteId": self.site_id,
            }
        }
        resp = await self._jd_request(
            "jd.union.open.promotion.common.get", biz_params
        )
        try:
            result = resp.get("jd_union_open_promotion_common_get_responce", {})
            data = json.loads(result.get("getResult", "{}"))
            return data.get("data", {}).get("clickURL", "")
        except (KeyError, TypeError, json.JSONDecodeError) as e:
            logger.warning("京东转链失败: %s", e)
            return ""

    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        """优惠券查询 (jd.union.open.coupon.query)"""
        if self.dry_run:
            return _mock_coupons(keyword, self.platform)

        biz_params = {"couponUrls": [], "pageIndex": page, "pageSize": 20}
        resp = await self._jd_request("jd.union.open.coupon.query", biz_params)
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
