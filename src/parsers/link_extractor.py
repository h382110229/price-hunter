"""商品链接/淘口令混合解析器。

从一段包含大量干扰文字的分享文本中提取:
- 淘口令 (￥...￥) / 淘宝短链 (m.tb.cn) / 淘宝长链 (item.taobao.com / detail.tmall.com)
- 京东短链 (u.jd.com / 3.cn) / 京东长链 (item.jd.com/{sku_id}.html)
- 拼多多短链 (p.pinduoduo.com) / 拼多多长链 (yangkeduo.com/goods.html)

输出标准化结构: Platform + ItemType + itemId/URL
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from src.models import Platform


class ItemType(str, Enum):
    """提取到的标识类型"""

    TKL = "tkl"          # 淘口令
    SHORT_LINK = "short"  # 短链
    PRODUCT_ID = "pid"    # 商品 ID (从 URL 中提取)
    FULL_URL = "url"      # 完整商品链接


@dataclass
class ParsedLink:
    """解析结果"""

    platform: Platform
    item_type: ItemType
    item_id: str          # 商品 ID 或口令原文
    raw_url: str = ""     # 原始 URL (如有)
    keyword: str = ""     # 从商品标题/上下文提取的关键词 (用于找同款)
    confidence: float = 1.0  # 置信度 (0~1)

    def to_dict(self) -> dict:
        return {
            "platform": self.platform.value,
            "item_type": self.item_type.value,
            "item_id": self.item_id,
            "raw_url": self.raw_url,
            "keyword": self.keyword,
            "confidence": self.confidence,
        }


# ═══════════════════════════════════════════════════════════
# 正则表达式 (按优先级排序)
# ═══════════════════════════════════════════════════════════

# ── 淘宝 ──────────────────────────────────────────────────
# 淘口令: ￥XXXXX￥ 或 ₤XXXXX₤ 或 ¤XXXXX¤
_RE_TKL = re.compile(r"[￥₤¤¥]([A-Za-z0-9]{6,})[￥₤¤¥]")
# 淘宝短链: m.tb.cn/h.xxx 或 m.tb.cn/xxx
_RE_TB_SHORT = re.compile(r"(https?://m\.tb\.cn/[^\s\u4e00-\u9fff]+)", re.IGNORECASE)
# 淘宝/天猫长链: item.taobao.com/item.htm?id=xxx 或 detail.tmall.com/...
_RE_TB_ITEM_ID = re.compile(
    r"(?:item\.taobao\.com|detail\.tmall\.com)[^\s]*?[?&]id=(\d+)",
    re.IGNORECASE,
)
# 纯数字 itemId (在淘宝链接上下文中)
_RE_TB_BARE_ID = re.compile(r"(?:itemId|item_id|num_iid)[=:]\s*(\d+)", re.IGNORECASE)

# ── 京东 ──────────────────────────────────────────────────
# 京东长链: item.jd.com/12345678.html
_RE_JD_LONG = re.compile(r"item\.jd\.com/(\d+)\.html", re.IGNORECASE)
# 京东短链: u.jd.com/xxx 或 3.cn/xxx
_RE_JD_SHORT = re.compile(
    r"(https?://(?:u\.jd\.com|3\.cn)/[^\s\u4e00-\u9fff]+)", re.IGNORECASE
)
# 京东 sku_id 关键字
_RE_JD_SKUID = re.compile(r"(?:skuId|sku_id|wareId)[=:]\s*(\d+)", re.IGNORECASE)

# ── 拼多多 ────────────────────────────────────────────────
# 拼多多长链: yangkeduo.com/goods.html?goods_id=xxx
_RE_PDD_LONG = re.compile(
    r"(?:yangkeduo\.com|mobile\.yangkeduo\.com)[^\s]*?goods_id=(\d+)",
    re.IGNORECASE,
)
# 拼多多短链: p.pinduoduo.com/xxx
_RE_PDD_SHORT = re.compile(
    r"(https?://p\.pinduoduo\.com/[^\s\u4e00-\u9fff]+)", re.IGNORECASE
)
# 拼多多 goods_id 关键字
_RE_PDD_GOODS_ID = re.compile(r"goods_id[=:]\s*(\d+)", re.IGNORECASE)

# ── 关键词提取 ────────────────────────────────────────────
# 匹配常见分享文本中的商品名 (淘宝/京东/拼多多分享格式)
_RE_KEYWORD_PATTERNS = [
    # 【商品标题】或「商品标题」
    re.compile(r"[【「]([^】」]{4,60})[】」]"),
    # "商品标题" (引号包裹)
    re.compile(r"[""「]([^""」]{4,60})[""」]"),
    # 分享文本中 "我在xxx发现了..." 后面的内容
    re.compile(r"发现[了]?.*?[：:]?\s*(.{4,60}?)(?:[,，。]|https?|$)"),
]


# ═══════════════════════════════════════════════════════════
# 解析主函数
# ═══════════════════════════════════════════════════════════

def extract_links(text: str) -> list[ParsedLink]:
    """从分享文本中提取所有可识别的商品标识。

    按优先级匹配: 口令 > 短链 > 长链 > 纯 ID。
    同一平台只保留最高优先级的匹配结果。
    """
    results: list[ParsedLink] = []
    seen_platforms: set[Platform] = set()

    # 提取关键词 (用于后续找同款)
    keyword = _extract_keyword(text)

    # ── 1. 淘口令 (最高优先级) ─────────────────────────────
    tkl_match = _RE_TKL.search(text)
    if tkl_match:
        tkl_code = tkl_match.group(1)
        results.append(ParsedLink(
            platform=Platform.TAOBAO,
            item_type=ItemType.TKL,
            item_id=f"￥{tkl_code}￥",
            keyword=keyword,
            confidence=1.0,
        ))
        seen_platforms.add(Platform.TAOBAO)

    # ── 2. 淘宝链接 ───────────────────────────────────────
    if Platform.TAOBAO not in seen_platforms:
        # 短链
        short_match = _RE_TB_SHORT.search(text)
        if short_match:
            results.append(ParsedLink(
                platform=Platform.TAOBAO,
                item_type=ItemType.SHORT_LINK,
                item_id=short_match.group(1),
                raw_url=short_match.group(1),
                keyword=keyword,
                confidence=0.9,
            ))
            seen_platforms.add(Platform.TAOBAO)
        else:
            # 长链 itemId
            id_match = _RE_TB_ITEM_ID.search(text) or _RE_TB_BARE_ID.search(text)
            if id_match:
                results.append(ParsedLink(
                    platform=Platform.TAOBAO,
                    item_type=ItemType.PRODUCT_ID,
                    item_id=id_match.group(1),
                    keyword=keyword,
                    confidence=1.0,
                ))
                seen_platforms.add(Platform.TAOBAO)

    # ── 3. 京东链接 ───────────────────────────────────────
    # 长链
    jd_long = _RE_JD_LONG.search(text)
    jd_short = _RE_JD_SHORT.search(text)
    jd_skuid = _RE_JD_SKUID.search(text)

    if jd_long:
        results.append(ParsedLink(
            platform=Platform.JD,
            item_type=ItemType.PRODUCT_ID,
            item_id=jd_long.group(1),
            raw_url=f"https://item.jd.com/{jd_long.group(1)}.html",
            keyword=keyword,
            confidence=1.0,
        ))
    elif jd_short:
        results.append(ParsedLink(
            platform=Platform.JD,
            item_type=ItemType.SHORT_LINK,
            item_id=jd_short.group(1),
            raw_url=jd_short.group(1),
            keyword=keyword,
            confidence=0.8,
        ))
    elif jd_skuid:
        results.append(ParsedLink(
            platform=Platform.JD,
            item_type=ItemType.PRODUCT_ID,
            item_id=jd_skuid.group(1),
            keyword=keyword,
            confidence=1.0,
        ))

    # ── 4. 拼多多链接 ─────────────────────────────────────
    pdd_long = _RE_PDD_LONG.search(text)
    pdd_short = _RE_PDD_SHORT.search(text)
    pdd_gid = _RE_PDD_GOODS_ID.search(text)

    if pdd_long:
        results.append(ParsedLink(
            platform=Platform.PDD,
            item_type=ItemType.PRODUCT_ID,
            item_id=pdd_long.group(1),
            keyword=keyword,
            confidence=1.0,
        ))
    elif pdd_short:
        results.append(ParsedLink(
            platform=Platform.PDD,
            item_type=ItemType.SHORT_LINK,
            item_id=pdd_short.group(1),
            raw_url=pdd_short.group(1),
            keyword=keyword,
            confidence=0.8,
        ))
    elif pdd_gid:
        results.append(ParsedLink(
            platform=Platform.PDD,
            item_type=ItemType.PRODUCT_ID,
            item_id=pdd_gid.group(1),
            keyword=keyword,
            confidence=1.0,
        ))

    return results


def _extract_keyword(text: str) -> str:
    """从分享文本中提取商品关键词。

    尝试匹配常见分享格式中的商品标题，用于后续"找同款"搜索。
    """
    for pattern in _RE_KEYWORD_PATTERNS:
        match = pattern.search(text)
        if match:
            kw = match.group(1).strip()
            # 清理干扰词
            for noise in ["点击链接", "打开淘宝", "打开京东", "打开拼多多", "立即抢购", "查看详情"]:
                kw = kw.replace(noise, "")
            kw = kw.strip()
            if len(kw) >= 2:
                return kw
    return ""


def get_search_keyword(parsed: ParsedLink, original_title: str = "") -> str:
    """获取用于"找同款"的搜索关键词。

    优先使用解析时提取的关键词，其次使用 API 返回的商品标题。
    对标题做截断处理，取核心主词 (前 20 字符)。
    """
    if parsed.keyword:
        return parsed.keyword
    if original_title:
        # 去除常见前缀/后缀噪音
        title = original_title
        for prefix in ["【", "】", "「", "」", "*", " "]:
            title = title.replace(prefix, "")
        # 取前 20 字符作为搜索词
        return title[:20].strip()
    return ""
