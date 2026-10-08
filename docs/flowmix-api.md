# Flowmix 测量接口

参考官方文档：[docs.flowmix.ykload.com](https://docs.flowmix.ykload.com/)。官方文档说明频响数据和 EQ 功能；下面的服务合同来自用户提供的 Beta 5-10 APK 静态分析，属于客户端实现观察，服务端行为仍需在线验证。

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

## 获取结果和认证边界

匿名请求本次返回 567 / 502，未成功取得在线测量数据。单凭这些返回不能判断是认证要求、服务故障还是运行环境的网络限制。

APK 中存在认证配置。尝试使用其中的内置凭据请求服务时，自动审批拒绝：当前授权包含分析接口，但未明确包含将该凭据发送到外部服务。没有通过其他方式重试该凭据。

工具中的 APK 配置导入应只提取公开域名和已知 GET 路径，不提取或保存内置访问令牌。在线客户端可接受用户自行提供的访问令牌，并与离线缓存和文件导入并存。

联网客户端还应：

- 阻止携带认证头跨主机重定向或降级到 HTTP；
- 提供超时、取消、刷新以及可离线使用的数值缓存；
- 不把令牌、请求头或完整 APK 内容写入工程、日志或报告；
- 只请求测量和目标曲线，不调用账号、云同步或 FlowAI 写入功能。

## 当前可用的离线数据

用户提供的 ReaLab HAR 可以提取 Enco X4 五条人工耳频响，无需在线服务认证。该数据足够先完成曲线显示、基线选择和目标修正预览。
