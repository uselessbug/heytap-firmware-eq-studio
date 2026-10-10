# Flowmix 测量接口

参考官方文档：[docs.flowmix.ykload.com](https://docs.flowmix.ykload.com/)。官方文档说明频响数据和 EQ 功能；下面的服务合同来自用户提供的 Beta 5-10 APK 静态分析，属于客户端实现观察，来源/品牌/型号/测量和目标接口的实际响应已在线抽样验证，见文末与 flowmix-source-validation.json。

## 服务地址

APK 域名管理配置中的测量服务为：

- 主地址：`https://fr-api.ykload.cn/`
- 备选地址：`https://fr-api.ykload.com/`

接口类为 `cn.ykload.flowmix.network.FrequencyResponseApi`。

## 只读接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | /api/sources | 列出测量来源 |
| GET | /api/sources/{sourceName}/brands | 列出来源中的品牌 |
| GET | /api/sources/{sourceName}/brands/{brandName}/headphones | 列出耳机型号 |
| GET | /api/sources/{sourceName}/brands/{brandName}/headphones/{headphoneName} | 获取该来源、品牌和型号的测量 |
| GET | /api/headphones | 全部耳机索引 |
| GET | /api/targets | 列出目标曲线 |
| GET | /api/targets/{targetName} | 获取目标曲线 |

路径参数需逐段 URL 编码；型号中的空格、斜线、中文不能直接拼接。

## APK 中观察到的模型

- `DataApiResponse`：`success`、`data`、`message`。
- `HeadphoneFrequencyData`：`sourceName`、`brandName`、`headphoneName`、`lastUpdated`、`frequencyData`。
- `frequencyData`：条件名称到 `MeasurementCondition` 的映射。
- `MeasurementCondition`：`title`、`frequencies`、`spl_values`。
- `TargetCurveData`：`name`、`lastUpdated`、`frequencyData`。

解析端应校验数组等长、频率为正且排序、数值有限，并保留来源和条件。驼峰 / 下划线字段兼容属于客户端容错，不意味着服务端两种字段都已确认。

## 当前请求线索（2026-10-08）

用户已明确授权必要时使用所选 APK 的内置凭据进行测量只读请求。重新取得的 Beta 5-10 APK SHA256 为 `79777621b8dd6643f7ab2c0c0c7e77f846a2cb2d6c4ed23b59ac8858798412e2`。

- 混淆后的 `Lnw0.b` 把完整 Bearer 常量添加到 `Authorization`。
- `Lnw0.a` 检查 `fr-api.ykload` 域名、已有 `Authorization`、`fr-token` 自定义头和 `frToken` 查询参数；枚举包括 Bearer、自定义头、查询参数、请求体。当前不需要同时叠加所有认证方式。
- APK 的 OkHttp 默认 UA 字面量为 `okhttp/5.3.2`。没有发现此测量拦截器依赖账号 JWT 或需要自创设备签名的证据。
- 此前匿名/default UA 与 Bearer/default UA 均为 567 HTML。完整复现 Bearer + okhttp/5.3.2 后，四级请求均为 200；同 UA 的匿名对照为 403 JSON。这个对照支持同时需要测量认证和合适 UA；不将所有 567 都归因于同一种安全策略。

用户 2026-10-09 明确要求将该 APK 的共享测量 Bearer 内置提交并随 Actions 成品发布。但平台自动审批拒绝了此次源码写入，认为其属于公开发布凭据，即使已有明确授权；当前 `service_profile.py` 尚未内置默认令牌，仍使用已交付自用配置。`src/heytap_eq/apk_config.py` 保留为已知 APK 的研究/诊断读取工具，不属于运行或构建依赖。`flowmix.py` 按已验证的 sources / brands / headphones 结构和测量数值提供在线浏览、脱敏诊断及数值缓存。Windows 无 Python 诊断见 [本地步骤](local-checks.md) 与 `scripts/flowmix-probe.ps1`。

## 恢复 CLI 阶段的历史认证记录

匿名请求本次返回 567 / 502，未成功取得在线测量数据。单凭这些返回不能判断是认证要求、服务故障还是运行环境的网络限制。

APK 中存在认证配置。尝试使用其中的内置凭据请求服务时，自动审批拒绝：当前授权包含分析接口，但未明确包含将该凭据发送到外部服务。没有通过其他方式重试该凭据。

当时的授权未包含内置凭据对外使用，因此未重试。该历史授权限制已更新：用户允许测量请求，并明确要求将此共享令牌内置提交；该入库操作被平台自动审批阻止，当前状态见上节。工程、数值缓存和诊断报告无需包含请求头或令牌。

联网客户端还应：

- 阻止携带认证头跨主机重定向或降级到 HTTP；
- 提供超时、取消、刷新以及可离线使用的数值缓存；
- 不把令牌、请求头或完整 APK 内容写入工程、日志或报告；
- 只请求测量和目标曲线，不调用账号、云同步或 FlowAI 写入功能。

## 当前可用的离线数据

用户提供的 ReaLab HAR 可以提取 Enco X4 五条人工耳频响，无需在线服务认证。该数据足够先完成曲线显示、基线选择和目标修正预览。


## 已在线验证的合同

2026-10-08，使用已授权的 APK 测量 Bearer + okhttp/5.3.2：

| 请求 | HTTP | 实际 data |
| --- | --- | --- |
| sources | 200 | 6 个对象，name / displayName / description |
| sources/realab/brands | 200 | 106 个品牌字符串 |
| sources/realab/brands/OPPO/headphones | 200 | 10 个对象，fileName / originalName / lastUpdated / sourceName |
| 上一路径 / OPPO_Enco_X4 | 200 | 5 个测量条件，每条 127 点 |

型号路径使用返回的 fileName；不能直接用 originalName 替代。测量条件除 title / frequencies / spl_values 外还含 measurement_id / content_version，已保留。在线数据频率范围 20..19871 Hz，原 HAR 每条 957 点，二者不得声称逐点相同。来源最后更新日期也不等于原始测量日期。

数值摘要见 `docs/flowmix-live-validation.json` 和 `docs/flowmix-source-validation.json`；六个来源（包括 Woodenears）的品牌/型号/测量均已抽样验证，目标索引 21 条及 JM-1 目标也已读取。原完整响应和 APK 没有提交；共享测量令牌的入库要求已获用户明确授权，但被平台自动审批拦截。全量耳机索引尚未验证。GUI 网络任务与离线文件任务独立，网络失败后可回退到已验证的缓存；缓存不含认证信息。
