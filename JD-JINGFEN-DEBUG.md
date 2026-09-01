# 京东联盟 jingfen.query 参数调试报告 (给 Gemini)

## 测试结果

| 接口 | 返回码 | 说明 |
|------|--------|------|
| `goods.query` | 403 | 需 V1 等级 |
| `goods.jingfen.query` | 400 | 接口可访问，参数格式错误 |
| `goods.bigfield.query` | 400 | 同上 |
| `goods.promotiongoodsinfo.query` | 403 | 需 V1 等级 |

## 关键发现

`jingfen.query` 返回 400 而非 403，说明接口已开通，不需要 V1 等级。

## 已尝试的 param_json 格式 (全部 400)

```python
# 格式1: goodsReq 嵌套
{"goodsReq": {"eliteId": 22, "pageIndex": 1, "pageSize": 10, "sortName": "price", "sort": "asc"}}

# 格式2: goodsReq + 字符串 eliteId
{"goodsReq": {"eliteId": "22", "pageIndex": 1, "pageSize": 10}}

# 格式3: 仅 eliteId
{"goodsReq": {"eliteId": 22}}

# 格式4: 顶层参数
{"eliteId": 22, "pageIndex": 1, "pageSize": 10}

# 格式5: goodsReqDTO
{"goodsReqDTO": {"eliteId": 22, "pageIndex": 1, "pageSize": 10}}

# 格式6: request
{"request": {"eliteId": 22, "pageIndex": 1, "pageSize": 10}}

# 格式7: 加 pid
{"goodsReq": {"eliteId": 22, "pageIndex": 1, "pageSize": 3, "pid": "4107684237_c10a6a91_4107684237"}}

# 格式8: 空对象
{}

# 以上全部返回: {"code": 400, "message": "参数错误"}
```

## 请求格式

```
POST https://api.jd.com/routerjson?method=jd.union.open.goods.jingfen.query&app_key=c10a6a918fd7dce9ec83575302f23fbe&timestamp=2026-09-01+15:34:18&format=json&v=1.0&sign_method=md5&param_json={"goodsReq":{"eliteId":22,...}}&sign=XXXX
```

## 签名验证

- 签名算法: MD5(secret + sorted_kv + secret).upper()
- 不含 param_json 的签名 → 请求被拒 (code=None)
- 含 param_json 的签名 → 400 参数错误
- 结论: 签名正确，问题在参数格式

## 应用信息

- AppKey: c10a6a918fd7dce9ec83575302f23fbe
- SiteID: 4107684237
- 等级: V0
- 流量: 300,000次/天

## 疑问给 Gemini

1. `jingfen.query` 的 `param_json` 是否需要特殊的编码方式？
2. 是否需要 `access_token` 参数？（文档说"否"但实际可能需要）
3. V0 等级是否真的能调用 `jingfen.query`？
4. 是否有其他不需要 V1 等级的京东联盟 API？
