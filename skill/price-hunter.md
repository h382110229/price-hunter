---
name: price-hunter
description: "全网比价聚合搜索 — 淘宝联盟/京东联盟/多多进宝 MCP Server。支持关键词搜索比价、分享链接/淘口令反向找同款。"
triggers:
  - price hunter
  - 比价
  - 全网比价
  - 聚合搜索
  - 淘宝联盟
  - 京东联盟
  - 多多进宝
  - 优惠券搜索
  - 找同款
  - 反向比价
  - 淘口令
  - ￥.*￥
  - item.jd.com
  - yangkeduo.com
  - m.tb.cn
  - p.pinduoduo.com
  - 这个链接便宜吗
  - 帮我比价
---

# Price Hunter Skill

## 概述

Price Hunter 是基于 MCP 的全网比价聚合搜索服务，对接三大电商联盟 API：
- **淘宝联盟** (Taobao客 TOP API) — MD5 签名
- **京东联盟** (JD Union Open Platform) — MD5 签名
- **多多进宝** (PDD Open Platform) — MD5 签名

## 项目位置

```
~/price-hunter/
```

## 触发路由

| 用户意图 | 优先调用 Tool |
|---------|-------------|
| "比价耳机"、"搜索充电宝" | `mcp_price_hunter_compare_prices` / `mcp_price_hunter_search_products` |
| 粘贴淘口令 `￥XXX￥` | `mcp_price_hunter_parse_and_compare` |
| 粘贴京东链接 `item.jd.com/xxx` | `mcp_price_hunter_parse_and_compare` |
| 粘贴拼多多链接 `yangkeduo.com/xxx` | `mcp_price_hunter_parse_and_compare` |
| "这个链接便宜吗"、"帮我找同款" | `mcp_price_hunter_parse_and_compare` |
| "查优惠券" | `mcp_price_hunter_get_coupons` |
| "商品详情" | `mcp_price_hunter_get_product_detail` |

**关键规则**: 当用户直接粘贴包含链接/口令的文本时，**必须**调用 `parse_and_compare` 而非手动解析。

## MCP Tools

| Tool | 参数 | 说明 |
|------|------|------|
| `search_products` | keyword, platform?, page?, page_size? | 跨平台商品搜索 |
| `get_product_detail` | product_id, platform | 单品详情 + 优惠券 |
| `compare_prices` | keyword, page_size? | 多平台比价排序 |
| `get_coupons` | keyword, platform?, page? | 优惠券搜索 |
| `parse_and_compare` | raw_text, page_size? | **分享链接/口令解析 + 全网找同款比价** |

### parse_and_compare 详解

输入一段包含链接/口令的分享文本，自动：
1. 从文本中提取平台标识 (淘口令/京东链接/拼多多链接)
2. 查询原品详情获取标题和价格
3. 提取核心关键词
4. 跨平台并发搜索全网同款
5. 输出比价报告：原品价格 vs 全网最低价 + 可省金额

支持的链接格式：
- 淘口令 `￥XXXXX￥` / `₤XXXXX₤`
- 淘宝短链 `m.tb.cn/h.xxx` / 天猫 `detail.tmall.com/...id=xxx`
- 京东 `item.jd.com/{sku_id}.html` / `u.jd.com/xxx` / `3.cn/xxx`
- 拼多多 `yangkeduo.com/goods.html?goods_id=xxx` / `p.pinduoduo.com/xxx`

## 配置

凭据通过环境变量或 `.env` 文件注入 (参见 `.env.example`)。

### 连通性检查

```bash
cd ~/price-hunter && uv run python scripts/check_keys.py
```

## 开发阶段

- Phase 1 ✅ 脚手架 + 安全基线
- Phase 2 ✅ 三大平台联盟 API 签名算法与比价核心
- Phase 3 ✅ MCP 接入与端到端验证
- Phase 4 ✅ 生产级错误处理与连通性探测
- Phase 5 ✅ 链接/口令解析器 + 反向比价
- Phase 6 ✅ Skill 路由更新 + E2E 实测

## 架构决策

- **pydantic-settings** 管理凭据
- **BaseEngine 抽象** + Mock/Dry-run 降级
- **asyncio.gather** 并发跨平台查询
- **_retry_request** 网络自动重试 (2次, 指数退避)
- **extract_links** 正则解析淘口令/短链/长链
- **ReverseCompareResult** 反向比价模型 (原品 + 全网 + savings)
