"""搜索引擎基类与签名抽象。

每个平台引擎需实现:
- _sign()       → 请求签名
- search()      → 商品搜索
- detail()      → 商品详情
- get_coupons() → 优惠券查询

当凭据未配置时，引擎自动降级为 Mock/Dry-run 模式，返回真实结构的模拟数据。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any

import httpx

from src.models import Coupon, Platform, Product

logger = logging.getLogger(__name__)


# ── 签名工具函数 (可独立使用 / 测试) ─────────────────────

def md5_sign(params: dict[str, str], secret: str) -> str:
    """通用 MD5 签名 (淘宝 TOP API / 京东联盟)。

    1. 参数按 key 字典序排序
    2. 拼接: secret + key1value1key2value2... + secret
    3. MD5 → 大写 32 位 hex
    """
    sorted_params = sorted(params.items())
    sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


def pdd_sign(params: dict[str, str], secret: str) -> str:
    """拼多多签名 — MD5(secret + sorted_kv + secret).upper()。

    PDD 官方签名算法与淘宝/京东一致，均为 MD5 拼接模式。
    """
    sorted_params = sorted(params.items())
    sign_str = secret + "".join(f"{k}{v}" for k, v in sorted_params) + secret
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest().upper()


# ── Mock 数据工厂 ─────────────────────────────────────────

_MOCK_KEYWORDS: dict[str, list[dict[str, Any]]] = {
    "耳机": [
        {"title": "【爆款】无线蓝牙耳机 降噪运动跑步超长续航", "price": 89.9, "coupon": 30.0, "shop": "数码旗舰店", "sales": 50000},
        {"title": "索尼 WH-1000XM5 头戴式降噪耳机", "price": 1999.0, "coupon": 200.0, "shop": "索尼官方旗舰店", "sales": 8000},
        {"title": "Apple AirPods Pro 2 无线降噪耳机", "price": 1599.0, "coupon": 100.0, "shop": "Apple 官方", "sales": 120000},
    ],
    "手机壳": [
        {"title": "iPhone 16 Pro Max 透明防摔手机壳", "price": 29.9, "coupon": 15.0, "shop": "壳膜工坊", "sales": 100000},
        {"title": "华为 Mate 70 硅胶超薄手机壳", "price": 39.9, "coupon": 20.0, "shop": "华为配件专营", "sales": 30000},
    ],
    "充电宝": [
        {"title": "20000mAh 大容量充电宝 22.5W 快充", "price": 79.9, "coupon": 25.0, "shop": "绿联数码", "sales": 80000},
        {"title": "小米移动电源 3 30000mAh", "price": 149.0, "coupon": 15.0, "shop": "小米官方", "sales": 45000},
    ],
}

_DEFAULT_MOCKS = [
    {"title": "通用好物推荐 实用超值精选", "price": 59.9, "coupon": 10.0, "shop": "综合旗舰店", "sales": 20000},
    {"title": "品质生活优选 高性价比好物", "price": 129.0, "coupon": 30.0, "shop": "品质生活馆", "sales": 15000},
    {"title": "网红爆款同款 热销TOP1", "price": 39.9, "coupon": 15.0, "shop": "潮流前线", "sales": 99000},
]


def _mock_products(keyword: str, platform: Platform, page_size: int = 5) -> list[Product]:
    """生成 Mock 商品列表，结构完全匹配真实 API 响应映射。"""
    templates = _MOCK_KEYWORDS.get(keyword, _DEFAULT_MOCKS)
    products = []
    now = datetime.now()
    for i, t in enumerate(templates[:page_size]):
        final = max(0.0, t["price"] - t["coupon"])
        pid = f"MOCK-{platform.value.upper()}-{int(now.timestamp())}-{i}"
        products.append(
            Product(
                platform=platform,
                product_id=pid,
                title=f"{t['title']}（{keyword}）",
                price=t["price"],
                coupon_amount=t["coupon"],
                final_price=final,
                original_price=t["price"] * 1.3,
                url=f"https://mock.{platform.value}.com/item/{pid}",
                coupon_url=f"https://mock.{platform.value}.com/coupon/{pid}",
                tkl_or_command=f"￥MOCK{i}￥" if platform == Platform.TAOBAO else "",
                image_url=f"https://mock.{platform.value}.com/img/{pid}.jpg",
                shop_name=t["shop"],
                sales_volume=t["sales"],
                commission_rate=round(5.0 + i * 2.5, 1),
                coupons=[
                    Coupon(
                        platform=platform,
                        coupon_id=f"CPN-{pid}",
                        title=f"满{t['price']:.0f}减{t['coupon']:.0f}",
                        discount=t["coupon"],
                        min_spend=t["price"],
                        end_time=now + timedelta(days=7),
                        url=f"https://mock.{platform.value}.com/coupon/{pid}",
                    )
                ],
            )
        )
    return products


def _mock_coupons(keyword: str, platform: Platform) -> list[Coupon]:
    """生成 Mock 优惠券列表。"""
    now = datetime.now()
    return [
        Coupon(
            platform=platform,
            coupon_id=f"MOCK-CPN-{platform.value}-{i}",
            title=f"满{50 + i * 30}减{10 + i * 10}",
            discount=float(10 + i * 10),
            min_spend=float(50 + i * 30),
            end_time=now + timedelta(days=14),
            url=f"https://mock.{platform.value}.com/coupon/{i}",
        )
        for i in range(3)
    ]


# ── 引擎基类 ──────────────────────────────────────────────

class BaseEngine(ABC):
    """联盟 API 引擎抽象基类

    - 配置了凭据 → 真实 API 调用
    - 未配置凭据 → Mock/Dry-run 模式，返回模拟数据
    """

    platform: Platform
    base_url: str
    dry_run: bool  # True = 未配置凭据，返回 Mock 数据

    def __init__(self, app_key: str, app_secret: str) -> None:
        self.app_key = app_key
        self.app_secret = app_secret
        self.dry_run = not app_key or not app_secret
        if self.dry_run:
            logger.info(
                "%s: 凭据未配置，启用 Mock/Dry-run 模式",
                self.__class__.__name__,
            )
        self._client = httpx.AsyncClient(timeout=15.0)

    async def close(self) -> None:
        await self._client.aclose()

    # ── 签名 (子类选择算法) ────────────────────────────────

    @abstractmethod
    def _sign(self, params: dict[str, str]) -> str:
        ...

    # ── 通用 HTTP ─────────────────────────────────────────

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        resp = await self._client.request(
            method, url, params=params, json=json_body
        )
        resp.raise_for_status()
        return resp.json()

    # ── 业务接口 ──────────────────────────────────────────

    @abstractmethod
    async def search(self, keyword: str, page: int = 1, page_size: int = 20) -> list[Product]:
        ...

    @abstractmethod
    async def detail(self, product_id: str) -> Product:
        ...

    @abstractmethod
    async def get_coupons(self, keyword: str, page: int = 1) -> list[Coupon]:
        ...

    # ── 上下文管理器 ──────────────────────────────────────

    async def __aenter__(self) -> "BaseEngine":
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()
