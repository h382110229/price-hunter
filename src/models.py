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
    """统一商品结构

    字段设计覆盖三大联盟 API 的核心输出:
    - price: 商品面价 (原价/拼单价)
    - coupon_amount: 隐藏券/东券面额
    - final_price: 券后到手价 (price - coupon_amount)
    - url: 推广链接 / 下单直达链接
    - coupon_url: 领券链接
    - tkl_or_command: 淘口令 / 分享口令
    """

    platform: Platform
    product_id: str  # 平台侧商品 ID
    title: str
    price: float  # 商品面价 (元)
    coupon_amount: float = 0.0  # 隐藏券/满减券面额 (元)
    final_price: float = 0.0  # 券后到手价 (元)
    original_price: Optional[float] = None  # 原价 (未打折)
    url: str = ""  # 推广/下单直达链接
    coupon_url: str = ""  # 领券链接
    tkl_or_command: str = ""  # 淘口令 / 分享口令
    image_url: str = ""
    detail_url: str = ""  # 商品详情页
    shop_name: str = ""
    sales_volume: Optional[int] = None  # 月销量
    commission_rate: Optional[float] = None  # 佣金比例 (%)
    coupons: list[Coupon] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        """自动计算 final_price: 若未显式设置则 = price - coupon_amount"""
        if self.final_price == 0.0:
            self.final_price = max(0.0, self.price - self.coupon_amount)


class CompareResult(BaseModel):
    """比价结果 — 同一商品在多平台的价格对比

    - products: 按 final_price 升序排列
    - min_price_product: 全网最低价商品
    - summary: LLM 友好的比价结论文本
    """

    keyword: str
    products: list[Product] = Field(default_factory=list)
    min_price_product: Optional[Product] = None
    summary: str = ""

    def model_post_init(self, __context: object) -> None:
        if self.products:
            # 按 final_price 升序
            self.products.sort(key=lambda p: p.final_price)
            self.min_price_product = self.products[0]
        if not self.summary:
            self.summary = self._build_summary()

    def _build_summary(self) -> str:
        """生成 LLM 友好的比价结论"""
        if not self.products:
            return f"「{self.keyword}」在所有平台均无搜索结果。"

        lines = [f"🔍 「{self.keyword}」全网比价结果（共 {len(self.products)} 件）：\n"]
        for i, p in enumerate(self.products[:10], 1):
            tag = "🏆 全网最低" if i == 1 else ""
            coupon_info = f"（券{p.coupon_amount:.0f}元）" if p.coupon_amount > 0 else ""
            platform_name = {
                Platform.TAOBAO: "淘宝",
                Platform.JD: "京东",
                Platform.PDD: "拼多多",
            }[p.platform]
            lines.append(
                f"{i}. [{platform_name}] {p.title[:40]}… — "
                f"¥{p.final_price:.2f}{coupon_info} {tag}"
            )

        if self.min_price_product:
            mp = self.min_price_product
            platform_name = {
                Platform.TAOBAO: "淘宝",
                Platform.JD: "京东",
                Platform.PDD: "拼多多",
            }[mp.platform]
            lines.append(
                f"\n💰 推荐：{platform_name}「{mp.title[:30]}」¥{mp.final_price:.2f}"
            )
        return "\n".join(lines)
