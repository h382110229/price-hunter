"""统一数据模型 — 商品、优惠券、比价结果。

所有引擎将各自 API 响应映射到这些通用结构，供 MCP Tool 统一输出。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Platform(str, Enum):
    """支持的电商平台"""

    TAOBAO = "taobao"
    JD = "jd"
    PDD = "pdd"


class Coupon(BaseModel):
    """优惠券信息"""

    platform: Platform
    coupon_id: str = ""
    title: str = ""
    discount: float = 0.0  # 券面额 (元)
    min_spend: float = 0.0  # 满减门槛 (元)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    url: str = ""  # 领券链接


class Product(BaseModel):
    """统一商品结构"""

    platform: Platform
    product_id: str  # 平台侧商品 ID
    title: str
    price: float  # 当前价 (元)
    original_price: Optional[float] = None  # 原价
    image_url: str = ""
    detail_url: str = ""  # 商品详情页 / 推广链接
    shop_name: str = ""
    sales_volume: Optional[int] = None  # 月销量
    commission_rate: Optional[float] = None  # 佣金比例 (%)
    coupons: list[Coupon] = Field(default_factory=list)

    @property
    def final_price(self) -> float:
        """券后价 (取最大面额券)"""
        if not self.coupons:
            return self.price
        max_discount = max(c.discount for c in self.coupons)
        return max(0.0, self.price - max_discount)


class CompareResult(BaseModel):
    """比价结果 — 同一商品在多平台的价格对比"""

    keyword: str
    products: list[Product] = Field(default_factory=list)
    cheapest: Optional[Product] = None  # 最低价商品

    def model_post_init(self, __context: object) -> None:
        if self.products and not self.cheapest:
            self.cheapest = min(self.products, key=lambda p: p.final_price)
