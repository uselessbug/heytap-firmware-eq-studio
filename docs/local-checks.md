# 通用测量与拟合新版（2026-10-09）

已配置的自用便携包解压后运行 EXE，保持 `_internal` 完整；点击“获取在线测量”，不需要 APK、手机或手填认证。当前 GitHub 通用构建未内置认证：用户 2026-10-09 已明确授权提交共享令牌，但平台自动审批拒绝公开发布凭据，提交尚未成功。功能版本仍为 1919bef；没有新构建。

1. 首次进入来源/品牌/型号应为空。选择 Woodenears 或任一服务返回来源，搜索型号并载入测量。
2. 可以从“目标曲线库”读取在线目标，或导入目标 CSV/JSON/HAR；另一副耳机的测量可点“当前实测设为目标”。
3. 选原始与目标条件，点“生成修正 EQ”，选择 RAW 或 PEQ、频段、强度、最大提升、PEQ 数量和整体电平对齐。结果可撤销，也可导出 EQ 文本。拟合指标对应平滑/限幅后的期望修正，44.1/48/96 kHz 分别重算。
4. 查看原始/目标/估计的独立开关、1 kHz 对齐显示与绝对 SPL、数字 EQ ±12/24/48 dB、复位和参数面板收起。拖动 RAW/PEQ 节点仍可编辑。
5. 保存工程、关闭重开，应恢复测量、目标与选中条件。重新连接后恢复上次来源/品牌/型号。首次打开已确认 Enco X4 固件时可按服务顺序寻找唯一精确匹配；未知机型不猜名称。
6. 回传 SOURCE_SHA.txt、窗口截图及任何操作异常。当前拟合结果是外部 EQ 修正；GUI 尚未写入固件。

下面保留上一阶段的历史验证和 APK 诊断，仅用于研究复现；新版程序运行与构建均不依赖 APK。

# 当前桌面阶段的本地验证

本阶段可用：完整性检查、已知 Enco X4 指纹/指针识别、现有记录只读查看、两类 EQ 导入、PEQ 表格编辑、RAW 纵向拖动、PEQ 频率/增益拖动、撤销重做、绑定固件 SHA 的原子工程保存/自动恢复、CSV/JSON/ReaLab HAR 测量和声学估计。

未知布局可显式扫描合理参数和可能指针；候选没有名称或写入权限。

本阶段尚未开放桌面固件导出或版本修改。原 CLI 研究工具保持可用，不把历史 32 项测试算作桌面覆盖。在线 sources / 品牌 / 型号 / Enco X4 测量已成功验证；其他来源仍需按实际响应处理。

## Windows 程序

从对应 Actions 运行下载 `HeyTapFirmwareEQStudio-windows-<SHA>`，解开产物内的 ZIP，运行 `HeyTapFirmwareEQStudio.exe`。必须保留同目录 `_internal`。

1. 打开官方 116，核对版本 116、产品 06EC10、完整性、四张路径表和每个预设九个状态。
2. 导入两份 Technics EQ。RAW 应为 127 点，优化版应为 5 个 PEQ。
3. 修改 PEQ、拖动 RAW 节点，确认撤销重做；保存工程、关闭重开，确认恢复。重新打开原固件会核对 SHA。
4. 点击“连接 Flowmix (APK)”选原 Beta 5-10 APK，选择 ReaLab → OPPO → OPPO Enco X4 后载入在线测量；应看到五条各 127 点。断网后可回退已有缓存，离线文件导入仍可进行。
5. 导入原 ReaLab HAR，确认五条 B&K 5128 曲线。实测和估计分开，数字 EQ 在独立页签。
6. 回传 `SOURCE_SHA.txt`、启动/操作异常信息，以及窗口截图。不要在此阶段刷写耳机。

## Flowmix 567 诊断（无需 Python）

已从这个 APK 确认：`Lnw0.b` 添加 Authorization Bearer；`Lnw0.a` 将请求限制到 `fr-api.ykload`，检查已有 Authorization / fr-token / frToken，支持四种认证枚举。依赖的默认 User-Agent 为 `okhttp/5.3.2`。该共享凭据不是自用户账号推测而来；用户已要求内置提交，但平台自动审批拦截了该写入；下面的 APK 诊断仅供历史请求复现。

下载仓库 `scripts/flowmix-probe.ps1` 后，在 PowerShell 运行（替换本地 APK 路径）：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\flowmix-probe.ps1 -Apk "D:\Downloads\Flowmix-Beta-5-10.apk" -Output flowmix-cn-auth.json
```

脚本只接受已研究的 APK 哈希，临时提取测量 Bearer，通过 stdin 交给 curl，仅 GET `/api/sources`；不跟随重定向、不输出凭据，响应中若回显凭据会脱敏。`ExecutionPolicy Bypass` 只用于这个进程，不修改系统策略。

若仍然 567，最多补充这两个对照请求，不要批量重试：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\flowmix-probe.ps1 -Apk "D:\Downloads\Flowmix-Beta-5-10.apk" -Anonymous -Output flowmix-cn-anon.json
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\flowmix-probe.ps1 -Apk "D:\Downloads\Flowmix-Beta-5-10.apk" -BaseHost fr-api.ykload.com -Output flowmix-com-auth.json
```

请回传诊断 JSON，以及同一网络的 Flowmix App 是否能实际加载来源/型号。脚本不包含 Cookie 或设备/用户访问令牌。若响应包含个人信息，请删除后再提供。

已有 Python 开发环境时可改用：

```powershell
python -m heytap_eq.flowmix --apk "D:\Downloads\Flowmix-Beta-5-10.apk" --output flowmix-cn-auth.json
```

当前环境完整复现 Bearer + okhttp/5.3.2 已取得四级 200 JSON；同 UA 匿名为 403。若本地仍为 567，使用上述脚本与同网络 App 对照即可，无需再次取得已经验证过的基础合同。
