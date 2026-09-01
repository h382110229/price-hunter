## Summary

PDD 引擎关键词过滤增强、优惠券逻辑优化、回归测试补充。

## Changes

### Client-side Keyword Filtering (src/engines/pdd.py)
- recommend.get 返回推荐池后，按商品标题匹配关键词
- _tokenize_chinese(): 中文分词 + 2-gram 滑窗
- _keyword_match_score(): 完整包含=1.0，部分命中按比例
- _filter_by_keyword(): 匹配不足时补充热门商品
- 超拉 3x 数据量再过滤，确保结果充足

### Coupon Calculation Fix
- coupon_amount = max(coupon_discount, extra_coupon_amount)
- 避免常规券 + 额外券重叠导致券后价虚高

### Sales Volume Parsing Fix
- "1.2万" → 12000 (之前错误解析为 1)

### New Tests (14 tests, total 73/73)
- TestPDDUnitConversion: 价格/券/佣金单位转换、goods_sign、销量解析 (9 tests)
- TestPDDKeywordFilter: 精确匹配/部分匹配/无匹配回退/空关键词/排序 (5 tests)
