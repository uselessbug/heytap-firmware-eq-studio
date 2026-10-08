# 通用测量与拟合（2026-10-08）

`/api/sources` 的实际响应包含 realab、huihifi、woodenears、hangoutaudio5128、hangoutaudio711、hobbytalk。六个来源均按实际返回的品牌、fileName 与测量条件逐级读取；每个来源已抽样取得 200 JSON，各测量为 127 点。这里的六个名称是验证记录，不是应用白名单。索引跟随服务返回更新。

`/api/targets` 当前返回 21 个对象，路径标识为 fileName，显示名称为 name。已读取 JM-1 目标，data 为 name / lastUpdated / frequencyData。原始测量可以成为目标，因此通用流程不依赖固件或耳机机型。

## APK 拟合线索

研究输入是用户提供的 Beta 5-10 APK，哈希见 flowmix-api.md。DEX 中 Lax1 的 access$calculateFlowEq 与 access$calculatePeqFlowEq 分别调用协程 Ldy1、Ley1。两者取得 MeasurementCondition 的有效频率/SPL、用户频段范围，并调用 access$interpolateSpl；该方法在频率上调用 Math.log。RAW 后续调用 access$smoothEqCurve；PEQ 在对数频率网格上计算差值、找剩余误差，调用 access$calculateOptimalQ 和 access$calculatePeakFilterGain 后递减剩余误差。

这支持“对数插值、频响差值、RAW 平滑与 PEQ 逐步近似”的实现方向。尚未逐指令复刻参数和边界，没有声称与 APK 输出逐点一致。没有发现拟合函数依赖测量服务端的证据。

## 本项目实现

fitting.py 独立于 Qt 和固件适配器。原始与目标仅在共享测量频段内进行对数插值，可按指定频率对齐整体电平；计算目标减原始，施加强度、可选平滑与增益上下限。RAW 保留采样修正；PEQ 采用剩余误差初始化，再用受限 least_squares 优化，并重算所选采样率响应。支持取消。

报告指标对应经过强度/平滑/限幅处理的期望修正，不应称为未经处理目标的声学误差；模拟估计依旧是测量加数字修正。不同测量人工耳的数据不能因为数值拟合就宣称声学一致。

工程 v2 保存测量、目标、选中条件和来源/型号，仍可读取 v1。浏览器记住上次明确选择和各已打开固件的选择；首次无记录为空，已确认机型才提供自动匹配身份，未知固件没有猜测型号。

## 自用内置连接

官方文档提供 https://cos.ykload.com/d/Flowmix/APK/Flowmix-Beta-5-10.apk。已验证该公共分发文件与附件 SHA-256 相同。构建可从这个固定版本临时提取测量认证并随便携包提供；生成配置被 gitignore 排除，不提交 APK 或凭据到源码。开发运行首次连接可自动准备同样配置，之后直接读取本地配置。界面不要求用户手动选择 APK或填写令牌。

核心本阶段已保存；GUI 接入和对应 Actions 验证随后完成。旧 CI 数量不能当作本阶段验证。
