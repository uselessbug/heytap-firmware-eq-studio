# HeyTap Firmware EQ Studio

面向 OPPO / HeyTap 耳机固件的本地 EQ 编辑项目，首个研究对象为 Enco X4。

当前有 **PySide6 + pyqtgraph 本地桌面工程** 与原 **Python CLI 研究原型**。桌面支持固件校验/只读查看、Wavelet / Flowmix EQ 编辑、RAW / PEQ 拖动、撤销重做、包含测量和目标的工程恢复，以及通用频响拟合。

测量来源动态读取（当前六个，含 Woodenears），可以选在线目标、本地目标或另一副耳机的测量，生成 RAW / PEQ 修正。首次使用选择为空，之后记住上次和各固件的选择；已确认机型可精确匹配测量。独立 HTTP 客户端在运行和构建时均不依赖 APK。深色大图使用稳定的音频坐标，实测 / 目标 / 估计可独立显示。原 CLI 保留固件拟合和重新封包能力。

桌面采用 **Python + PySide6 + pyqtgraph**，核心独立于 Qt。源码和 Windows 便携 ZIP 由 GitHub Actions 检查/构建；每个产物记录源 SHA，并实际启动冻结 EXE。桌面固件写入和版本修改尚未开放。此前丢失源码阶段的测试报告未作为当前实现的验证。

## 桌面启动

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate；Linux: source .venv/bin/activate
python -m pip install -r requirements-ci.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m heytap_eq.app
```

Windows 可下载当前工作分支 [Actions](https://github.com/uselessbug/heytap-firmware-eq-studio/actions) 的通用便携程序。当前 GitHub 构建未内置认证；已配置的自用包单独交付，运行时不需要 APK。用户已明确要求将共享测量令牌内置提交，但 2026-10-09 的提交被平台自动审批拦截，尚未完成。详细操作见 [本地验证步骤](docs/local-checks.md)，测量和拟合见 [说明](docs/measurement-fitting.md)。

## 接手开发

请先阅读 [交接文档](docs/handoff.md) 和 [恢复文件清单](research/recovery-manifest.json)。

- [EQ CLI 与说明](research/enco_x4_eq_toolkit/README.txt)
- [OPKG 结构工具](research/enco_x4_structure/README.txt)
- [全部恢复源码](research)
- [完整 EQ 工具包](research/archives/enco_x4_eq_toolkit.zip)
- [完整结构工具包](research/archives/enco_x4_structure_toolkit.zip)

## 快速检查

```bash
cd research/enco_x4_eq_toolkit
python -m pip install -r requirements.txt
python eq_tool.py mapping
python eq_tool.py inspect examples/Technics-AZ80-Optimized.txt
```

计划生成、应用、原输入要求和验证命令见 CLI 的 README。原厂固件未包含在仓库中。当前 CLI 不修改版本号，只支持附件所用的连续编号 Peak PEQ。

## 当前桌面验证

功能提交 `1919bef` 的 [Actions](https://github.com/uselessbug/heytap-firmware-eq-studio/actions/runs/37799038245) 全部成功：Linux / Windows 各 32 项测试、Ruff、源码 GUI，以及 Windows 便携包生成与真实冻结 EXE 启动。截图已检查；详见 [验证记录](docs/desktop-validation.json)。实际测量配置可读取六个来源和 21 条目标。2026-10-09 用户已授权将共享测量令牌提交 GitHub，但平台自动审批拒绝了公开发布凭据的写入，功能源码和已验证构建尚未改变。

## 恢复 CLI 的历史验证

恢复后重新跑通两个脚本：112 / 116 各修改 72 条记录并验证重新封包；四个固件样本共 135 个块通过完整性、字节一致回包、指针和隔离修改检查。新输出保持原版本，尚未实机刷写。

- [当前可重跑验证](docs/recovered-validation.json)
- [前一阶段桌面实现的历史记录](docs/local-validation.json)（源码未恢复，不能当作当前 CI 结果）

## 研究文档

- [固件结构与名称映射](docs/firmware-format.md)
- [EQ 格式与频响](docs/eq-formats.md)
- [Flowmix 测量接口](docs/flowmix-api.md)
- [相关开源项目](docs/related-projects.md)

后续需要补齐固件完整预设拟合/受限导出、元数据修改、未知机型语义验证，以及更多样本和实机验证。原厂固件和完整 APK / HAR 不提交到本公开仓库；用户允许 Flowmix APK 中的共享测量令牌随源码与成品发布，该项入库仍被平台自动审批阻止。


