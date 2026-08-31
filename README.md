# 🎯 Price Hunter — 全网比价聚合搜索服务

基于 FastMCP (Model Context Protocol) 的全网比价聚合引擎，对接淘宝联盟、京东联盟、多多进宝三大电商联盟 API，提供统一的商品搜索、优惠券查询与跨平台比价能力。

## 架构

```
Client (LLM / Agent)
  │  MCP Protocol (stdio / SSE)
  ▼
FastMCP Server (server.py)
  │
  ├── config.py          # pydantic-settings 凭据加载
  ├── models.py          # 统一数据模型 (Product, Coupon, CompareResult)
  └── engines/
      ├── base.py        # 引擎抽象基类 (签名、请求、解析)
      ├── taobao.py      # 淘宝联盟 TOP API
      ├── jd.py          # 京东联盟 API
      └── pdd.py         # 多多进宝 API
```

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置凭据
cp .env.example .env
# 编辑 .env 填入联盟 API Key

# 3. 启动 MCP Server
uv run python -m src.server
```

## MCP Tools

| Tool | 说明 |
|------|------|
| `search_products` | 跨平台商品搜索 |
| `get_product_detail` | 单品详情 + 优惠券信息 |
| `compare_prices` | 多平台比价 |
| `get_coupons` | 按商品/关键词搜索优惠券 |

## 开发状态

Phase 1 ✅ 工程脚手架与安全基线
Phase 2 🔜 三大平台联盟 API 签名算法实现
Phase 3 🔜 比价核心逻辑与 MCP Tool 注册

## License

MIT
