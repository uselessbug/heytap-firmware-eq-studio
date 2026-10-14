Enco X4 EQ 离线研究工具 — 2026-10-08

阅读 report.html 查看格式、名称映射、曲线、拟合误差与验证边界。
本工具只处理已核实的官方 112 / 116 样本，不连接耳机。
依赖 Python 3.10+、numpy、scipy。运行时以本目录为工作目录。

安装：
  python -m pip install -r requirements.txt

查看名称映射：
  python eq_tool.py mapping

查看输入解析：
  python eq_tool.py inspect examples/Technics-AZ80-Optimized.txt

生成计划（用自己的官方 112 或 116 原封包替换 ORIGINAL）：
  python eq_tool.py plan ORIGINAL examples/Technics-AZ80.txt az80.json --target 丹拿高解析
  python eq_tool.py plan ORIGINAL examples/Technics-AZ80-Optimized.txt optimized.json --target 清亮高音

可选 --preamp-db -3 等，为两个处理路径统一衰减；默认 0，保留基准增益。
工具总是以丹拿原声的同一状态记录作为基准，不会叠加目的预设原有音染。
计算可能持续几分钟，会打印当前拟合的路径与状态。计划包括所有参数和误差。

离线重封装：
  python eq_tool.py apply ORIGINAL edited.opkg az80.json optimized.json

不改版本号。输出必须是新文件。工具拒绝低质量拟合及格式错误。
examples/az80_plan116.json 和 optimized_plan116.json 为本次提供的 116 样本生成；
只对输入哈希一致的封包有效。112 请重新生成计划。
固件和输出封包未打包；这是导入/拟合/重封装研究原型，不是已实测的刷机发行包。

完整记录格式：
  +0x00 <float32 gain0_dB>
  +0x04 <float32 gain1_dB>
  +0x08 <uint32 count>
  +0x0C 18 × <uint32 type_id, float32 gain_dB, float32 fc_Hz, float32 Q>
  小端，记录总长 300 字节。
  类型：0 低架，1 峰值，2 高架，3 低通，4 高通，5 全通。
  名称和表内范围（每张表相同）：
    丹拿原声     protocol_id=0, modeType=42, 索引 0–8
    清亮高音     protocol_id=1, modeType=46, 索引 9–17
    纯享人声     protocol_id=2, modeType=28, 索引 18–26
    澎湃低音     protocol_id=3, modeType=29, 索引 27–35
    丹拿高解析   protocol_id=7, modeType=43, 索引 36–44
  索引 45 为特殊配置。未知 ANC 内部状态固定落到索引 8，参见 mapping.json。

验证复现：
  python -m pip install capstone unicorn
  python verify_arm.py ORIGINAL_112 ORIGINAL_116 --output arm-check.json
  python validate_tool.py ORIGINAL_112 ORIGINAL_116 --output tool-check.json

HAR 测量提取：
  python extract_realab.py YOUR_CAPTURE.har extracted_measurement
  只保存曲线数字及公开页面字段，不输出 HAR 请求头或 cookies。

边界：
GraphicEQ 的 127 个点按对数频率插值为幅度目标，再合并拟合到 18 段。
原型没有验证 Wavelet/Flowmix 的实际 DSP 实现，不能宣称逐采样等效。
保留低通、高通、全通参数，但峰值/架式段合并可能改变相位。
拟合误差是滤波器幅度误差，不等于实机双单元叠加后的声学误差。
实际 DSP 采样率、硬件量化、完整 ANC 子模式映射、OTA 接受与听感仍待实机确认。
这次 HAR 只有 X4 测量；图中的 AZ80 目标是由补偿推算，不是独立 AZ80 实测。

文件：
  eq_tool.py              解析、拟合、定点覆盖、离线封包
  opkg_tool.py            OPKG 格式、完整性、LZMA 分块重封装
  verify_arm.py           直接执行固件 ARM 索引/系数函数的验证
  validate_tool.py        两版封包、保护范围与错误拒绝集成检查
  extract_realab.py       HAR 的 HTML 频响数据提取
  mapping.json            机器可读的名称、类型与索引映射
  examples/               两份原 EQ 与 116 拟合计划
  measurement/            从 HAR 提取的 5 条频响 CSV
  evidence/               输入哈希、映射配置、反汇编及验证结果
  response_analysis.svg   可单独分享的精确数字图

注意：输入文件来自用户上传；APK 为第三方修改版本。
名称依据该 APK 的内置配置及中文资源，与固件协议选择逻辑核对。
