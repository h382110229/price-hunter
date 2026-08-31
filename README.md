# 🎯 Price Hunter — 全网比价聚合搜索服务

基于 MCP (Model Context Protocol) 的全网比价聚合引擎，对接淘宝联盟、京东联盟、多多进宝三大电商联盟 API，提供统一的商品搜索、优惠券查询与跨平台比价能力。

## 架构

```
Client (LLM / Agent)
  │  MCP Protocol (stdio / SSE)
  ▼
MCPServer (server.py)
  │
  ├── config.py          # pydantic-settings 凭据加载
  ├── models.py          # 统一数据模型 (Product, Coupon, CompareResult)
  └── engines/
      ├── base.py        # 引擎基类 (签名、重试、Mock/Dry-run)
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
# 编辑 .env 填入联盟 API Key（见下方生产配置）

# 3. 检查连通性
uv run python scripts/check_keys.py

# 4. 启动 MCP Server
uv run python -m src.server
```

## 生产配置

三大联盟 API 凭据获取指南详见 [docs/union_api_guide.md](docs/union_api_guide.md)。

`.env` 文件格式：

```
TB_APP_KEY=你的淘宝AppKey
TB_APP_SECRET=你的淘宝AppSecret
TB_ADZONE_ID=你的推广位ID

JD_APP_KEY=你的京东AppKey
JD_APP_SECRET=你的京东AppSecret
JD_SITE_ID=你的推广位SiteID

PDD_CLIENT_ID=你的拼多多ClientID
PDD_CLIENT_SECRET=你的拼多多ClientSecret
PDD_PID=你的推广位PID
```

### 连通性探测

```bash
uv run python scripts/check_keys.py
```

输出示例：

```
╔══════════════════════════════════════════════════════╗
║       Price Hunter — 联盟 API 连通性探测             ║
╠══════════════════════════════════════════════════════╣

  🟢  淘宝联盟 (TOP API)
     已连通 — 返回 1 条结果
  🟡  京东联盟 (JD Union)
     未配置 (Dry-run 运行中)
  🔴  多多进宝 (PDD DDK)
     签名错误: ...

╠══════════════════════════════════════════════════════╣
║  汇总: 🟢 1 连通  🟡 1 未配置  🔴 1 失败    ║
╚══════════════════════════════════════════════════════╝
```

| 图标 | 含义 |
|------|------|
| 🟢 | 真实 API 已连通 |
| 🟡 | 未配置凭据 (Dry-run 模式) |
| 🔴 | 鉴权失败 / 签名错误 / 网络错误 |

## MCP Tools

| Tool | 说明 |
|------|------|
| `search_products` | 跨平台商品搜索 (并发) |
| `get_product_detail` | 单品详情 + 优惠券信息 |
| `compare_prices` | 多平台比价 (并发 + 排序 + 摘要) |
| `get_coupons` | 按商品/关键词搜索优惠券 |

## 容错机制

- **自动重试**: 网络超时/连接失败自动重试 2 次 (指数退避 1s → 3s)
- **错误分类**: 明确区分「未配置密钥」「网络超时」「签名错误」「限流」
- **Mock/Dry-run**: 无凭据时自动返回真实结构的模拟数据，测试无需 API Key
- **生产级超时**: 连接 5s、读取 10s

## 开发状态

- Phase 1 ✅ 工程脚手架与安全基线
- Phase 2 ✅ 三大平台联盟 API 签名算法与比价核心
- Phase 3 ✅ MCP 接入与端到端验证
- Phase 4 ✅ 生产级错误处理与连通性探测

## License

MIT
