# 京东联盟 API 集成诊断报告 (给 Gemini Review)

## 项目概述

Price Hunter 是一个基于 MCP 的全网比价聚合搜索服务，对接淘宝联盟、京东联盟、多多进宝三大电商联盟 API。

- **GitHub**: https://github.com/h382110229/price-hunter
- **当前分支**: main (commit 4232ddd)
- **测试**: 86/86 passed (pytest)
- **PDD**: ✅ 已连通，真实数据

## 京东联盟配置

### 应用信息
- 应用名称: PriceHunter
- 应用ID: 4107684237
- AppKey: c10a6a918fd7dce9ec83575302f23fbe
- App Secret: eccb386f7acf4bfab083f4798660b9cb
- 证书流量: 300,000 次/天
- 已用流量: 12 次
- 应用等级: V0 (0单量, 0 GMV, 0 UV)

### 授权 Key
```
fb9d3a21926c0282758c3ff02b3fbee258f015db1f772619a2486faf11c7f3d22cf3ae7be5a07242
有效期: 2027-09-01
```

## API 测试结果

### 测试1: 无 access_token (标准签名方式)
```json
{
  "jd_union_open_goods_query_responce": {
    "code": "0",
    "queryResult": "{\"code\":403,\"message\":\"无访问权限\",\"requestId\":\"o_0672b5a8_mtibppaq_1677839\"}"
  }
}
```
- 外层 code: "0" (调用成功)
- 内层 code: 403 (无访问权限)

### 测试2: 使用 access_token
```json
{
  "error_response": {
    "code": "19",
    "zh_desc": "token已过期或者不存在，请重新授权",
    "en_desc": "Invalid access_token"
  }
}
```
- code: 19 (token 过期或不存在)

### 测试3: 使用 key 参数
```json
{
  "jd_union_open_goods_query_responce": {
    "code": "0",
    "queryResult": "{\"code\":403,\"message\":\"无访问权限\"}"
  }
}
```

## 代码实现

### 请求格式 (jd.py)
```python
params = {
    "method": "jd.union.open.goods.query",
    "app_key": "c10a6a918fd7dce9ec83575302f23fbe",
    "timestamp": "2026-09-01 15:06:03",  # YYYY-MM-DD HH:MM:SS (北京时间)
    "format": "json",
    "v": "1.0",
    "sign_method": "md5",
    "param_json": "{\"goodsReqDTO\":{\"keyword\":\"测试\",\"pageIndex\":1,\"pageSize\":3}}"
}
# 签名: MD5(secret + sorted_kv + secret).upper()
params["sign"] = jd_sign(params, "eccb386f7acf4bfab083f4798660b9cb")
```

### 响应解析
- 外层 code "0" 或 200 = 调用成功
- 内层 queryResult.code = 业务状态码

## 平台状态

| 平台 | 状态 | 说明 |
|------|------|------|
| 淘宝联盟 | 🟡 Mock | 未配置凭据 |
| 京东联盟 | 🔴 403 | 凭据有效，API 权限未开通 |
| 多多进宝 | 🟢 已连通 | 真实数据 |

## 疑问

1. 京东联盟 API 权限是否需要单独申请？还是应用等级升到 V1 后自动开通？
2. access_token 是否需要通过 OAuth 流程获取？还是可以直接在平台领取？
3. 应用等级 V0 是否意味着无法调用任何 API？
4. 是否有其他方式可以绕过403 限制？

## 参考链接

- 京东联盟开放平台: https://union.jd.com/openplatform
- API 文档: https://union.jd.com/openplatform/api
- OAuth 授权指南: https://open.jd.com/v2/#/doc/guide?listId=533

## 代码仓库

- GitHub: https://github.com/h382110229/price-hunter
- 当前分支: main (commit 4232ddd)
- 测试: 86/86 passed
- PDD 真实 API: ✅ 已连通
