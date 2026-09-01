# Price Hunter — PDD API 集成完整报告 (给 Gemini Review)

## 项目概述

Price Hunter 是一个基于 MCP 的全网比价聚合搜索服务，对接淘宝联盟、京东联盟、多多进宝三大电商联盟 API。

- **GitHub**: https://github.com/h382110229/price-hunter
- **当前分支**: main (commit f55686a)
- **测试**: 59/59 passed (pytest, Mock/Dry-run 模式)
- **语言**: Python 3.12 | 依赖: mcp, httpx, pydantic, pydantic-settings

## PDD API 集成状态

### 可用接口

| 接口 | 状态 | 说明 |
|------|------|------|
| `pdd.ddk.goods.recommend.get` | ✅ 已验证 | 免费，不需要用户授权 |
| `pdd.ddk.goods.search` | ❌ 已下线 | PDD 平台已移除 |
| `pdd.ddk.goods.detail` | ❌ 已下线 | 需用 goods_sign 替代 |

### 关键发现

1. **`pid` 和 `channel_type` 参数会触发"授权备案"检查** — 在未完成备案前，这两个参数必须省略
2. **`goods_sign_list` 必须传 JSON 字符串**（如 `["xxx"]`），不能传 Python 数组
3. **价格单位: 分**（÷100 = 元），**佣金比例: 千分比**（÷10 = 百分比）
4. **`extra_coupon_amount` 与 `coupon_discount` 可能重叠**，不应累加
5. **`goods_id` 已下线**，统一使用 `goods_sign`

### 账号配置状态

| 项目 | 状态 |
|------|------|
| 多多进宝实名认证 | ✅ 审核通过 |
| 多多客ID | 已获取 |
| Client ID 绑定 | ✅ 已绑定 (开发者中心) |
| 媒体登记 | ✅ 社交默认 (审核通过) |
| 推广位 PID | ✅ 已创建 |
| API 签名 | ✅ MD5 验证通过 |
| 推荐 API | ✅ 返回真实商品数据 |

## 代码架构

```
src/
├── config.py              # pydantic-settings 平铺配置
├── models.py              # Product/Coupon/CompareResult/ReverseCompareResult
├── server.py              # MCP Server + 5 个 Tools
├── engines/
│   ├── base.py            # BaseEngine + 签名 + Mock/Dry-run + 重试
│   ├── taobao.py          # 淘宝联盟 (Mock 模式)
│   ├── jd.py              # 京东联盟 (Mock 模式)
│   └── pdd.py             # 多多进宝 (真实 API ✅)
├── parsers/
│   └── link_extractor.py  # 淘口令/链接解析器
└── scripts/
    └── check_keys.py      # 连通性探测 CLI
```

## PDD 引擎实现要点 (pdd.py)

### 签名算法
```python
sign = MD5(secret + sorted_key_value_pairs + secret).upper()
```

### 请求构造
```python
params = {
    "type": "pdd.ddk.goods.recommend.get",
    "client_id": "<CLIENT_ID>",
    "timestamp": str(int(time.time())),
    "data_type": "JSON",
    # 不传 pid 和 channel_type
}
params["sign"] = md5_sign(params, secret)
```

### 响应解析
```python
# 价格: 分 → 元
price = item["min_group_price"] / 100.0
coupon = item["coupon_discount"] / 100.0
final = max(0, price - coupon)

# 佣金: 千分比 → 百分比
commission = item["promotion_rate"] / 10.0

# 商品标识: goods_sign (非 goods_id)
product_id = item["goods_sign"]
```

## 测试覆盖

### 测试套件 (59 tests)

| 类别 | 数量 | 说明 |
|------|------|------|
| 签名算法 | 8 | MD5/PDD 签名正确性 |
| 数据模型 | 8 | Product/CompareResult 序列化 |
| 引擎 Dry-run | 9 | 三平台 Mock 模式 |
| 跨平台比价 | 3 | 并发搜索 + 排序 |
| MCP Tool 格式 | 6 | 返回值结构验证 |
| 链接解析器 | 17 | 淘口令/京东/拼多多链接提取 |
| 反向比价 E2E | 5 | parse_and_compare 端到端 |
| 真实 API | 3 | search/detail/get_coupons (真实数据) |

### 真实 API 测试结果

```
search: ✅ 5 条商品
  1. 官栈即食花胶 — 面价 ¥372 券 ¥192 到手 ¥180
  2. 金纺柔顺剂 — 面价 ¥21.90 券 ¥10 到手 ¥11.90
  3. 贝亲奶瓶 — 面价 ¥233 券 ¥161 到手 ¥72

detail: ✅ 通过 goods_sign 查询成功

get_coupons: ✅ 20 张优惠券
```

## 待解决 / TODO

1. **淘宝联盟 / 京东联盟** — 需要配置真实 API Key
2. **PDD 关键词搜索** — `goods.search` 已下线，`recommend.get` 不支持关键词过滤
3. **PDD 授权备案** — 完成后可启用 `pid` 和 `channel_type` 参数
4. **`extra_coupon_amount`** — 需要确认是否与 `coupon_discount` 重叠

## 安全注意

- `.env` 已在 `.gitignore` 中屏蔽，不会提交到 Git
- 所有凭据通过环境变量注入，代码中无硬编码
- check_keys.py 输出仅显示凭据前 8 位
