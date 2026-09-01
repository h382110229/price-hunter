## Summary

实现商品链接/淘口令混合解析与全网找同款比价功能。

## Changes

### Link Extractor (src/parsers/link_extractor.py)
- 淘口令 ￥XXXXX￥ / ₤XXXXX₤ 匹配
- 淘宝短链 m.tb.cn / 天猫长链 detail.tmall.com / 淘宝长链 item.taobao.com
- 京东长链 item.jd.com/{sku_id}.html / 短链 u.jd.com / 3.cn
- 拼多多长链 yangkeduo.com?goods_id=xxx / 短链 p.pinduoduo.com
- 关键词提取: 从 【标题】/「标题」/ "标题" 中提取搜索词
- 优先级: 口令 > 短链 > 长链 > 纯ID

### Reverse Compare Model (src/models.py)
- ReverseCompareResult: 原品信息 + 全网同款 + 最优推荐 + 可省金额 + LLM 摘要

### MCP Tool (src/server.py)
- parse_and_compare(raw_text, page_size): 分享文本 → 解析 → 查原品 → 提取关键词 → 跨平台比价 → 报告

### Tests (tests/test_parsers.py)
- 25 new tests (total 59/59 passed)
- 淘宝/京东/拼多多链接提取 (13 tests)
- 混合文本 + 关键词提取 (7 tests)
- parse_and_compare E2E (5 tests)
