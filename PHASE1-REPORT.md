# Price Hunter — Phase 1 执行报告

## ✅ 全部完成

| 项目 | 状态 | 详情 |
|------|------|------|
| Python 环境 | ✅ | CPython 3.12.13 via uv (系统 3.9.6 不满足 >=3.10) |
| 核心依赖 | ✅ | mcp 2.1.1, httpx 0.28.1, pydantic 2.13.5, pydantic-settings 2.15.0, python-dotenv 1.2.3 (共 34 包) |
| 安全基线 | ✅ | .gitignore 屏蔽 .env*、.venv/、__pycache__/、*.pyc、.DS_Store；已验证 git check-ignore 通过 |
| GitHub 仓库 | ✅ | https://github.com/h382110229/price-hunter (public, main 分支) |
| Initial Commit | ✅ | fff256a — 15 files, 785 insertions |

## 目录结构

```
price-hunter/
├── .env.example          # 联盟 API 凭据模板 (TB/JD/PDD)
├── .gitignore            # 严格安全屏蔽
├── .python-version       # 3.12
├── README.md             # 项目文档
├── pyproject.toml        # 项目元数据 + 依赖
├── uv.lock               # 锁定依赖版本
├── skill/
│   └── price-hunter.md   # Hermes Agent 原生 Skill 规约
└── src/
    ├── __init__.py
    ├── server.py          # FastMCP 入口 — 4 个 MCP Tools
    ├── config.py          # pydantic-settings 凭据加载
    ├── models.py          # Product / Coupon / CompareResult
    └── engines/
        ├── __init__.py
        ├── base.py        # BaseEngine 抽象 (MD5 + HMAC-SHA256 签名)
        ├── taobao.py      # 淘宝联盟 TOP API 引擎
        ├── jd.py          # 京东联盟 API 引擎
        └── pdd.py         # 多多进宝 API 引擎
```

## 待实现的引擎接口草案

### BaseEngine (base.py)
```python
class BaseEngine(ABC):
    async def search(keyword, page, page_size) -> list[Product]   # 搜索
    async def detail(product_id) -> Product                        # 详情
    async def get_coupons(keyword, page) -> list[Coupon]           # 优惠券
    def _sign(params) -> str                                       # 签名
    def _md5_sign(params, secret) -> str                           # 淘宝/京东
    def _hmac_sha256_sign(params, secret) -> str                   # 拼多多
```

### MCP Tools (server.py)
| Tool | 接口 | 说明 |
|------|------|------|
| `search_products` | keyword, platform?, page?, page_size? | 跨平台搜索 |
| `get_product_detail` | product_id, platform | 单品详情 |
| `compare_prices` | keyword, page_size? | 比价排序 |
| `get_coupons` | keyword, platform?, page? | 优惠券搜索 |

## Phase 2 待办 (联盟 API 签名算法)

1. **淘宝联盟** — TOP API MD5 签名 + taobao.tbk.dg.material.optional 响应解析
2. **京东联盟** — JD Union MD5 签名 + jd.union.open.goods.query 响应解析
3. **多多进宝** — PDD HMAC-SHA256 签名 + pdd.ddk.goods.search 响应解析
4. 各引擎 detail() 和 get_coupons() 完整实现
5. compare_prices() 跨平台去重与最优排序逻辑
