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
        assert "🏆" in result.summary

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


class TestTaobaoSigning:
    """淘宝 TOP API 签名单元测试"""

    def test_taobao_sign_basic(self):
        """基本签名: MD5(secret + sorted_kv + secret).upper()"""
        from src.engines.taobao import taobao_sign
        params = {
            "method": "taobao.tbk.dg.material.optional",
            "app_key": "test_key",
            "timestamp": "2026-09-01 12:00:00",
        }
        secret = "test_secret"
        result = taobao_sign(params, secret)
        assert len(result) == 32
        assert result == result.upper()

    def test_taobao_sign_excludes_sign_field(self):
        """签名时剔除 sign 字段"""
        from src.engines.taobao import taobao_sign
        params = {"a": "1", "sign": "should_be_ignored", "b": "2"}
        params_without = {"a": "1", "b": "2"}
        assert taobao_sign(params, "sec") == taobao_sign(params_without, "sec")

    def test_taobao_sign_order_independent(self):
        """参数顺序不影响签名"""
        from src.engines.taobao import taobao_sign
        p1 = {"b": "2", "a": "1"}
        p2 = {"a": "1", "b": "2"}
        assert taobao_sign(p1, "sec") == taobao_sign(p2, "sec")

    def test_taobao_sign_known_vector(self):
        """已知向量验算"""
        from src.engines.taobao import taobao_sign
        import hashlib
        params = {"method": "test", "app_key": "key"}
        secret = "sec"
        sorted_kv = "app_keykeymethodtest"
        expected = hashlib.md5((secret + sorted_kv + secret).encode()).hexdigest().upper()
        assert taobao_sign(params, secret) == expected


class TestTaobaoProductParsing:
    """淘宝商品解析回归测试"""

    def _make_engine(self):
        return TaobaoEngine()

    def test_zk_final_price(self):
        """zk_final_price 作为面价"""
        engine = self._make_engine()
        item = {"zk_final_price": "199.9", "title": "测试"}
        p = engine._parse_product(item)
        assert p.price == 199.9

    def test_coupon_amount(self):
        """coupon_amount 正确解析"""
        engine = self._make_engine()
        item = {"zk_final_price": "100", "coupon_amount": "30", "title": "测试"}
        p = engine._parse_product(item)
        assert p.coupon_amount == 30.0
        assert p.final_price == 70.0

    def test_no_coupon(self):
        """无券时 final_price = price"""
        engine = self._make_engine()
        item = {"zk_final_price": "50", "coupon_amount": "0", "title": "测试"}
        p = engine._parse_product(item)
        assert p.coupon_amount == 0.0
        assert p.final_price == 50.0

    def test_volume_sales(self):
        """volume 字段作为销量"""
        engine = self._make_engine()
        item = {"zk_final_price": "100", "volume": 12345, "title": "测试"}
        p = engine._parse_product(item)
        assert p.sales_volume == 12345

    def test_coupon_url_fields(self):
        """coupon_share_url 和 coupon_click_url 正确映射"""
        engine = self._make_engine()
        item = {
            "zk_final_price": "100", "coupon_amount": "10",
            "coupon_share_url": "https://share.url", "coupon_click_url": "https://click.url",
            "title": "测试",
        }
        p = engine._parse_product(item)
        assert p.coupon_url == "https://share.url"
        assert p.coupons[0].url == "https://click.url"

    def test_shop_title(self):
        """店铺名从 shop_title 提取"""
        engine = self._make_engine()
        item = {"zk_final_price": "100", "shop_title": "测试旗舰店", "title": "测试"}
        p = engine._parse_product(item)
        assert p.shop_name == "测试旗舰店"


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


class TestJDSigning:
    """京东联盟签名单元测试"""

    def test_jd_sign_basic(self):
        """基本签名: MD5(secret + sorted_kv + secret).upper()"""
        from src.engines.jd import jd_sign
        params = {
            "method": "jd.union.open.goods.query",
            "app_key": "test_key",
            "timestamp": "2026-08-31 12:00:00",
        }
        secret = "test_secret"
        result = jd_sign(params, secret)
        assert len(result) == 32
        assert result == result.upper()

    def test_jd_sign_deterministic(self):
        """相同输入 → 相同签名"""
        from src.engines.jd import jd_sign
        params = {"a": "1", "b": "2"}
        assert jd_sign(params, "sec") == jd_sign(params, "sec")

    def test_jd_sign_order_independent(self):
        """参数顺序不影响签名"""
        from src.engines.jd import jd_sign
        p1 = {"b": "2", "a": "1"}
        p2 = {"a": "1", "b": "2"}
        assert jd_sign(p1, "sec") == jd_sign(p2, "sec")

    def test_jd_sign_includes_param_json(self):
        """签名包含 param_json 字段"""
        from src.engines.jd import jd_sign
        import json
        pj = json.dumps({"goodsReqDTO": {"keyword": "test"}}, separators=(",", ":"))
        params = {
            "method": "jd.union.open.goods.query",
            "app_key": "key",
            "param_json": pj,
            "timestamp": "2026-08-31 12:00:00",
        }
        result = jd_sign(params, "secret")
        assert len(result) == 32

    def test_jd_sign_known_vector(self):
        """已知向量验算"""
        from src.engines.jd import jd_sign
        import hashlib
        params = {"method": "test", "app_key": "key"}
        secret = "sec"
        sorted_kv = "app_keykeymethodtest"
        expected = hashlib.md5((secret + sorted_kv + secret).encode()).hexdigest().upper()
        assert jd_sign(params, secret) == expected


class TestJDProductParsing:
    """京东商品解析回归测试"""

    def _make_engine(self):
        return JDEngine()

    def test_price_parsing(self):
        """priceInfo.price 正确解析"""
        engine = self._make_engine()
        item = {"skuId": "123", "skuName": "测试", "priceInfo": {"price": 299.9}}
        p = engine._parse_product(item)
        assert p.price == 299.9

    def test_best_coupon_extraction(self):
        """提取最大面额优惠券"""
        engine = self._make_engine()
        item = {
            "skuId": "123", "skuName": "测试", "priceInfo": {"price": 100},
            "couponInfo": {"couponList": [
                {"couponId": "1", "discount": 10, "quota": 99, "link": ""},
                {"couponId": "2", "discount": 30, "quota": 99, "link": ""},
                {"couponId": "3", "discount": 20, "quota": 99, "link": ""},
            ]},
        }
        p = engine._parse_product(item)
        assert p.coupon_amount == 30.0
        assert p.final_price == 70.0
        assert p.coupons[0].coupon_id == "2"

    def test_no_coupon(self):
        """无优惠券时 final_price = price"""
        engine = self._make_engine()
        item = {"skuId": "123", "skuName": "测试", "priceInfo": {"price": 50},
                "couponInfo": {"couponList": []}}
        p = engine._parse_product(item)
        assert p.coupon_amount == 0.0
        assert p.final_price == 50.0

    def test_commission_rate(self):
        """佣金比例正确解析"""
        engine = self._make_engine()
        item = {"skuId": "123", "skuName": "测试", "priceInfo": {"price": 100},
                "commissionInfo": {"commissionShare": 15.5}}
        p = engine._parse_product(item)
        assert p.commission_rate == 15.5

    def test_sales_volume(self):
        """30天引单数正确解析"""
        engine = self._make_engine()
        item = {"skuId": "123", "skuName": "测试", "priceInfo": {"price": 100},
                "inOrderCount30Days": 5895}
        p = engine._parse_product(item)
        assert p.sales_volume == 5895

    def test_image_url(self):
        """图片从 imageInfo.imageList[0].url 提取"""
        engine = self._make_engine()
        item = {"skuId": "123", "skuName": "测试", "priceInfo": {"price": 100},
                "imageInfo": {"imageList": [{"url": "https://img.jd.com/1.jpg"}]}}
        p = engine._parse_product(item)
        assert p.image_url == "https://img.jd.com/1.jpg"

    def test_detail_url_format(self):
        """详情页 URL 格式: item.jd.com/{skuId}.html"""
        engine = self._make_engine()
        item = {"skuId": "99887766", "skuName": "测试", "priceInfo": {"price": 100}}
        p = engine._parse_product(item)
        assert p.detail_url == "https://item.jd.com/99887766.html"

    def test_promotion_url_mock(self):
        """Dry-run 模式转链返回 mock URL"""
        engine = self._make_engine()
        import asyncio
        url = asyncio.run(engine.get_promotion_url("https://item.jd.com/123.html"))
        assert "u.jd.com" in url


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
# 3b. PDD 引擎回归测试 (单元转换、优惠券、关键词过滤)
# ═══════════════════════════════════════════════════════════

class TestPDDUnitConversion:
    """PDD 价格单位转换与优惠券计算"""

    def _make_engine(self):
        """创建 dry_run 引擎 (不触发真实 API)"""
        return PDDEngine()

    def test_price_fen_to_yuan(self):
        """min_group_price 分 → 元"""
        engine = self._make_engine()
        item = {"min_group_price": 37200, "coupon_discount": 0, "goods_name": "测试"}
        p = engine._parse_recommend_item(item)
        assert p.price == 372.0

    def test_coupon_fen_to_yuan(self):
        """coupon_discount 分 → 元"""
        engine = self._make_engine()
        item = {"min_group_price": 10000, "coupon_discount": 3000, "goods_name": "测试"}
        p = engine._parse_recommend_item(item)
        assert p.coupon_amount == 30.0
        assert p.final_price == 70.0

    def test_coupon_max_no_overlap(self):
        """优惠券取 max(coupon_discount, extra_coupon_amount)，不累加"""
        engine = self._make_engine()
        item = {
            "min_group_price": 10000,
            "coupon_discount": 3000,  # 30元
            "extra_coupon_amount": 5000,  # 50元
            "goods_name": "测试",
        }
        p = engine._parse_recommend_item(item)
        # 应取 max(30, 50) = 50，而不是 30+50=80
        assert p.coupon_amount == 50.0
        assert p.final_price == 50.0

    def test_coupon_only_extra(self):
        """仅有 extra_coupon_amount 时也能正确计算"""
        engine = self._make_engine()
        item = {
            "min_group_price": 10000,
            "coupon_discount": 0,
            "extra_coupon_amount": 2000,
            "goods_name": "测试",
        }
        p = engine._parse_recommend_item(item)
        assert p.coupon_amount == 20.0

    def test_commission_permille_to_percent(self):
        """promotion_rate 千分比 → 百分比"""
        engine = self._make_engine()
        item = {"min_group_price": 10000, "promotion_rate": 90, "goods_name": "测试"}
        p = engine._parse_recommend_item(item)
        assert p.commission_rate == 9.0  # 90‰ = 9%

    def test_goods_sign_as_product_id(self):
        """product_id 优先使用 goods_sign"""
        engine = self._make_engine()
        item = {
            "goods_id": 123456,
            "goods_sign": "ABC123_sign",
            "min_group_price": 10000,
            "goods_name": "测试",
        }
        p = engine._parse_recommend_item(item)
        assert p.product_id == "ABC123_sign"

    def test_sales_tip_wan(self):
        """销量 "1.2万" → 12000"""
        engine = self._make_engine()
        item = {"min_group_price": 10000, "sales_tip": "1.2万", "goods_name": "测试"}
        p = engine._parse_recommend_item(item)
        assert p.sales_volume == 12000

    def test_sales_tip_plain_number(self):
        """销量 "5895" → 5895"""
        engine = self._make_engine()
        item = {"min_group_price": 10000, "sales_tip": "5895", "goods_name": "测试"}
        p = engine._parse_recommend_item(item)
        assert p.sales_volume == 5895

    def test_final_price_no_negative(self):
        """券后价不低于 0"""
        engine = self._make_engine()
        item = {"min_group_price": 500, "coupon_discount": 1000, "goods_name": "测试"}
        p = engine._parse_recommend_item(item)
        assert p.final_price == 0.0


class TestPDDKeywordFilter:
    """PDD 客户端关键词过滤"""

    def _make_engine(self):
        return PDDEngine()

    def _make_product(self, title: str) -> Product:
        return Product(
            platform=Platform.PDD, product_id="test", title=title,
            price=10.0, coupon_amount=0.0, final_price=10.0,
        )

    def test_exact_match(self):
        """完整关键词包含 → 排在前面"""
        engine = self._make_engine()
        products = [
            self._make_product("维达抽纸家用实惠装整箱"),
            self._make_product("金纺柔顺剂薰衣草"),
            self._make_product("洗衣液大桶装"),
            self._make_product("纸巾抽纸面巾纸"),
        ]
        result = engine._filter_by_keyword(products, "抽纸")
        # 匹配项应排在前面
        assert "抽纸" in result[0].title
        assert "抽纸" in result[1].title

    def test_partial_match(self):
        """部分分词匹配 → 保留"""
        engine = self._make_engine()
        products = [
            self._make_product("无线蓝牙耳机降噪运动"),
            self._make_product("有线耳机入耳式重低音"),
            self._make_product("洗衣液大桶装家庭用"),
        ]
        result = engine._filter_by_keyword(products, "蓝牙耳机")
        # 至少 "无线蓝牙耳机降噪运动" 应该匹配
        assert any("蓝牙" in p.title for p in result)

    def test_no_match_fallback(self):
        """无匹配时补充热门商品"""
        engine = self._make_engine()
        products = [
            self._make_product("苹果iPhone手机壳"),
            self._make_product("华为Mate手机壳"),
            self._make_product("洗衣液"),
        ]
        result = engine._filter_by_keyword(products, "耳机")
        # 无匹配，应补充热门商品
        assert len(result) >= 1

    def test_empty_keyword(self):
        """空关键词 → 全部通过"""
        engine = self._make_engine()
        products = [self._make_product("A"), self._make_product("B")]
        result = engine._filter_by_keyword(products, "")
        assert len(result) == 2

    def test_match_score_ordering(self):
        """匹配结果按分数排序"""
        engine = self._make_engine()
        products = [
            self._make_product("洗衣液大桶装"),  # 不匹配 "抽纸"
            self._make_product("维达抽纸家用实惠装整箱抽纸批发"),  # 强匹配
            self._make_product("纸巾抽纸面巾纸"),  # 中等匹配
        ]
        result = engine._filter_by_keyword(products, "抽纸")
        # 第一个应该是匹配度最高的
        assert "抽纸" in result[0].title


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
