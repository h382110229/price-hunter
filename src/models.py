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

_PLATFORM_EMOJI: dict[Platform, str] = {
    Platform.TAOBAO: "🟠",
    Platform.JD: "🔴",
    Platform.PDD: "🟤",
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


def _fmt_price(price: float) -> str:
    """格式化价格: 整数不带小数，否则保留2位"""
    if price == int(price):
        return f"¥{int(price)}"
    return f"¥{price:.2f}"


def _truncate(s: str, max_len: int = 30) -> str:
    """截断字符串"""
    return s[:max_len] + "…" if len(s) > max_len else s


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
            return f"🔍 「{self.keyword}」— 全网无搜索结果"

        lines: list[str] = []

        # ── 最低价推荐卡片 ──
        mp = self.min_price_product
        if mp:
            mp_name = _PLATFORM_NAMES[mp.platform]
            mp_emoji = _PLATFORM_EMOJI[mp.platform]
            coupon_tag = f"（券 {_fmt_price(mp.coupon_amount)}）" if mp.coupon_amount > 0 else ""
            lines.append(f"## 🏆 最低价推荐")
            lines.append("")
            lines.append(f"> {mp_emoji} **{mp_name}** — {_truncate(mp.title, 40)}")
            lines.append(f">")
            if mp.coupon_amount > 0:
                lines.append(f"> 原价 ~~{_fmt_price(mp.price)}~~ → 券后 **{_fmt_price(mp.final_price)}** {coupon_tag}")
            else:
                lines.append(f"> 价格 **{_fmt_price(mp.final_price)}**")
            if mp.url:
                lines.append(f"> 🔗 [直达链接]({mp.url})")
            elif mp.tkl_or_command:
                lines.append(f"> 📋 淘口令: `{mp.tkl_or_command}`")
            lines.append("")

        # ── 省钱提示 ──
        if len(self.products) >= 2:
            diff = self.products[-1].final_price - self.products[0].final_price
            if diff > 0:
                lines.append(f"💰 **最高可省 {_fmt_price(diff)}** (最低 vs 最高)")
                lines.append("")

        # ── 比价表格 ──
        lines.append(f"## 🔍 「{self.keyword}」全网比价（{len(self.products)} 件）")
        lines.append("")
        lines.append("| # | 平台 | 商品 | 原价 | 优惠券 | 到手价 | 链接 |")
        lines.append("|---|------|------|------|--------|--------|------|")

        for i, p in enumerate(self.products[:10], 1):
            name = _PLATFORM_NAMES[p.platform]
            emoji = _PLATFORM_EMOJI[p.platform]
            tag = " 🏆" if i == 1 else ""
            coupon = f"¥{p.coupon_amount:.0f}" if p.coupon_amount > 0 else "-"
            title_short = _truncate(p.title, 25)

            # 链接: 优先淘口令，其次url
            if p.tkl_or_command:
                link = f"`{p.tkl_or_command}`"
            elif p.url:
                link = f"[🔗]({p.url})"
            elif p.coupon_url:
                link = f"[🎫]({p.coupon_url})"
            else:
                link = "-"

            lines.append(
                f"| {i} | {emoji} {name} | {title_short}{tag} | {_fmt_price(p.price)} | {coupon} | **{_fmt_price(p.final_price)}** | {link} |"
            )

        return "\n".join(lines)


class ReverseCompareResult(BaseModel):
    """反向比价结果"""

    source_text: str = ""
    source_platform: str = ""
    source_product_id: str = ""
    source_title: str = ""
    source_price: float = 0.0
    source_coupon: float = 0.0
    source_final_price: float = 0.0
    keyword: str = ""
    cross_platform: list[Product] = Field(default_factory=list)
    best_deal: Optional[Product] = None
    savings: float = 0.0
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
        src_name = _PLATFORM_NAMES.get(Platform(self.source_platform), self.source_platform) if self.source_platform else "未知"
        src_emoji = _PLATFORM_EMOJI.get(Platform(self.source_platform), "⚪") if self.source_platform else "⚪"

        # ── 原品信息卡片 ──
        lines.append("## 📌 原品信息")
        lines.append("")
        lines.append(f"> {src_emoji} **{src_name}**")
        if self.source_title:
            lines.append(f"> {_truncate(self.source_title, 50)}")
        lines.append(f">")
        lines.append(f"> 面价 {_fmt_price(self.source_price)}")
        if self.source_coupon > 0:
            lines.append(f"> 隐藏券 {_fmt_price(self.source_coupon)}")
        lines.append(f"> 到手价 **{_fmt_price(self.source_final_price)}**")
        lines.append("")

        if not self.cross_platform:
            lines.append("❌ 未找到全网同款商品。")
            return "\n".join(lines)

        # ── 最优推荐 ──
        if self.best_deal:
            bd = self.best_deal
            bd_name = _PLATFORM_NAMES[bd.platform]
            bd_emoji = _PLATFORM_EMOJI[bd.platform]
            lines.append("## 🏆 最优推荐")
            lines.append("")
            lines.append(f"> {bd_emoji} **{bd_name}** — {_truncate(bd.title, 40)}")
            lines.append(f">")
            if bd.coupon_amount > 0:
                lines.append(f"> 原价 ~~{_fmt_price(bd.price)}~~ → 券后 **{_fmt_price(bd.final_price)}**")
            else:
                lines.append(f"> 价格 **{_fmt_price(bd.final_price)}**")
            if self.savings > 0:
                lines.append(f">")
                lines.append(f"> 🎉 **比原品省 {_fmt_price(self.savings)}！**")
            else:
                lines.append(f">")
                lines.append(f"> ✅ 原品已是最优价格")
            lines.append("")

        # ── 全网比价表格 ──
        lines.append(f"## 🔍 全网同款比价（{len(self.cross_platform)} 件）")
        lines.append("")
        lines.append("| # | 平台 | 商品 | 原价 | 优惠券 | 到手价 | 备注 |")
        lines.append("|---|------|------|------|--------|--------|------|")

        for i, p in enumerate(self.cross_platform[:10], 1):
            name = _PLATFORM_NAMES[p.platform]
            emoji = _PLATFORM_EMOJI[p.platform]
            tag = " 🏆" if i == 1 else ""
            coupon = f"¥{p.coupon_amount:.0f}" if p.coupon_amount > 0 else "-"
            title_short = _truncate(p.title, 25)

            is_source = (
                p.platform.value == self.source_platform
                and p.product_id == self.source_product_id
            )
            note = "⭐原品" if is_source else ""

            lines.append(
                f"| {i} | {emoji} {name} | {title_short}{tag} | {_fmt_price(p.price)} | {coupon} | **{_fmt_price(p.final_price)}** | {note} |"
            )

        return "\n".join(lines)
