"""链接/口令解析器 + 反向比价端到端测试。

覆盖: 淘口令、淘宝短链/长链、京东短链/长链、拼多多短链/长链、混合文本、关键词提取、parse_and_compare E2E。
"""

from __future__ import annotations

import os

import pytest

# 强制清空凭据 → Dry-run
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

from src.models import Platform, Product
from src.parsers.link_extractor import ItemType, ParsedLink, extract_links, get_search_keyword


# ═══════════════════════════════════════════════════════════
# 1. 淘宝解析
# ═══════════════════════════════════════════════════════════

class TestTaobaoExtraction:
    """淘宝淘口令/链接提取"""

    def test_tkl_basic(self):
        """基本淘口令 ￥XXXXX￥"""
        text = "这个耳机超好用 ￥AbCdEf123￥ 快来抢"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.TAOBAO
        assert results[0].item_type == ItemType.TKL
        assert "AbCdEf123" in results[0].item_id

    def test_tkl_with_noise(self):
        """淘口令夹杂大量干扰文字"""
        text = (
            "🔥【限时秒杀】无线蓝牙耳机降噪运动跑步超长续航\n"
            "原价199元，券后仅需69元！\n"
            "────────────────────\n"
            "复制这段话￥AbCdEfGhI￥打开淘宝APP下单\n"
            "────────────────────\n"
            "更多好物推荐请关注我们~"
        )
        results = extract_links(text)
        assert len(results) >= 1
        taobao = [r for r in results if r.platform == Platform.TAOBAO]
        assert len(taobao) == 1
        assert taobao[0].item_type == ItemType.TKL

    def test_tb_short_link(self):
        """淘宝短链 m.tb.cn"""
        text = "好物推荐 https://m.tb.cn/h.abc123 点击购买"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.TAOBAO
        assert results[0].item_type == ItemType.SHORT_LINK
        assert "m.tb.cn" in results[0].raw_url

    def test_tb_long_link(self):
        """淘宝/天猫长链"""
        text = "看看这个 https://item.taobao.com/item.htm?id=6543210&spm=xxx"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.TAOBAO
        assert results[0].item_type == ItemType.PRODUCT_ID
        assert results[0].item_id == "6543210"

    def test_tmall_link(self):
        """天猫链接"""
        text = "天猫旗舰店 https://detail.tmall.com/item.htm?id=9876543"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.TAOBAO
        assert results[0].item_id == "9876543"

    def test_tkl_priority_over_link(self):
        """淘口令优先级高于链接"""
        text = "￥SecretCode￥ https://m.tb.cn/h.abc"
        results = extract_links(text)
        taobao_results = [r for r in results if r.platform == Platform.TAOBAO]
        assert len(taobao_results) == 1
        assert taobao_results[0].item_type == ItemType.TKL


# ═══════════════════════════════════════════════════════════
# 2. 京东解析
# ═══════════════════════════════════════════════════════════

class TestJDExtraction:
    """京东链接提取"""

    def test_jd_long_link(self):
        """京东长链 item.jd.com/xxx.html"""
        text = "京东好价 https://item.jd.com/100012345.html 立即抢购"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.JD
        assert results[0].item_type == ItemType.PRODUCT_ID
        assert results[0].item_id == "100012345"

    def test_jd_short_link_u(self):
        """京东短链 u.jd.com"""
        text = "推荐好物 https://u.jd.com/AbCdEf"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.JD
        assert results[0].item_type == ItemType.SHORT_LINK

    def test_jd_short_link_3cn(self):
        """京东短链 3.cn"""
        text = "速抢 http://3.cn/xxxxx"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.JD

    def test_jd_skuid_param(self):
        """京东 skuId 参数"""
        text = "商品链接 skuId=9876543210"
        results = extract_links(text)
        jd = [r for r in results if r.platform == Platform.JD]
        assert len(jd) == 1
        assert jd[0].item_id == "9876543210"


# ═══════════════════════════════════════════════════════════
# 3. 拼多多解析
# ═══════════════════════════════════════════════════════════

class TestPDDExtraction:
    """拼多多链接提取"""

    def test_pdd_long_link(self):
        """拼多多长链"""
        text = "拼团链接 https://mobile.yangkeduo.com/goods.html?goods_id=12345678"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.PDD
        assert results[0].item_type == ItemType.PRODUCT_ID
        assert results[0].item_id == "12345678"

    def test_pdd_short_link(self):
        """拼多多短链"""
        text = "快来拼 https://p.pinduoduo.com/AbCdEf"
        results = extract_links(text)
        assert len(results) == 1
        assert results[0].platform == Platform.PDD
        assert results[0].item_type == ItemType.SHORT_LINK

    def test_pdd_goods_id_param(self):
        """拼多多 goods_id 参数"""
        text = "商品 goods_id=55555555"
        results = extract_links(text)
        pdd = [r for r in results if r.platform == Platform.PDD]
        assert len(pdd) == 1
        assert pdd[0].item_id == "55555555"


# ═══════════════════════════════════════════════════════════
# 4. 混合文本 + 多平台同时出现
# ═══════════════════════════════════════════════════════════

class TestMixedText:
    """混合分享文本解析"""

    def test_multi_platform_text(self):
        """同一文本包含多平台链接"""
        text = (
            "【全网比价】这个耳机到处都能买：\n"
            "淘宝: ￥TaoBao123￥\n"
            "京东: https://item.jd.com/9999999.html\n"
            "拼多多: https://mobile.yangkeduo.com/goods.html?goods_id=88888888\n"
        )
        results = extract_links(text)
        platforms = {r.platform for r in results}
        assert Platform.TAOBAO in platforms
        assert Platform.JD in platforms
        assert Platform.PDD in platforms

    def test_no_link_text(self):
        """无链接文本返回空"""
        results = extract_links("今天天气真好，适合出去走走")
        assert results == []

    def test_keyword_extraction_from_title(self):
        """从分享文本提取商品关键词"""
        text = "【索尼WH-1000XM5头戴式降噪耳机】限时特惠 ￥AbCd123￥"
        results = extract_links(text)
        assert len(results) == 1
        # 关键词应包含商品名
        assert len(results[0].keyword) > 0
        assert "索尼" in results[0].keyword or "耳机" in results[0].keyword

    def test_keyword_extraction_chinese_quotes(self):
        """中文引号包裹的标题"""
        text = "「Apple AirPods Pro 2」京东特价 https://item.jd.com/1111111.html"
        results = extract_links(text)
        assert len(results) == 1
        assert "AirPods" in results[0].keyword or "Apple" in results[0].keyword


# ═══════════════════════════════════════════════════════════
# 5. get_search_keyword 辅助函数
# ═══════════════════════════════════════════════════════════

class TestGetSearchKeyword:
    """搜索关键词获取"""

    def test_use_parsed_keyword(self):
        """优先使用解析到的关键词"""
        parsed = ParsedLink(
            platform=Platform.TAOBAO, item_type=ItemType.TKL,
            item_id="￥abc￥", keyword="无线蓝牙耳机",
        )
        assert get_search_keyword(parsed) == "无线蓝牙耳机"

    def test_fallback_to_title(self):
        """其次使用商品标题"""
        parsed = ParsedLink(
            platform=Platform.JD, item_type=ItemType.PRODUCT_ID,
            item_id="123", keyword="",
        )
        kw = get_search_keyword(parsed, "索尼 WH-1000XM5 头戴式降噪耳机 黑色")
        assert "索尼" in kw

    def test_empty(self):
        """无关键词无标题返回空"""
        parsed = ParsedLink(
            platform=Platform.PDD, item_type=ItemType.PRODUCT_ID,
            item_id="456", keyword="",
        )
        assert get_search_keyword(parsed) == ""


# ═══════════════════════════════════════════════════════════
# 6. parse_and_compare E2E
# ═══════════════════════════════════════════════════════════

class TestParseAndCompare:
    """parse_and_compare 端到端测试 (Dry-run 模式)"""

    @pytest.mark.asyncio
    async def test_tkl_to_compare(self):
        """淘口令 → 全网比价"""
        from src.server import parse_and_compare
        text = "【爆款耳机】限时秒杀 ￥TESTCODE123￥ 打开淘宝"
        result = await parse_and_compare(text, page_size=3)
        assert "error" not in result
        assert result["source_platform"] == "taobao"
        assert result["keyword"] != ""
        assert len(result["cross_platform"]) > 0
        assert result["summary"] != ""
        assert result["savings"] >= 0

    @pytest.mark.asyncio
    async def test_jd_link_to_compare(self):
        """京东链接 → 全网比价"""
        from src.server import parse_and_compare
        text = "「索尼降噪耳机」京东特价 https://item.jd.com/100012345.html"
        result = await parse_and_compare(text, page_size=2)
        assert "error" not in result
        assert result["source_platform"] == "jd"
        assert len(result["cross_platform"]) > 0

    @pytest.mark.asyncio
    async def test_pdd_link_to_compare(self):
        """拼多多链接 → 全网比价"""
        from src.server import parse_and_compare
        text = "拼团价 https://mobile.yangkeduo.com/goods.html?goods_id=88888888"
        result = await parse_and_compare(text, page_size=2)
        assert "error" not in result
        assert result["source_platform"] == "pdd"
        assert len(result["cross_platform"]) > 0

    @pytest.mark.asyncio
    async def test_no_link_returns_error(self):
        """无链接文本返回错误"""
        from src.server import parse_and_compare
        result = await parse_and_compare("今天天气真好")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_multi_platform_text(self):
        """多平台链接文本 → 取最高优先级"""
        from src.server import parse_and_compare
        text = "淘宝便宜 ￥Priority123￥ 京东也行 https://item.jd.com/111.html"
        result = await parse_and_compare(text, page_size=2)
        assert "error" not in result
        # 淘口令优先级最高
        assert result["source_platform"] == "taobao"

    @pytest.mark.asyncio
    async def test_jd_short_link_3jdhk_recognized(self):
        """3.jd.hk 短链被正确识别为京东短链"""
        from src.server import parse_and_compare
        text = "【支持siri AI】iPhone17PM 美版 https://3.jd.hk/-102POe0 点击链接"
        result = await parse_and_compare(text, page_size=2)
        # 应该识别到链接，不返回 "未识别" 错误
        assert "error" not in result
        assert result["source_platform"] == "jd"
        # 关键词应该包含从分享文本提取的 iPhone 相关内容
        assert result["keyword"] != ""


# ═══════════════════════════════════════════════════════════
# 7. JD 国际域名解析
# ═══════════════════════════════════════════════════════════

class TestJDInternationalDomains:
    """京东国际 (jd.hk) 域名解析"""

    def test_3jdhk_short_link(self):
        """3.jd.hk 短链识别"""
        text = "iPhone17PM https://3.jd.hk/-102POe0 点击"
        results = extract_links(text)
        jd = [r for r in results if r.platform == Platform.JD]
        assert len(jd) == 1
        assert jd[0].item_type == ItemType.SHORT_LINK
        assert "3.jd.hk" in jd[0].raw_url

    def test_item_jd_hk_long_link(self):
        """item.jd.hk 长链提取 SKU"""
        text = "京东国际 https://item.jd.hk/1008611040.html 限时折扣"
        results = extract_links(text)
        jd = [r for r in results if r.platform == Platform.JD]
        assert len(jd) == 1
        assert jd[0].item_type == ItemType.PRODUCT_ID
        assert jd[0].item_id == "1008611040"

    def test_npcitem_jd_hk_long_link(self):
        """npcitem.jd.hk 长链提取 SKU"""
        text = "海外购 https://npcitem.jd.hk/5566778899.html"
        results = extract_links(text)
        jd = [r for r in results if r.platform == Platform.JD]
        assert len(jd) == 1
        assert jd[0].item_id == "5566778899"

    def test_jd_hk_with_sku_param(self):
        """jd.hk 链接中含 skuId 参数"""
        text = "商品 sku=9876543210"
        results = extract_links(text)
        jd = [r for r in results if r.platform == Platform.JD]
        assert len(jd) == 1
        assert jd[0].item_id == "9876543210"

    def test_jd_hk_priority_over_short(self):
        """jd.hk 长链优先级高于短链"""
        text = "https://3.jd.hk/-abc https://item.jd.hk/123456.html"
        results = extract_links(text)
        jd = [r for r in results if r.platform == Platform.JD]
        assert len(jd) == 1
        # 长链优先
        assert jd[0].item_type == ItemType.PRODUCT_ID
        assert jd[0].item_id == "123456"


# ═══════════════════════════════════════════════════════════
# 8. SKU 提取函数
# ═══════════════════════════════════════════════════════════

class TestExtractSkuFromUrl:
    """extract_sku_from_url URL 中 SKU 提取"""

    def test_jd_com_sku(self):
        """item.jd.com/{sku}.html"""
        from src.parsers.link_extractor import extract_sku_from_url
        assert extract_sku_from_url("https://item.jd.com/100012345.html") == "100012345"

    def test_jd_hk_sku(self):
        """item.jd.hk/{sku}.html"""
        from src.parsers.link_extractor import extract_sku_from_url
        assert extract_sku_from_url("https://item.jd.hk/1008611040.html") == "1008611040"

    def test_npcitem_jd_hk_sku(self):
        """npcitem.jd.hk/{sku}.html"""
        from src.parsers.link_extractor import extract_sku_from_url
        assert extract_sku_from_url("https://npcitem.jd.hk/55667788.html") == "55667788"

    def test_jd_query_param_sku(self):
        """URL query 中的 skuId"""
        from src.parsers.link_extractor import extract_sku_from_url
        url = "https://item.jd.com/product/123.html?skuId=998877&other=1"
        assert extract_sku_from_url(url) == "998877"

    def test_pdd_goods_id(self):
        """拼多多 goods_id"""
        from src.parsers.link_extractor import extract_sku_from_url
        url = "https://mobile.yangkeduo.com/goods.html?goods_id=12345678"
        assert extract_sku_from_url(url) == "12345678"

    def test_taobao_id(self):
        """淘宝 id 参数"""
        from src.parsers.link_extractor import extract_sku_from_url
        url = "https://item.taobao.com/item.htm?id=6543210&spm=xxx"
        assert extract_sku_from_url(url) == "6543210"

    def test_no_match(self):
        """无匹配返回 None"""
        from src.parsers.link_extractor import extract_sku_from_url
        assert extract_sku_from_url("https://www.example.com/page") is None


# ═══════════════════════════════════════════════════════════
# 9. 标题相似度过滤 (server.py)
# ═══════════════════════════════════════════════════════════

class TestTitleSimilarity:
    """标题相似度计算与相关性过滤"""

    def test_identical_titles(self):
        """完全相同标题 → 相似度 1.0"""
        from src.server import _title_similarity
        sim = _title_similarity("iPhone 17 Pro Max 美版", "iPhone 17 Pro Max 美版")
        assert sim == 1.0

    def test_similar_titles(self):
        """相似标题 → 高相似度"""
        from src.server import _title_similarity
        sim = _title_similarity(
            "iPhone 17 Pro Max 美版 支持siri AI",
            "Apple iPhone17PM 美版 256G",
        )
        assert sim > 0.15  # 共享 iphone, 美版 等 token

    def test_unrelated_titles(self):
        """完全无关标题 → 低相似度"""
        from src.server import _title_similarity
        sim = _title_similarity(
            "iPhone 17 Pro Max 美版",
            "漩涡地漏浴室下水道盖头防堵过滤网",
        )
        assert sim < 0.08  # 低于阈值

    def test_empty_title(self):
        """空标题 → 0"""
        from src.server import _title_similarity
        assert _title_similarity("", "test") == 0.0
        assert _title_similarity("test", "") == 0.0

    def test_filter_removes_unrelated(self):
        """_filter_by_relevance 过滤无关商品"""
        from src.server import _filter_by_relevance
        products = [
            Product(platform=Platform.JD, product_id="1", title="iPhone17PM 美版 256G", price=5000, final_price=5000),
            Product(platform=Platform.JD, product_id="2", title="漩涡地漏浴室下水道盖头防堵", price=10, final_price=10),
            Product(platform=Platform.PDD, product_id="3", title="阿凡迪7D超薄隐形丝袜", price=40, final_price=40),
            Product(platform=Platform.TAOBAO, product_id="4", title="iPhone 17 Pro Max 手机壳", price=30, final_price=30),
        ]
        filtered = _filter_by_relevance(products, "iPhone 17 Pro Max 美版", "iPhone17PM")
        # 地漏和丝袜应被过滤掉
        titles = [p.title for p in filtered]
        assert any("iPhone" in t for t in titles)
        assert not any("地漏" in t for t in titles)
        assert not any("丝袜" in t for t in titles)

    def test_filter_keyword_fallback(self):
        """当无原品标题时，用关键词做过滤"""
        from src.server import _filter_by_relevance
        products = [
            Product(platform=Platform.JD, product_id="1", title="无线蓝牙耳机降噪", price=100, final_price=100),
            Product(platform=Platform.JD, product_id="2", title="不锈钢地漏防臭", price=20, final_price=20),
        ]
        filtered = _filter_by_relevance(products, "", "蓝牙耳机")
        assert len(filtered) == 1
        assert "蓝牙" in filtered[0].title or "耳机" in filtered[0].title
