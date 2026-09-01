## Summary

实现三大电商联盟 API 对接、签名计算与跨平台比价排序逻辑。

## Changes

### Models (src/models.py)
- Product: 新增 coupon_amount, final_price(自动计算), url, coupon_url, tkl_or_command, sales 字段
- CompareResult: 新增 min_price_product、按 final_price 升序自动排序、LLM 友好的 Markdown 摘要

### Engines (src/engines/)
- base.py: 独立 md5_sign() / pdd_sign() 签名函数；Mock/Dry-run 降级机制（无 Key 时返回真实结构的模拟数据）
- taobao.py: taobao.tbk.dg.material.optional 完整解析 — 面价、隐藏券、券后价、淘口令、月销量
- jd.py: jd.union.open.goods.query 完整解析 — priceInfo/couponInfo/promotionInfo、领券短链
- pdd.py: pdd.ddk.goods.search 完整解析 — 分→元转换、隐藏补贴券、佣金比例(‱→%)

### Server (src/server.py)
- 迁移至 MCP 2.x (MCPServer)
- asyncio.gather 并发跨平台搜索
- compare_prices: 并发聚合 + 全局排序 + 比价摘要

### Tests (tests/test_engines.py)
- 34 tests, all passing ✅
- 签名算法: 8 tests (确定性、顺序无关、已知向量)
- 数据模型: 8 tests (自动计算、排序、摘要、序列化往返)
- 引擎 Dry-run: 9 tests (search/detail/get_coupons × 3平台)
- MCP Tool 格式: 9 tests (结构、筛选、错误处理)

### DevOps
- MCP SDK v1 → v2 迁移
- 新增 pytest + pytest-asyncio 开发依赖
- asyncio_mode=auto 配置
