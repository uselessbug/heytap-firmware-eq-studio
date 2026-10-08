# HeyTap Firmware EQ Studio

面向 OPPO / HeyTap 耳机固件的本地 EQ 编辑项目，首个研究对象为 Enco X4。

当前有 **PySide6 + pyqtgraph 本地桌面工程** 与原 **Python CLI 研究原型**。桌面提供固件校验/只读查看、通用 Wavelet 与 Flowmix EQ 导入编辑、RAW 拖动、撤销重做、工程自动恢复，以及人工耳测量/估计展示。Flowmix 在线来源/品牌/型号浏览已按真实响应接入，并提供离线数值缓存。原 CLI 保留拟合和重新封包能力。

桌面采用 **Python + PySide6 + pyqtgraph**，核心独立于 Qt。源码和 Windows 便携 ZIP 由 GitHub Actions 检查/构建；每个产物记录源 SHA，并实际启动冻结 EXE。桌面固件写入和版本修改尚未开放。此前 32 项测试属于源码未恢复的历史结果。

## 桌面启动

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate；Linux: source .venv/bin/activate
python -m pip install -r requirements-ci.txt
python -m pip install --no-deps --no-build-isolation -e .
python -m heytap_eq.app
```

Windows 可下载当前工作分支 [Actions](https://github.com/uselessbug/heytap-firmware-eq-studio/actions) 的便携程序。详细操作与 Flowmix 本地诊断见 [本地验证步骤](docs/local-checks.md)。

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

最新功能提交 `546ea97` 的 [Actions](https://github.com/uselessbug/heytap-firmware-eq-studio/actions/runs/37785516338) 已成功：Linux / Windows 各 25 项测试与 Ruff、源码启动，以及 Windows 便携包和真实冻结 EXE 启动。对应 [验证记录](docs/desktop-validation.json)。冻结截图已检查；本机操作见 [本地验证步骤](docs/local-checks.md)。

## 恢复 CLI 的历史验证

恢复后重新跑通两个脚本：112 / 116 各修改 72 条记录并验证重新封包；四个固件样本共 135 个块通过完整性、字节一致回包、指针和隔离修改检查。新输出保持原版本，尚未实机刷写。

- [当前可重跑验证](docs/recovered-validation.json)
- [前一阶段桌面实现的历史记录](docs/local-validation.json)（源码未恢复，不能当作当前 CI 结果）

## 研究文档

- [固件结构与名称映射](docs/firmware-format.md)
- [EQ 格式与频响](docs/eq-formats.md)
- [Flowmix 测量接口](docs/flowmix-api.md)
- [相关开源项目](docs/related-projects.md)

后续需要补齐完整预设拟合/受限导出、元数据修改、未知机型语义验证，以及其他在线源/目标曲线验证。原厂固件、完整 APK / HAR 和访问令牌不提交到本公开仓库。


