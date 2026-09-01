"""商品链接/淘口令混合解析器。

从一段包含大量干扰文字的分享文本中提取:
- 淘口令 (￥...￥) / 淘宝短链 (m.tb.cn) / 淘宝长链 (item.taobao.com / detail.tmall.com)
- 京东短链 (u.jd.com / 3.cn / 3.jd.hk) / 京东长链 (item.jd.com / item.jd.hk / npcitem.jd.hk)
- 拼多多短链 (p.pinduoduo.com / pdd.com) / 拼多多长链 (yangkeduo.com/goods.html)

支持通过 HTTP 重定向解析短链，获取落地页真实 URL 和商品标题。

输出标准化结构: Platform + ItemType + itemId/URL
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum

import httpx

from src.models import Platform

logger = logging.getLogger(__name__)


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
# 京东国际长链: item.jd.hk/12345678.html, npcitem.jd.hk/12345678.html
_RE_JD_HK_LONG = re.compile(
    r"(?:npc)?item\.jd\.hk/(\d+)\.html", re.IGNORECASE,
)
# 京东短链: u.jd.com/xxx, 3.cn/xxx, 3.jd.hk/xxx
_RE_JD_SHORT = re.compile(
    r"(https?://(?:u\.jd\.com|3\.cn|3\.jd\.hk)/[^\s\u4e00-\u9fff]+)",
    re.IGNORECASE,
)
# 京东 sku_id 关键字
_RE_JD_SKUID = re.compile(r"(?:skuId|sku_id|wareId|sku)[=:]\s*(\d+)", re.IGNORECASE)

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
# 注意: 先匹配最外层括号, 内层的 【营销标签】 在后处理中清洗
_RE_KEYWORD_PATTERNS = [
    # 「商品标题」 — 优先中文书名号 (京东分享常用)
    re.compile(r"[「]([^」]{4,80})[」]"),
    # 【商品标题】 — 中文方括号
    re.compile(r"[【]([^】]{4,80})[】]"),
    # "商品标题" (引号包裹) — 使用 Unicode 避免编码歧义
    re.compile(r"[\u201c\u201d]([^\u201c\u201d\u300d]{4,60})[\u201c\u201d]"),
    # 分享文本中 "我在xxx发现了..." 后面的内容
    re.compile(r"发现[了]?.*?[：:]?\s*(.{4,60}?)(?:[,，。]|https?|$)"),
]

# 营销标签正则 — 匹配独立的【...】标签 (非商品名主体)
_RE_MARKETING_TAG = re.compile(
    r"【(?:顺丰包邮|支持[^】]{1,15}|新品|预售|现货|直邮|保税|正品|保证|"
    r"限时|秒杀|特价|清仓|促销|热卖|爆款|网红|官方|自营|"
    r"全国联保|含税|包税|免邮|加急|闪购|补贴|返利|优惠|"
    r"AI|siri|Siri|SIRI)[^】]*】",
    re.IGNORECASE,
)
# 清洗后的残留括号
_RE_LEFTOVER_BRACKETS = re.compile(r"[【】「」\[\]（）\(\)]+")


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
    # 长链 (包括 jd.hk 国际)
    jd_long = _RE_JD_LONG.search(text) or _RE_JD_HK_LONG.search(text)
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

    策略:
    1. 匹配「...」(京东分享) — 内部清洗营销标签
    2. 跳过纯营销标签的【...】，找商品主体的【...】
    3. 匹配引号包裹的标题
    4. 匹配 "发现" 格式
    """
    # ── 1. 「...」格式 (京东分享) ──
    m = re.search(r"[「]([^」]{4,80})[」]", text)
    if m:
        kw = _clean_keyword(m.group(1))
        if kw and len(kw) >= 2:
            return kw

    # ── 2. 【...】格式 — 跳过营销标签，找商品主体 ──
    for m in re.finditer(r"[【]([^】]{4,80})[】]", text):
        candidate = m.group(1).strip()
        # 检查是否是纯营销标签 (不含括号的原始内容)
        if _is_marketing_tag_content(candidate):
            continue
        kw = _clean_keyword(candidate)
        if kw and len(kw) >= 2:
            return kw

    # ── 2b. 如果所有【...】都是营销标签，尝试去除营销标签后的剩余文本 ──
    cleaned = _RE_MARKETING_TAG.sub("", text)
    cleaned = _RE_LEFTOVER_BRACKETS.sub(" ", cleaned)
    # 提取有意义的文本片段 (至少包含一个中文或英文单词)
    segments = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9]+(?:\s+[a-zA-Z0-9]+)+", cleaned)
    if segments:
        # 过滤掉噪音词
        noise_words = {"点击链接", "直接打开", "立即抢购", "查看详情", "京东", "淘宝", "拼多多"}
        meaningful = [s.strip() for s in segments if s.strip() not in noise_words and len(s.strip()) >= 2]
        if meaningful:
            return " ".join(meaningful[:3])[:40]

    # ── 3. 引号包裹的标题 ──
    m = re.search(r"[\u201c\u201d]([^\u201c\u201d\u300d]{4,60})[\u201c\u201d]", text)
    if m:
        kw = _clean_keyword(m.group(1))
        if kw and len(kw) >= 2:
            return kw

    # ── 4. "发现" 格式 ──
    m = re.search(r"发现[了]?.*?[：:]?\s*(.{4,60}?)(?:[,，。]|https?|$)", text)
    if m:
        kw = _clean_keyword(m.group(1))
        if kw and len(kw) >= 2:
            return kw

    return ""


def _is_marketing_tag_content(text: str) -> bool:
    """判断【...】中的内容是否是纯营销标签 (非商品名)。"""
    marketing_keywords = [
        "顺丰包邮", "包邮", "现货", "预售", "直邮", "保税", "正品", "保证",
        "限时", "秒杀", "特价", "清仓", "促销", "热卖", "爆款", "网红",
        "官方", "自营", "全国联保", "含税", "包税", "免邮", "加急", "闪购",
        "补贴", "返利", "优惠", "新品",
    ]
    text_lower = text.lower().strip()
    # 匹配 "支持xxx" / "siri" / "AI" 等
    if re.match(r"支持.{1,15}$", text_lower):
        return True
    if text_lower in ("ai", "siri", "google assistant"):
        return True
    for kw in marketing_keywords:
        if kw in text:
            return True
    return False


def _clean_keyword(text: str) -> str:
    """清洗关键词文本: 去营销标签 + 残留括号 + 噪音词。"""
    cleaned = _RE_MARKETING_TAG.sub("", text)
    cleaned = _RE_LEFTOVER_BRACKETS.sub(" ", cleaned)
    for noise in ["点击链接", "打开淘宝", "打开京东", "打开拼多多", "立即抢购", "查看详情"]:
        cleaned = cleaned.replace(noise, "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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


# ═══════════════════════════════════════════════════════════
# 短链重定向解析 (异步)
# ═══════════════════════════════════════════════════════════

# 匹配落地页 URL 中的 SKU / goods_id
_RE_URL_SKU = re.compile(
    r"(?:item\.jd\.com|item\.jd\.hk|npcitem\.jd\.hk)[^\s]*?(?:/(\d+)\.html|[?&](?:skuId|sku|wareId)=(\d+))",
    re.IGNORECASE,
)

# HTML <title> 提取
_RE_HTML_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Open Graph title
_RE_OG_TITLE = re.compile(
    r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\'](.*?)["\']',
    re.IGNORECASE,
)

# 通用短链域名列表 (需要重定向解析)
_SHORT_LINK_DOMAINS = (
    "u.jd.com", "3.cn", "3.jd.hk",
    "m.tb.cn",
    "p.pinduoduo.com", "pdd.com",
)


# 最大手动重定向次数
_MAX_REDIRECTS = 10

# 在 Location header 中匹配 SKU 的模式
_RE_LOCATION_SKU = re.compile(
    r"(?:item\.jd\.com|item\.jd\.hk|npcitem\.jd\.hk)[^\s]*?/(\d+)\.html",
    re.IGNORECASE,
)
_RE_LOCATION_SKU_PARAM = re.compile(r"[?&](?:skuId|sku|wareId)=(\d+)")


async def resolve_short_link(url: str, *, timeout: float = 8.0) -> tuple[str | None, str | None]:
    """跟随 HTTP 重定向解析短链，返回 (最终落地页URL, 途中提取的SKU)。

    手动跟随重定向以便在每一级 Location header 中嗅探 SKU。
    返回 (None, None) 表示解析失败或超时。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Version/17.5 Mobile/15E148 Safari/604.1"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    current_url = url
    found_sku: str | None = None

    try:
        async with httpx.AsyncClient(
            follow_redirects=False,  # 手动跟随，嗅探每级 Location
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=5.0, pool=5.0),
            headers=headers,
        ) as client:
            resp: httpx.Response | None = None
            for _ in range(_MAX_REDIRECTS):
                resp = await client.get(current_url)

                # 检查是否有重定向
                location = resp.headers.get("location", "")
                if location:
                    # 补全相对路径
                    if location.startswith("/"):
                        parsed_url = httpx.URL(current_url)
                        location = f"{parsed_url.scheme}://{parsed_url.host}{location}"
                    elif not location.startswith("http"):
                        location = f"https://{location}"

                    # 在 Location 中嗅探 SKU
                    if not found_sku:
                        sku = extract_sku_from_url(location)
                        if sku:
                            found_sku = sku
                            logger.info("Location 嗅探到 SKU: %s (from %s)", sku, location[:80])

                    current_url = location
                    continue

                # 没有重定向，到达最终页面
                break

            final_url = current_url
            if final_url != url:
                logger.info("短链解析: %s → %s", url, final_url)

            # 如果还没找到 SKU，从最终 URL 提取
            if not found_sku:
                found_sku = extract_sku_from_url(final_url)

            # 尝试从 HTML meta refresh 提取
            if resp is not None and resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                text = resp.text[:5000]
                meta_refresh = re.search(
                    r'url=["\']?(https?://[^"\'>\s]+)', text, re.IGNORECASE,
                )
                if meta_refresh:
                    meta_url = meta_refresh.group(1)
                    if not found_sku:
                        found_sku = extract_sku_from_url(meta_url)
                    return meta_url, found_sku

            return (final_url if final_url != url else None, found_sku)
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e:
        logger.warning("短链解析失败 %s: %s", url, e)
        return None, None


async def extract_title_from_url(url: str, *, timeout: float = 8.0) -> str:
    """从落地页 HTML 中提取商品标题。

    尝试顺序: og:title > <title>。返回空字符串表示失败。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) "
            "Mobile/15E148"
        ),
    }
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(connect=5.0, read=timeout, write=5.0, pool=5.0),
            headers=headers,
        ) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return ""
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type:
                return ""
            html = resp.text[:20000]  # 只读前 20KB

            # 优先 og:title
            og_match = _RE_OG_TITLE.search(html)
            if og_match:
                title = og_match.group(1).strip()
                if len(title) >= 4:
                    logger.info("og:title 提取: %s", title[:60])
                    return title

            # 其次 <title>
            title_match = _RE_HTML_TITLE.search(html)
            if title_match:
                title = title_match.group(1).strip()
                # 清理常见后缀
                for suffix in ["-京东", "-JD.COM", "｜京东", "|京东", "-淘宝", "-天猫"]:
                    title = title.replace(suffix, "")
                title = title.strip()
                if len(title) >= 4:
                    logger.info("<title> 提取: %s", title[:60])
                    return title
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPError) as e:
        logger.warning("标题提取失败 %s: %s", url, e)
    return ""


def extract_sku_from_url(url: str) -> str | None:
    """从落地页 URL 中提取 SKU ID (京东) 或 goods_id (拼多多)。"""
    # 京东 — 优先查询参数 skuId/sku/wareId (比路径更可靠)
    jd_param = re.search(r"[?&](?:skuId|sku|wareId)=(\d+)", url)
    if jd_param:
        return jd_param.group(1)
    # 京东 — 路径中的 SKU (直接跟在域名后的数字)
    jd_path = re.search(
        r"(?:item\.jd\.com|item\.jd\.hk|npcitem\.jd\.hk)/(\d+)\.html",
        url, re.IGNORECASE,
    )
    if jd_path:
        return jd_path.group(1)
    # 拼多多
    pdd_match = re.search(r"goods_id=(\d+)", url)
    if pdd_match:
        return pdd_match.group(1)
    # 淘宝
    tb_match = re.search(r"(?:id|item_id|num_iid)=(\d+)", url)
    if tb_match:
        return tb_match.group(1)
    return None


def _clean_title(title: str) -> str:
    """清洗商品标题中的营销标签，提取核心商品名。

    例: "【顺丰包邮】【支持Siri AI】Apple/苹果 iPhone 17 Pro Max 美版"
    → "Apple/苹果 iPhone 17 Pro Max 美版"
    """
    # 先去除营销标签
    cleaned = _RE_MARKETING_TAG.sub("", title)
    # 清理残留括号
    cleaned = _RE_LEFTOVER_BRACKETS.sub(" ", cleaned)
    # 去除常见后缀
    for suffix in ["-京东", "-JD.COM", "｜京东", "|京东", "-淘宝", "-天猫", "【自营】"]:
        cleaned = cleaned.replace(suffix, "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:60] if cleaned else title[:60]


async def resolve_and_enrich(parsed: ParsedLink) -> ParsedLink:
    """解析短链并丰富元数据: 重定向 → 提取 SKU → 提取标题关键词。

    如果解析成功，会原地更新 parsed 对象的 item_id / raw_url / keyword。
    始终返回同一个 parsed 对象 (不创建新的)。
    """
    if parsed.item_type != ItemType.SHORT_LINK:
        return parsed

    url = parsed.raw_url or parsed.item_id
    if not url.startswith("http"):
        url = f"https://{url}"

    # 1. 跟随重定向 + Location 嗅探 SKU
    final_url, location_sku = await resolve_short_link(url)

    if final_url:
        parsed.raw_url = final_url

    # 2. 优先使用 Location 嗅探到的 SKU，其次从最终 URL 提取
    sku = location_sku
    if not sku and final_url:
        sku = extract_sku_from_url(final_url)
    if sku:
        parsed.item_id = sku
        parsed.item_type = ItemType.PRODUCT_ID
        parsed.confidence = 0.95

    # 3. 如果没有关键词，尝试从落地页提取标题
    if not parsed.keyword and final_url:
        title = await extract_title_from_url(final_url)
        if title:
            parsed.keyword = _clean_title(title)

    return parsed
