# HeyTap Firmware EQ Studio

面向 OPPO / HeyTap 耳机固件的本地 EQ 编辑项目，首个研究对象为 Enco X4。

当前可运行部分为 **Python CLI 研究原型**：支持两个给定 EQ 的解析、拟合计划、72 条记录替换及 OPKG 重新封包。恢复出的 11 个 Python 源文件、示例、映射、验证脚本和两个完整工具包已提交。

桌面方向已确定为 **Python + PySide6 + pyqtgraph**。此前完整 GUI 源码、32 项 pytest 和 Actions 配置未恢复，需继续重建。目前没有桌面安装包。

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

## 当前验证

恢复后重新跑通两个脚本：112 / 116 各修改 72 条记录并验证重新封包；四个固件样本共 135 个块通过完整性、字节一致回包、指针和隔离修改检查。新输出保持原版本，尚未实机刷写。

- [当前可重跑验证](docs/recovered-validation.json)
- [前一阶段桌面实现的历史记录](docs/local-validation.json)（源码未恢复，不能当作当前 CI 结果）

## 研究文档

- [固件结构与名称映射](docs/firmware-format.md)
- [EQ 格式与频响](docs/eq-formats.md)
- [Flowmix 测量接口](docs/flowmix-api.md)
- [相关开源项目](docs/related-projects.md)

未来桌面工具需要补齐通用 EQ 导入 / 编辑、测量叠加、元数据修改、工程保存、未知布局只读发现，以及 Linux / Windows CI 和打包。原厂固件、完整 APK / HAR 和访问令牌不提交到本公开仓库。

