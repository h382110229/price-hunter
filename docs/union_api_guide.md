# 联盟 API 生产接入指南

本文档覆盖三大电商联盟（淘宝联盟、京东联盟、多多进宝）的免费开发者账号注册、权限申请与凭据获取流程。

---

## 一、淘宝联盟 (Taobao客 TOP API)

### 1.1 注册与创建应用

1. 访问 [淘宝开放平台](https://open.taobao.com/)，使用淘宝账号登录
2. 进入「控制台」→「创建应用」→ 选择「自用型」
3. 填写应用名称、描述，提交审核
4. 审核通过后，在应用详情页获取：
   - **App Key** → 填入 `.env` 的 `TB_APP_KEY`
   - **App Secret** → 填入 `.env` 的 `TB_APP_SECRET`

### 1.2 申请 API 权限

1. 在应用详情页 → 「API 权限」→ 搜索并申请以下权限：
   - `taobao.tbk.dg.material.optional` (物料搜索)
   - `taobao.tbk.item.info.get` (商品详情)
   - `taobao.tbk.coupon.get` (优惠券查询)
2. 新应用默认有「沙箱环境」权限，正式环境需提交工单申请

### 1.3 创建推广位 (Adzone ID)

1. 访问 [淘宝联盟](https://pub.alimama.com/)，登录
2. 进入「推广管理」→「推广位管理」→「新建推广位」
3. 选择「导购推广」类型，填写推广位名称
4. 获取推广位 PID (格式: `mm_xxx_xxx_xxx`)
5. 提取其中的 **Adzone ID** (PID 最后一段数字) → 填入 `.env` 的 `TB_ADZONE_ID`

---

## 二、京东联盟 (JD Union Open Platform)

### 2.1 注册与创建应用

1. 访问 [京东联盟开放平台](https://union.jd.com/openplatform)，使用京东账号登录
2. 进入「我的工具」→「API 管理」→「创建应用」
3. 填写应用信息，提交审核（通常 1-3 个工作日）
4. 审核通过后获取：
   - **App Key** → 填入 `.env` 的 `JD_APP_KEY`
   - **App Secret** → 填入 `.env` 的 `JD_APP_SECRET`

### 2.2 申请 API 权限

1. 在应用管理页 → 「权限申请」→ 申请以下接口：
   - `jd.union.open.goods.query` (商品查询)
   - `jd.union.open.goods.promotiongoodsinfo.query` (商品详情)
   - `jd.union.open.coupon.query` (优惠券查询)
   - `jd.union.open.promotion.common.get` (推广链接获取)

### 2.3 创建推广位 (Site ID)

1. 在京东联盟首页 → 「推广管理」→「推广位管理」
2. 新建推广位，选择「网站推广」或「APP 推广」
3. 获取 **Site ID** → 填入 `.env` 的 `JD_SITE_ID`

---

## 三、多多进宝 (PDD Open Platform)

### 3.1 注册与创建应用

1. 访问 [拼多多开放平台](https://open.pinduoduo.com/)，使用拼多多账号登录
2. 进入「应用管理」→「创建应用」→ 选择「多多客」类型
3. 填写应用信息，提交审核
4. 审核通过后获取：
   - **Client ID** → 填入 `.env` 的 `PDD_CLIENT_ID`
   - **Client Secret** → 填入 `.env` 的 `PDD_CLIENT_SECRET`

### 3.2 申请 API 权限

1. 在应用详情页 → 「权限管理」→ 申请以下接口：
   - `pdd.ddk.goods.search` (商品搜索)
   - `pdd.ddk.goods.detail` (商品详情)
   - `pdd.ddk.goods.promotion.url.generate` (推广链接)

### 3.3 创建推广位 (PID)

1. 在多多进宝后台 → 「推广管理」→「推广位管理」
2. 新建推广位
3. 获取 **PID** (格式: `mm_xxx_xxx_xxx`) → 填入 `.env` 的 `PDD_PID`

---

## 四、配置与验证

### 4.1 填写凭据

```bash
cd ~/price-hunter
cp .env.example .env
# 编辑 .env，填入上述获取的凭据
```

### 4.2 运行连通性探测

```bash
uv run python scripts/check_keys.py
```

预期输出：

```
╔══════════════════════════════════════════════════════╗
║       Price Hunter — 联盟 API 连通性探测             ║
╠══════════════════════════════════════════════════════╣

  🟢  淘宝联盟 (TOP API)
     已连通 — 返回 1 条结果

  🟡  京东联盟 (JD Union)
     未配置 (Dry-run 运行中)

  🔴  多多进宝 (PDD DDK)
     签名错误: 拼多多签名错误 [10019]: invalid sign

╠══════════════════════════════════════════════════════╣
║  汇总: 🟢 1 连通  🟡 1 未配置  🔴 1 失败    ║
╚══════════════════════════════════════════════════════╝
```

### 4.3 常见问题

| 图标 | 含义 | 解决方案 |
|------|------|----------|
| 🟢 | 真实 API 已连通 | 无需操作 |
| 🟡 | 未配置 (Dry-run 模式) | 编辑 .env 填入凭据 |
| 🔴 签名错误 | App Secret 不正确 | 重新复制 Secret，注意前后空格 |
| 🔴 鉴权失败 | App Key 无效或权限未开通 | 检查 Key 是否正确，API 权限是否审核通过 |
| 🔴 网络错误 | 网络不通或超时 | 检查代理/防火墙设置 |

---

## 五、安全注意事项

1. **永远不要提交 `.env` 文件到 Git** — `.gitignore` 已严格屏蔽
2. **定期轮换 API Secret** — 如怀疑泄露，立即在对应平台重置
3. **限制 API 权限范围** — 只申请需要的接口权限
4. **监控调用量** — 各平台均有日调用量限制，超限会被限流
