---
name: price-hunter
description: "全网比价聚合搜索 — 淘宝联盟/京东联盟/多多进宝 MCP Server"
triggers:
  - price hunter
  - 比价
  - 全网比价
  - 聚合搜索
  - 淘宝联盟
  - 京东联盟
  - 多多进宝
  - 优惠券搜索
---

# Price Hunter Skill

## 概述

Price Hunter 是一个基于 FastMCP 的全网比价聚合搜索服务，对接三大电商联盟 API:
- **淘宝联盟** (Taobao客 TOP API) — MD5 签名
- **京东联盟** (JD Union Open Platform) — MD5 签名
- **多多进宝** (PDD Open Platform) — HMAC-SHA256 签名

## 项目位置

```
~/price-hunter/
```

## 运行方式

```bash
cd ~/price-hunter
uv sync                    # 安装依赖
uv run python -m src.server  # 启动 MCP Server (stdio)
```

## MCP Tools

| Tool | 参数 | 说明 |
|------|------|------|
| `search_products` | keyword, platform?, page?, page_size? | 跨平台商品搜索 |
| `get_product_detail` | product_id, platform | 单品详情 + 优惠券 |
| `compare_prices` | keyword, page_size? | 多平台比价排序 |
| `get_coupons` | keyword, platform?, page? | 优惠券搜索 |

## 配置

凭据通过环境变量或 `.env` 文件注入 (参见 `.env.example`)。

## 开发阶段

- Phase 1 ✅ 脚手架 + 安全基线
- Phase 2 🔜 API 签名算法与请求实现
- Phase 3 🔜 比价核心逻辑与 MCP Tool 完整注册

## 架构决策

- **pydantic-settings** 管理凭据，避免硬编码
- **BaseEngine 抽象** 统一三平台接口 (search / detail / get_coupons)
- **MD5 vs HMAC-SHA256** 签名工具内置，子类选择
- **httpx 异步客户端** 支持并发跨平台查询
