"""链接/口令解析器 + 反向比价端到端测试。

覆盖: 淘口令、淘宝短链/长链、京东短链/长链、拼多多短链/长链、混合文本、关键词提取、parse_and_compare E2E。
"""

from __future__ import annotations

import os

import pytest

# 强制清空凭据 → Dry-run
for var in [
    "TB_APP_KEY", "TB_APP_SECRET", "TB_ADZONE_ID",
    "JD_APP_KEY", "JD_APP_SECRET", "JD_SITE_ID",
    "PDD_CLIENT_ID", "PDD_CLIENT_SECRET", "PDD_PID",
]:
    os.environ.pop(var, None)

from src.models import Platform
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
