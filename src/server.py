"""FastMCP 入口 — 注册比价搜索 MCP Tools。

Tools:
  - search_products    跨平台商品搜索 (并发)
  - get_product_detail  单品详情
  - compare_prices     多平台比价 (并发 + 全局排序)
  - get_coupons        优惠券搜索

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
from src.models import CompareResult, Coupon, Platform, Product

logger = logging.getLogger(__name__)

# ── MCP Server 实例 ──────────────────────────────────────
mcp = MCPServer(
    "price-hunter",
    description="全网比价聚合搜索 — 淘宝联盟/京东联盟/多多进宝",
)


# ── 引擎工厂 ─────────────────────────────────────────────

def _engines() -> list[BaseEngine]:
    """按凭据可用性实例化引擎。
    未配置凭据的引擎也会被加入 (Dry-run 模式)。
    """
    from src.config import settings

    engines: list[BaseEngine] = []
    engines.append(TaobaoEngine())  # 内部自动判断 dry_run
    engines.append(JDEngine())
    engines.append(PDDEngine())
    return engines


def _filter_engines(engines: list[BaseEngine], platform: str) -> list[BaseEngine]:
    if platform == "all":
        return engines
    return [e for e in engines if e.platform.value == platform]


async def _concurrent_search(
    engines: list[BaseEngine], keyword: str, page: int, page_size: int
) -> list[Product]:
    """并发查询所有引擎，合并结果。"""

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


# ── 入口 ──────────────────────────────────────────────────
def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
