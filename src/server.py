"""FastMCP 入口 — 注册比价搜索 MCP Tools。

Tools:
  - search_products     跨平台商品搜索 (并发)
  - get_product_detail   单品详情
  - compare_prices      多平台比价 (并发 + 全局排序)
  - get_coupons         优惠券搜索
  - parse_and_compare   分享链接/口令解析 + 全网找同款比价

当凭据未配置时，所有引擎自动降级为 Mock/Dry-run 模式。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from mcp.server.mcpserver import MCPServer

from src.engines.base import BaseEngine
from src.engines.jd import JDEngine
from src.engines.pdd import PDDEngine
from src.engines.taobao import TaobaoEngine
from src.models import CompareResult, Coupon, Platform, Product, ReverseCompareResult
from src.parsers.link_extractor import (
    ParsedLink, extract_links, get_search_keyword, resolve_and_enrich,
)

logger = logging.getLogger(__name__)

# ── MCP Server 实例 ──────────────────────────────────────
mcp = MCPServer(
    "price-hunter",
    description="全网比价聚合搜索 — 淘宝联盟/京东联盟/多多进宝",
)


# ── 引擎工厂 ─────────────────────────────────────────────

def _engines() -> list[BaseEngine]:
    from src.config import settings
    engines: list[BaseEngine] = [TaobaoEngine(), JDEngine(), PDDEngine()]
    return engines


def _filter_engines(engines: list[BaseEngine], platform: str) -> list[BaseEngine]:
    if platform == "all":
        return engines
    return [e for e in engines if e.platform.value == platform]


async def _concurrent_search(
    engines: list[BaseEngine], keyword: str, page: int, page_size: int
) -> list[Product]:
    async def _safe_search(engine: BaseEngine) -> list[Product]:
        try:
            return await engine.search(keyword, page, page_size)
        except Exception as e:
            logger.warning("%s 搜索失败: %s", engine.platform.value, e)
            return []
        finally:
            await engine.close()

    tasks = [_safe_search(e) for e in engines]
    results = await asyncio.gather(*tasks)
    return [p for batch in results for p in batch]


async def _get_source_product(parsed: ParsedLink) -> Product | None:
    """获取源商品详情 (真实 API 或 Mock)"""
    engine_map = {
        Platform.TAOBAO: TaobaoEngine,
        Platform.JD: JDEngine,
        Platform.PDD: PDDEngine,
    }
    engine_cls = engine_map.get(parsed.platform)
    if not engine_cls:
        return None
    async with engine_cls() as engine:
        try:
            return await engine.detail(parsed.item_id)
        except Exception:
            return None


def _tokenize(text: str) -> set[str]:
    """将文本分词为小写 token 集合 (中文按字, 英文按单词)。"""
    tokens = set()
    for m in re.finditer(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", text.lower()):
        token = m.group()
        # 中文按 2-gram 拆分以提高匹配粒度
        if re.match(r"[\u4e00-\u9fff]", token):
            for i in range(len(token)):
                tokens.add(token[i])
            for i in range(len(token) - 1):
                tokens.add(token[i:i+2])
        else:
            tokens.add(token)
    return tokens


def _title_similarity(title_a: str, title_b: str) -> float:
    """计算两个商品标题的 Jaccard 相似度 (基于 token 集合)。"""
    if not title_a or not title_b:
        return 0.0
    tokens_a = _tokenize(title_a)
    tokens_b = _tokenize(title_b)
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


# 标题相似度阈值: 低于此值视为无关商品
_SIMILARITY_THRESHOLD = 0.08


def _filter_by_relevance(
    products: list[Product], reference_title: str, keyword: str,
) -> list[Product]:
    """过滤掉与原品标题/关键词不相关的商品。"""
    if not reference_title and not keyword:
        return products
    filtered = []
    for p in products:
        # 优先用原品标题做相似度匹配
        if reference_title:
            sim = _title_similarity(reference_title, p.title)
            if sim >= _SIMILARITY_THRESHOLD:
                filtered.append(p)
                continue
        # 回退: 用关键词做包含检查
        if keyword:
            kw_lower = keyword.lower()
            title_lower = p.title.lower()
            # 关键词的任一 token 出现在标题中即保留
            tokens = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z0-9]+", kw_lower)
            if any(t in title_lower for t in tokens if len(t) >= 2):
                filtered.append(p)
                continue
        # 既不相似也不包含关键词 → 过滤掉
        logger.debug("过滤无关商品: %s (sim=%.2f)", p.title[:30], _title_similarity(reference_title, p.title))
    return filtered


# ── MCP Tools ─────────────────────────────────────────────

@mcp.tool()
async def search_products(
    keyword: str,
    platform: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> list[dict[str, Any]]:
    """跨平台商品搜索 (并发请求)。

    Args:
        keyword: 搜索关键词
        platform: 平台筛选 (all / taobao / jd / pdd)
        page: 页码
        page_size: 每页数量
    """
    engines = _filter_engines(_engines(), platform)
    products = await _concurrent_search(engines, keyword, page, page_size)
    products.sort(key=lambda p: p.final_price)
    return [p.model_dump() for p in products]


@mcp.tool()
async def get_product_detail(product_id: str, platform: str) -> dict[str, Any]:
    """获取单品详情 (含优惠券信息)。

    Args:
        product_id: 平台侧商品 ID
        platform: 平台 (taobao / jd / pdd)
    """
    engine_map: dict[str, type[BaseEngine]] = {
        "taobao": TaobaoEngine,
        "jd": JDEngine,
        "pdd": PDDEngine,
    }
    engine_cls = engine_map.get(platform)
    if not engine_cls:
        return {"error": f"不支持的平台: {platform}"}

    async with engine_cls() as engine:
        try:
            product = await engine.detail(product_id)
            return product.model_dump()
        except Exception as e:
            return {"error": str(e)}


@mcp.tool()
async def compare_prices(keyword: str, page_size: int = 5) -> dict[str, Any]:
    """多平台比价 — 并发搜索 + 按券后价全局升序排序。

    Args:
        keyword: 搜索关键词
        page_size: 每平台取前 N 个结果
    """
    engines = _engines()
    all_products = await _concurrent_search(engines, keyword, page=1, page_size=page_size)
    result = CompareResult(keyword=keyword, products=all_products)
    return result.model_dump()


@mcp.tool()
async def get_coupons(
    keyword: str, platform: str = "all", page: int = 1
) -> list[dict[str, Any]]:
    """搜索优惠券。

    Args:
        keyword: 关键词或商品 ID
        platform: 平台筛选 (all / taobao / jd / pdd)
        page: 页码
    """
    engines = _filter_engines(_engines(), platform)

    async def _safe_coupons(engine: BaseEngine) -> list[Coupon]:
        try:
            return await engine.get_coupons(keyword, page)
        except Exception as e:
            logger.warning("%s 优惠券查询失败: %s", engine.platform.value, e)
            return []
        finally:
            await engine.close()

    tasks = [_safe_coupons(e) for e in engines]
    results = await asyncio.gather(*tasks)
    coupons = [c for batch in results for c in batch]
    return [c.model_dump() for c in coupons]


@mcp.tool()
async def parse_and_compare(raw_text: str, page_size: int = 5) -> dict[str, Any]:
    """解析分享链接/淘口令，自动找全网同款并比价。

    从用户分享的文本中提取商品标识 (淘口令/京东链接/拼多多链接)，
    查询原品价格，然后跨平台搜索同款，输出比价报告。

    Args:
        raw_text: 包含商品链接或口令的分享文本
        page_size: 每平台取前 N 个同款结果
    """
    # 1. 解析文本
    parsed_list = extract_links(raw_text)
    if not parsed_list:
        return {"error": "未从文本中识别到任何商品链接或口令", "raw_text": raw_text[:200]}

    parsed = parsed_list[0]  # 取最高优先级

    # 1b. 如果是短链，尝试跟随重定向 + 提取 SKU + 提取标题
    if parsed.item_type.value == "short":
        parsed = await resolve_and_enrich(parsed)

    # 2. 获取原品详情
    source_product = await _get_source_product(parsed)

    source_title = source_product.title if source_product else ""
    source_price = source_product.price if source_product else 0.0
    source_coupon = source_product.coupon_amount if source_product else 0.0
    source_final = source_product.final_price if source_product else source_price

    # 3. 确定搜索关键词
    keyword = get_search_keyword(parsed, source_title)
    if not keyword:
        keyword = parsed.item_id  # fallback: 用 ID 搜

    # 4. 全网找同款比价
    engines = _engines()
    all_products = await _concurrent_search(engines, keyword, page=1, page_size=page_size)

    # 4b. 按标题相似度过滤无关商品 (防止地漏/丝袜等无关结果混入)
    ref_title = source_title or parsed.keyword or keyword
    all_products = _filter_by_relevance(all_products, ref_title, keyword)

    # 5. 构建反向比价结果
    result = ReverseCompareResult(
        source_text=raw_text[:200],
        source_platform=parsed.platform.value,
        source_product_id=parsed.item_id,
        source_title=source_title,
        source_price=source_price,
        source_coupon=source_coupon,
        source_final_price=source_final,
        keyword=keyword,
        cross_platform=all_products,
    )
    return result.model_dump()


# ── 入口 ──────────────────────────────────────────────────
def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
