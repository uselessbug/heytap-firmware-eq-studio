# HeyTap Firmware EQ Studio

面向 OPPO / HeyTap 耳机固件的本地 EQ 研究与编辑项目，首个适配对象为 Enco X4。

计划采用 **Python + PySide6 + pyqtgraph**：一个本地桌面程序，解析、拟合、可视化和封包均在同一 Python 工程中完成。

## 当前提交状态

本分支首先保存已确认的格式、映射、接口和本地验证记录。完整桌面程序源码、测试源码、示例 EQ 及 Actions 配置尚未包含在此提交中；当前仓库内容不能直接启动 GUI 或生成修改后的固件。

本地已完成桌面实现和核心验证，但上传前执行环境离线，无法读取源码或继续完成打包检查。后续提交应以源码、可重跑测试和成功的 CI 为交付依据。

## 已确认的研究结果

- Enco X4 112 / 116 的 OPKG 结构、EQ 参数区、四组指针表、预设名称和选择映射。
- Wavelet GraphicEQ 与 Flowmix RAW + PEQ 两种输入的用途与转换边界。
- Flowmix APK 中的公开测量服务域名、七个只读接口和响应模型。
- 原始测量频响、数字 EQ 增益和修改后的估计声学频响需要分别显示。
- 本地 32 项测试，以及 112 / 116 上两个目标 EQ 共 72 条记录的修改和重新封包验证。

## 文档

- [固件结构、名称映射与编辑边界](docs/firmware-format.md)
- [EQ 输入和频响处理](docs/eq-formats.md)
- [Flowmix 测量接口](docs/flowmix-api.md)
- [相关开源项目](docs/related-projects.md)
- [本地验证记录](docs/local-validation.json)

## 桌面工具的实现目标

- 导入固件、扫描已有 EQ、显示预设名称和数字滤波响应。
- 导入 GraphicEQ 和 Flowmix RAW + PEQ；拖动曲线节点、编辑 PEQ 参数、撤销/重做。
- 在四组输出路径及九个内部状态上拟合替换 EQ，检查容量、稳定性和拟合误差。
- 导入 ReaLab HAR / HTML、CSV / JSON 测量数据，显示原始测量与 EQ 叠加估计。
- 编辑已确认的版本和文本元数据；未知、自动计算或布局相关字段保留为只读。
- 保存与输入固件 SHA 绑定的工程文件；导出新固件和修改报告。
- 对未知机型或变化后的布局扫描候选表；未经验证的选择逻辑保持只读。
- Linux / Windows CI、GUI 启动检查和 Windows 打包。

原厂固件、完整 APK、HAR 以及凭据不应提交到此公开仓库。
