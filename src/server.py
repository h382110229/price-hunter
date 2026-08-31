"""FastMCP 入口 — 注册比价搜索 MCP Tools。

Tools:
  - search_products   跨平台商品搜索
  - get_product_detail 单品详情
  - compare_prices    多平台比价
  - get_coupons       优惠券搜索
"""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.fastmcp import FastMCP

from src.engines.jd import JDEngine
from src.engines.pdd import PDDEngine
from src.engines.taobao import TaobaoEngine
from src.models import CompareResult, Product

# ── MCP Server 实例 ──────────────────────────────────────
mcp = FastMCP(
    "price-hunter",
    description="全网比价聚合搜索 — 淘宝联盟/京东联盟/多多进宝",
)


# ── 引擎工厂 ─────────────────────────────────────────────
def _engines():
    """按凭据可用性实例化引擎"""
    engines = []
    from src.config import settings

    if settings.taobao.app_key:
        engines.append(TaobaoEngine())
    if settings.jd.app_key:
        engines.append(JDEngine())
    if settings.pdd.client_id:
        engines.append(PDDEngine())
    return engines


# ── MCP Tools ─────────────────────────────────────────────

@mcp.tool()
async def search_products(
    keyword: str,
    platform: str = "all",
    page: int = 1,
    page_size: int = 20,
) -> list[dict[str, Any]]:
    """跨平台商品搜索。

    Args:
        keyword: 搜索关键词
        platform: 平台筛选 (all / taobao / jd / pdd)
        page: 页码
        page_size: 每页数量
    """
    engines = _engines()
    if platform != "all":
        engines = [e for e in engines if e.platform.value == platform]

    results: list[Product] = []
    for engine in engines:
        try:
            products = await engine.search(keyword, page, page_size)
            results.extend(products)
        except NotImplementedError:
            pass  # Phase 2 未实现的引擎静默跳过
        finally:
            await engine.close()

    return [p.model_dump() for p in results]


@mcp.tool()
async def get_product_detail(product_id: str, platform: str) -> dict[str, Any]:
    """获取单品详情 (含优惠券信息)。

    Args:
        product_id: 平台侧商品 ID
        platform: 平台 (taobao / jd / pdd)
    """
    engine_map = {"taobao": TaobaoEngine, "jd": JDEngine, "pdd": PDDEngine}
    engine_cls = engine_map.get(platform)
    if not engine_cls:
        return {"error": f"不支持的平台: {platform}"}

    async with engine_cls() as engine:
        product = await engine.detail(product_id)
        return product.model_dump()


@mcp.tool()
async def compare_prices(keyword: str, page_size: int = 10) -> dict[str, Any]:
    """多平台比价 — 同一关键词在各平台搜索并排序。

    Args:
        keyword: 搜索关键词
        page_size: 每平台取前 N 个结果
    """
    engines = _engines()
    all_products: list[Product] = []

    for engine in engines:
        try:
            products = await engine.search(keyword, page=1, page_size=page_size)
            all_products.extend(products)
        except NotImplementedError:
            pass
        finally:
            await engine.close()

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
    engines = _engines()
    if platform != "all":
        engines = [e for e in engines if e.platform.value == platform]

    from src.models import Coupon

    results: list[Coupon] = []
    for engine in engines:
        try:
            coupons = await engine.get_coupons(keyword, page)
            results.extend(coupons)
        except NotImplementedError:
            pass
        finally:
            await engine.close()

    return [c.model_dump() for c in results]


# ── 入口 ──────────────────────────────────────────────────
def main():
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
