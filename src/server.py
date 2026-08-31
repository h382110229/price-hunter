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
from typing import Any

from mcp.server.mcpserver import MCPServer

from src.engines.base import BaseEngine
from src.engines.jd import JDEngine
from src.engines.pdd import PDDEngine
from src.engines.taobao import TaobaoEngine
from src.models import CompareResult, Coupon, Platform, Product, ReverseCompareResult
from src.parsers.link_extractor import ParsedLink, extract_links, get_search_keyword

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

    # 4. 全网找同款比价 (排除原品所在平台的结果中去重)
    engines = _engines()
    all_products = await _concurrent_search(engines, keyword, page=1, page_size=page_size)

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
