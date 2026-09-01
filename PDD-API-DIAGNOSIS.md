# Price Hunter Phase 7 — PDD API 授权备案诊断报告

## 当前状态

| 项目 | 状态 | 详情 |
|------|------|------|
| .env 配置 | ✅ | PDD_CLIENT_ID / SECRET / PID 已写入 |
| 签名算法 | ✅ | API 能识别凭据（HTTP 200，非签名错误） |
| 账号类型 | ✅ | 多多客权限包已开通 |
| 应用状态 | ✅ | PriceHuter 已正式上线 |
| 媒体登记 | ✅ | ID 11280619064「社交默认」审核通过 |
| PID 创建 | ✅ | 44738016_317748083「多多分享」已关联媒体 |
| API 调用 | ❌ | 返回 50001 错误 |

## PDD API 完整错误响应

```json
{
  "error_response": {
    "error_msg": "业务服务错误",
    "sub_msg": "未传入已经授权备案过的相关参数(pid/custom_parameters)，授权备案说明链接：https://jinbao.pinduoduo.com/qa-system?questionId=204",
    "sub_code": "20001",
    "error_code": 50001,
    "request_id": "17881578129756333"
  }
}
```

## 已尝试的排查步骤

1. ✅ 确认签名正确 — API 返回的不是签名错误
2. ✅ 确认账号已绑定 — 错误从"非多多客"变为"pid/custom_parameters未授权备案"
3. ✅ 确认 pageSize>=10 — 通过参数校验
4. ❌ custom_parameters + pid — 同样报错
5. ❌ 仅 custom_parameters — 同样报错
6. ❌ pid 仅前半部分 — "用户PID不正确"（说明完整PID格式是对的）

## 平台配置截图确认

- open.pinduoduo.com 应用详情页: 已上线，有多多客权限包
- open.pinduoduo.com 授权管理: "可授权账号：不限"，表格为空，无添加入口
- jinbao.pinduoduo.com 媒体登记管理: 媒体ID 11280619064「社交默认」审核通过
- jinbao.pinduoduo.com 推广位管理: PID 44738016_317748083「多多分享」已创建

## 请求参数 (完整)

```json
{
  "type": "pdd.ddk.goods.search",
  "client_id": "7ee584673906496ca659781cc049565e",
  "timestamp": "1788157812",
  "data_type": "JSON",
  "keyword": "纸巾",
  "page": "1",
  "page_size": "10",
  "pid": "44738016_317748083",
  "sort_type": "6",
  "sign": "<MD5签名>"
}
```

## 疑问

1. PDD 的"授权备案"具体指什么操作？进宝网站和开放平台均无明确入口
2. 开放平台「授权管理」页面为空且"添加账号"不可操作，是否需要额外步骤？
3. 是否需要通过 OAuth 授权流程获取 access_token 才能使用 DDK API？

## 参考链接

- PDD 开放平台: https://open.pinduoduo.com
- PDD 进宝网站: https://jinbao.pinduoduo.com
- 授权备案说明: https://jinbao.pinduoduo.com/qa-system?questionId=204
- DDK API 文档: https://open.pinduoduo.com/application/document/api?id=pdd.ddk.goods.search

## 代码仓库

- GitHub: https://github.com/h382110229/price-hunter
- 当前分支: main (commit 9bb93c1)
- 测试: 59/59 passed
