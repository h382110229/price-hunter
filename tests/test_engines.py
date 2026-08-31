"""单元测试 — 签名算法、Mock/Dry-run 引擎、比价排序、MCP Tool 格式。

所有测试在无凭据环境下运行 (Mock/Dry-run 模式)，无需真实 API Key。
"""

from __future__ import annotations

import asyncio
import json
import os

import pytest

# ── 强制清空凭据，确保 Dry-run 模式 ──────────────────────
# Set env vars to empty strings to override .env file on disk
for var in [
    "TB_APP_KEY", "TB_APP_SECRET", "TB_ADZONE_ID",
    "JD_APP_KEY", "JD_APP_SECRET", "JD_SITE_ID",
    "PDD_CLIENT_ID", "PDD_CLIENT_SECRET", "PDD_PID",
]:
    os.environ[var] = ""

# Reload config singleton with cleared env
import src.config
src.config.settings = src.config.Settings()

from src.engines.base import BaseEngine, md5_sign, pdd_sign
from src.engines.jd import JDEngine
from src.engines.pdd import PDDEngine
from src.engines.taobao import TaobaoEngine
from src.models import CompareResult, Coupon, Platform, Product


# ═══════════════════════════════════════════════════════════
# 1. 签名算法测试
# ═══════════════════════════════════════════════════════════

class TestMd5Sign:
    """MD5 签名算法 (淘宝 TOP / 京东联盟)"""

    def test_basic_sign(self):
        """基本签名: secret + sorted_kv + secret → MD5 大写"""
        params = {"method": "test", "app_key": "123", "timestamp": "2024-01-01"}
        secret = "mysecret"
        result = md5_sign(params, secret)
        # 手动验算: secret=123456 → sorted=app_key123methodtesttimestamp2024-01-01 → secret包裹
        assert len(result) == 32
        assert result == result.upper()

    def test_deterministic(self):
        """相同输入 → 相同签名"""
        params = {"a": "1", "b": "2"}
        secret = "sec"
        assert md5_sign(params, secret) == md5_sign(params, secret)

    def test_order_independent(self):
        """参数顺序不影响签名 (内部排序)"""
        p1 = {"b": "2", "a": "1"}
        p2 = {"a": "1", "b": "2"}
        assert md5_sign(p1, "sec") == md5_sign(p2, "sec")

    def test_different_secret_different_sign(self):
        """不同 secret → 不同签名"""
        params = {"a": "1"}
        assert md5_sign(params, "sec1") != md5_sign(params, "sec2")

    def test_empty_params(self):
        """空参数: sign = MD5(secret + secret)"""
        secret = "abc"
        import hashlib
        expected = hashlib.md5(("abcabc").encode()).hexdigest().upper()
        assert md5_sign({}, secret) == expected

    def test_known_vector(self):
        """已知向量验算"""
        params = {"method": "taobao.test", "app_key": "test123"}
        secret = "secret456"
        sorted_kv = "app_keytest123methodtaobao.test"
        sign_input = secret + sorted_kv + secret
        import hashlib
        expected = hashlib.md5(sign_input.encode()).hexdigest().upper()
        assert md5_sign(params, secret) == expected


class TestPddSign:
    """拼多多签名算法 (MD5 模式)"""

    def test_basic_sign(self):
        """PDD 签名与 md5_sign 结构一致"""
        params = {"type": "pdd.ddk.goods.search", "client_id": "abc"}
        secret = "pddsecret"
        result = pdd_sign(params, secret)
        assert len(result) == 32
        assert result == result.upper()

    def test_same_as_md5_sign(self):
        """pdd_sign 和 md5_sign 对相同输入应产生相同结果"""
        params = {"a": "1", "b": "2"}
        secret = "sec"
        assert pdd_sign(params, secret) == md5_sign(params, secret)


# ═══════════════════════════════════════════════════════════
# 2. 数据模型测试
# ═══════════════════════════════════════════════════════════

class TestProduct:
    """Product 模型"""

    def test_final_price_auto_calc(self):
        """final_price 自动 = price - coupon_amount"""
        p = Product(
            platform=Platform.TAOBAO, product_id="1", title="t",
            price=100.0, coupon_amount=30.0,
        )
        assert p.final_price == 70.0

    def test_final_price_no_negative(self):
        """券后价不低于 0"""
        p = Product(
            platform=Platform.JD, product_id="2", title="t",
            price=10.0, coupon_amount=50.0,
        )
        assert p.final_price == 0.0

    def test_final_price_explicit(self):
        """显式设置 final_price 不被覆盖"""
        p = Product(
            platform=Platform.PDD, product_id="3", title="t",
            price=100.0, coupon_amount=30.0, final_price=65.0,
        )
        assert p.final_price == 65.0

    def test_model_dump_roundtrip(self):
        """model_dump → JSON → model_validate 往返"""
        p = Product(
            platform=Platform.TAOBAO, product_id="123", title="测试商品",
            price=99.9, coupon_amount=20.0, final_price=79.9,
        )
        d = p.model_dump()
        p2 = Product.model_validate(d)
        assert p2.final_price == p.final_price


class TestCompareResult:
    """CompareResult 模型"""

    def test_auto_sort_by_final_price(self):
        """products 自动按 final_price 升序"""
        products = [
            Product(platform=Platform.JD, product_id="1", title="贵", price=200, final_price=180),
            Product(platform=Platform.TAOBAO, product_id="2", title="便宜", price=50, final_price=50),
            Product(platform=Platform.PDD, product_id="3", title="中等", price=100, final_price=90),
        ]
        result = CompareResult(keyword="test", products=products)
        assert result.products[0].title == "便宜"
        assert result.products[-1].title == "贵"

    def test_min_price_product(self):
        """min_price_product 自动选最低"""
        products = [
            Product(platform=Platform.JD, product_id="1", title="A", price=100, final_price=100),
            Product(platform=Platform.PDD, product_id="2", title="B", price=50, final_price=50),
        ]
        result = CompareResult(keyword="test", products=products)
        assert result.min_price_product is not None
        assert result.min_price_product.title == "B"

    def test_summary_generated(self):
        """自动生成比价摘要"""
        products = [
            Product(platform=Platform.TAOBAO, product_id="1", title="商品A", price=100, coupon_amount=30, final_price=70),
            Product(platform=Platform.JD, product_id="2", title="商品B", price=80, coupon_amount=10, final_price=70),
        ]
        result = CompareResult(keyword="耳机", products=products)
        assert "耳机" in result.summary
        assert "全网最低" in result.summary

    def test_empty_products(self):
        """空结果"""
        result = CompareResult(keyword="不存在", products=[])
        assert result.min_price_product is None
        assert "无搜索结果" in result.summary


# ═══════════════════════════════════════════════════════════
# 3. 引擎 Dry-run / Mock 测试
# ═══════════════════════════════════════════════════════════

class TestTaobaoEngineDryRun:
    """淘宝引擎 Dry-run 模式"""

    @pytest.mark.asyncio
    async def test_search_returns_mock(self):
        async with TaobaoEngine() as engine:
            assert engine.dry_run is True
            products = await engine.search("耳机", page_size=3)
            assert len(products) > 0
            assert all(p.platform == Platform.TAOBAO for p in products)
            assert all(p.final_price >= 0 for p in products)
            assert all(p.price > 0 for p in products)

    @pytest.mark.asyncio
    async def test_detail_returns_mock(self):
        async with TaobaoEngine() as engine:
            product = await engine.detail("123456")
            assert product.platform == Platform.TAOBAO
            assert product.product_id == "123456"

    @pytest.mark.asyncio
    async def test_get_coupons_returns_mock(self):
        async with TaobaoEngine() as engine:
            coupons = await engine.get_coupons("耳机")
            assert len(coupons) > 0
            assert all(c.platform == Platform.TAOBAO for c in coupons)


class TestJDEngineDryRun:
    """京东引擎 Dry-run 模式"""

    @pytest.mark.asyncio
    async def test_search_returns_mock(self):
        async with JDEngine() as engine:
            assert engine.dry_run is True
            products = await engine.search("手机壳", page_size=2)
            assert len(products) > 0
            assert all(p.platform == Platform.JD for p in products)

    @pytest.mark.asyncio
    async def test_detail_returns_mock(self):
        async with JDEngine() as engine:
            product = await engine.detail("JD789")
            assert product.platform == Platform.JD
            assert product.product_id == "JD789"

    @pytest.mark.asyncio
    async def test_get_coupons_returns_mock(self):
        async with JDEngine() as engine:
            coupons = await engine.get_coupons("手机壳")
            assert len(coupons) > 0


class TestPDDEngineDryRun:
    """拼多多引擎 Dry-run 模式"""

    @pytest.mark.asyncio
    async def test_search_returns_mock(self):
        async with PDDEngine() as engine:
            assert engine.dry_run is True
            products = await engine.search("充电宝", page_size=3)
            assert len(products) > 0
            assert all(p.platform == Platform.PDD for p in products)

    @pytest.mark.asyncio
    async def test_detail_returns_mock(self):
        async with PDDEngine() as engine:
            product = await engine.detail("PDD456")
            assert product.platform == Platform.PDD
            assert product.product_id == "PDD456"

    @pytest.mark.asyncio
    async def test_get_coupons_returns_mock(self):
        async with PDDEngine() as engine:
            coupons = await engine.get_coupons("充电宝")
            assert len(coupons) > 0


# ═══════════════════════════════════════════════════════════
# 4. 跨平台比价排序测试
# ═══════════════════════════════════════════════════════════

class TestComparePrices:
    """跨平台比价逻辑"""

    @pytest.mark.asyncio
    async def test_multi_platform_search(self):
        """三个平台并发搜索，结果覆盖三平台"""
        from src.server import _concurrent_search, _engines

        engines = _engines()
        products = await _concurrent_search(engines, "耳机", page=1, page_size=5)
        assert len(products) >= 3  # 至少每个平台 1 个

        # 验证覆盖三平台
        platforms = {p.platform for p in products}
        assert Platform.TAOBAO in platforms
        assert Platform.JD in platforms
        assert Platform.PDD in platforms

        # 验证所有 final_price 非负
        assert all(p.final_price >= 0 for p in products)

    @pytest.mark.asyncio
    async def test_compare_result_structure(self):
        """CompareResult 输出结构完整"""
        from src.server import _concurrent_search, _engines

        engines = _engines()
        products = await _concurrent_search(engines, "耳机", page=1, page_size=3)
        result = CompareResult(keyword="耳机", products=products)

        assert result.keyword == "耳机"
        assert len(result.products) > 0
        assert result.min_price_product is not None
        assert result.summary != ""
        assert result.products[0].final_price <= result.products[-1].final_price

    @pytest.mark.asyncio
    async def test_unknown_keyword(self):
        """未知关键词返回通用 Mock"""
        from src.server import _concurrent_search, _engines

        engines = _engines()
        products = await _concurrent_search(engines, "完全不存在的关键词xyz", page=1, page_size=3)
        # Mock 模式对未知关键词返回 _DEFAULT_MOCKS
        assert len(products) > 0


# ═══════════════════════════════════════════════════════════
# 5. MCP Tool 调用格式测试
# ═══════════════════════════════════════════════════════════

class TestMCPToolFormat:
    """MCP Tool 返回值格式验证"""

    @pytest.mark.asyncio
    async def test_search_products_format(self):
        """search_products 返回 list[dict]"""
        from src.server import search_products

        result = await search_products("耳机", platform="all", page_size=3)
        assert isinstance(result, list)
        assert len(result) > 0
        assert isinstance(result[0], dict)
        # 验证关键字段存在
        for key in ["platform", "product_id", "title", "price", "final_price", "url"]:
            assert key in result[0], f"缺少字段: {key}"

    @pytest.mark.asyncio
    async def test_compare_prices_format(self):
        """compare_prices 返回 dict 含 summary"""
        from src.server import compare_prices

        result = await compare_prices("耳机", page_size=3)
        assert isinstance(result, dict)
        assert "keyword" in result
        assert "products" in result
        assert "min_price_product" in result
        assert "summary" in result
        assert isinstance(result["products"], list)

    @pytest.mark.asyncio
    async def test_get_coupons_format(self):
        """get_coupons 返回 list[dict]"""
        from src.server import get_coupons

        result = await get_coupons("耳机", platform="all")
        assert isinstance(result, list)
        assert len(result) > 0
        assert isinstance(result[0], dict)
        for key in ["platform", "coupon_id", "discount"]:
            assert key in result[0], f"缺少字段: {key}"

    @pytest.mark.asyncio
    async def test_get_product_detail_format(self):
        """get_product_detail 返回 dict"""
        from src.server import get_product_detail

        result = await get_product_detail("12345", "taobao")
        assert isinstance(result, dict)
        assert "platform" in result
        assert result["platform"] == "taobao"

    @pytest.mark.asyncio
    async def test_get_product_detail_invalid_platform(self):
        """无效平台返回 error"""
        from src.server import get_product_detail

        result = await get_product_detail("12345", "amazon")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_search_single_platform(self):
        """单平台筛选"""
        from src.server import search_products

        result = await search_products("耳机", platform="jd", page_size=2)
        assert all(item["platform"] == "jd" for item in result)
