"""统一数据模型 — 商品、优惠券、比价结果、反向比价。

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


_PLATFORM_NAMES: dict[Platform, str] = {
    Platform.TAOBAO: "淘宝",
    Platform.JD: "京东",
    Platform.PDD: "拼多多",
}


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
    product_id: str
    title: str
    price: float
    coupon_amount: float = 0.0
    final_price: float = 0.0
    original_price: Optional[float] = None
    url: str = ""
    coupon_url: str = ""
    tkl_or_command: str = ""
    image_url: str = ""
    detail_url: str = ""
    shop_name: str = ""
    sales_volume: Optional[int] = None
    commission_rate: Optional[float] = None
    coupons: list[Coupon] = Field(default_factory=list)

    def model_post_init(self, __context: object) -> None:
        if self.final_price == 0.0:
            self.final_price = max(0.0, self.price - self.coupon_amount)


class CompareResult(BaseModel):
    """比价结果"""

    keyword: str
    products: list[Product] = Field(default_factory=list)
    min_price_product: Optional[Product] = None
    summary: str = ""

    def model_post_init(self, __context: object) -> None:
        if self.products:
            self.products.sort(key=lambda p: p.final_price)
            self.min_price_product = self.products[0]
        if not self.summary:
            self.summary = self._build_summary()

    def _build_summary(self) -> str:
        if not self.products:
            return f"「{self.keyword}」在所有平台均无搜索结果。"

        lines = [f"🔍 「{self.keyword}」全网比价结果（共 {len(self.products)} 件）：\n"]
        for i, p in enumerate(self.products[:10], 1):
            tag = "🏆 全网最低" if i == 1 else ""
            coupon_info = f"（券{p.coupon_amount:.0f}元）" if p.coupon_amount > 0 else ""
            name = _PLATFORM_NAMES[p.platform]
            lines.append(f"{i}. [{name}] {p.title[:40]}… — ¥{p.final_price:.2f}{coupon_info} {tag}")

        if self.min_price_product:
            mp = self.min_price_product
            name = _PLATFORM_NAMES[mp.platform]
            lines.append(f"\n💰 推荐：{name}「{mp.title[:30]}」¥{mp.final_price:.2f}")
        return "\n".join(lines)


class ReverseCompareResult(BaseModel):
    """反向比价结果 — 用户分享某平台商品，找其他平台同款最低价

    - source_product: 用户分享的原品信息
    - cross_platform: 全网同款比价结果 (按 final_price 升序)
    - best_deal: 全网最优 (可能是原品，也可能是其他平台)
    - savings: 对比原品可节省的金额 (元)
    - summary: LLM 友好的比价报告
    """

    source_text: str = ""  # 原始分享文本
    source_platform: str = ""
    source_product_id: str = ""
    source_title: str = ""
    source_price: float = 0.0
    source_coupon: float = 0.0
    source_final_price: float = 0.0
    keyword: str = ""  # 用于找同款的关键词
    cross_platform: list[Product] = Field(default_factory=list)
    best_deal: Optional[Product] = None
    savings: float = 0.0  # 对比原品可省多少
    summary: str = ""

    def model_post_init(self, __context: object) -> None:
        if self.cross_platform:
            self.cross_platform.sort(key=lambda p: p.final_price)
            self.best_deal = self.cross_platform[0]
        if self.source_final_price > 0 and self.best_deal:
            self.savings = max(0.0, self.source_final_price - self.best_deal.final_price)
        if not self.summary:
            self.summary = self._build_summary()

    def _build_summary(self) -> str:
        lines: list[str] = []
        lines.append(f"🔄 反向比价报告\n")
        src_name = _PLATFORM_NAMES.get(Platform(self.source_platform), self.source_platform) if self.source_platform else "未知"
        lines.append(f"📌 原品来源: {src_name}")
        if self.source_title:
            lines.append(f"📌 原品标题: {self.source_title[:50]}")
        lines.append(f"📌 原品面价: ¥{self.source_price:.2f}")
        if self.source_coupon > 0:
            lines.append(f"📌 原品隐藏券: ¥{self.source_coupon:.0f}")
        lines.append(f"📌 原品到手价: ¥{self.source_final_price:.2f}")
        lines.append(f"📌 搜索关键词: {self.keyword}\n")

        if not self.cross_platform:
            lines.append("❌ 未找到全网同款商品。")
            return "\n".join(lines)

        lines.append(f"🔍 全网同款比价（共 {len(self.cross_platform)} 件）：\n")
        for i, p in enumerate(self.cross_platform[:10], 1):
            tag = "🏆 全网最低" if i == 1 else ""
            is_source = (
                p.platform.value == self.source_platform
                and p.product_id == self.source_product_id
            )
            source_mark = " ⭐ 原品" if is_source else ""
            coupon_info = f"（券{p.coupon_amount:.0f}元）" if p.coupon_amount > 0 else ""
            name = _PLATFORM_NAMES[p.platform]
            lines.append(
                f"{i}. [{name}] {p.title[:40]}… — ¥{p.final_price:.2f}{coupon_info}{source_mark} {tag}"
            )

        if self.best_deal:
            bd = self.best_deal
            name = _PLATFORM_NAMES[bd.platform]
            if self.savings > 0:
                lines.append(
                    f"\n💰 最优推荐: {name}「{bd.title[:30]}」¥{bd.final_price:.2f}"
                    f"\n🎉 比原品省 ¥{self.savings:.2f}！"
                )
            else:
                lines.append(f"\n✅ 原品已是最优价格，无需跨平台购买。")
        return "\n".join(lines)
