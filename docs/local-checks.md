# 当前桌面阶段的本地验证

本阶段可用：完整性检查、已知 Enco X4 指纹/指针识别、现有记录只读查看、两类 EQ 导入、PEQ 表格编辑、RAW 纵向拖动、撤销重做、绑定固件 SHA 的原子工程保存/自动恢复、CSV/JSON/ReaLab HAR 测量和声学估计。

本阶段尚未开放桌面固件导出或版本修改。原 CLI 研究工具保持可用，不把历史 32 项测试算作桌面覆盖。在线接口尚无成功的真实数据响应。

## Windows 程序

从对应 Actions 运行下载 `HeyTapFirmwareEQStudio-windows-<SHA>`，解开产物内的 ZIP，运行 `HeyTapFirmwareEQStudio.exe`。必须保留同目录 `_internal`。

1. 打开官方 116，核对版本 116、产品 06EC10、完整性、四张路径表和每个预设九个状态。
2. 导入两份 Technics EQ。RAW 应为 127 点，优化版应为 5 个 PEQ。
3. 修改 PEQ、拖动 RAW 节点，确认撤销重做；保存工程、关闭重开，确认恢复。重新打开原固件会核对 SHA。
4. 导入原 ReaLab HAR，确认五条 B&K 5128 曲线。实测和估计分开，数字 EQ 在独立页签。
5. 回传 `SOURCE_SHA.txt`、启动/操作异常信息，以及窗口截图。不要在此阶段刷写耳机。

## Flowmix 567 诊断（无需 Python）

已从这个 APK 确认：`Lnw0.b` 添加 Authorization Bearer；`Lnw0.a` 将请求限制到 `fr-api.ykload`，检查已有 Authorization / fr-token / frToken，支持四种认证枚举。依赖的默认 User-Agent 为 `okhttp/5.3.2`。凭据不是自用户账号推测而来，也未写在源码中。

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

当前运行环境用匿名和 APK Bearer 都收到 HTTP 567 HTML。这个结果不能证明令牌无效，也不能证明 567 来自 Flowmix 服务本身；需与本地请求和 App 比较。成功响应回来之前不将 APK 模型当作真实服务端合同。
