## Summary

生产级真实联盟 API 联调准备：网络容错增强、业务错误分类、连通性探测脚本、生产接入文档。

## Changes

### Network Resilience (src/engines/base.py)
- httpx.AsyncClient: connect=5s, read=10s 超时 + 连接池限制
- _retry_request(): 网络抖动/5xx 自动重试 2 次 (指数退避 1s → 3s)
- 业务级错误 (ApiBusinessError) 不重试，直接抛出

### Custom Exception Hierarchy
- EngineError → NetworkError (超时/连接失败) / ApiBusinessError (签名/鉴权/限流) / ConfigMissingError
- 日志清晰区分三类错误，避免静默失败

### Per-Platform Business Error Handling
- 淘宝: error_response.sub_code 分类 (Invalid Sign / Unauthorized / 流量限制)
- 京东: result.code + message 分类 (sign/auth/rate-limit)
- 拼多多: error_response.error_code 分类 (10019=签名 / 10001=鉴权 / 10016=限流)

### CLI Probe Script (scripts/check_keys.py)
- 读取 .env，对已配置平台发送极简测试请求
- 输出美化终端检查清单 (green/yellow/red)
- Exit code 1 if any platform has errors

### Documentation
- docs/union_api_guide.md: 免费开发者账号注册 + 凭据获取全流程
- README.md: 生产配置说明 + check_keys.py 用法 + 错误图标说明

### Tests
- 34/34 passed — 现有 Mock/Dry-run 测试不受影响
