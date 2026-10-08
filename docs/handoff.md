# HeyTap Firmware EQ Studio 交接文档

更新时间：2026-10-08（Asia/Shanghai）。此文档可直接交给后续对话继续开发。

## 当前桌面交付状态（2026-10-08）

最新功能提交：`180c96236f77d341dc6f15aa0cda24c8a1e7f16e`。所有源码均通过连接器保存在 `feat/python-desktop-studio`，沿用草稿 PR #1；main 未合并。

- 已实现：独立 OPKG 核心及完整性检查、已知 Enco X4 完整代码指纹/四表识别、只读固件 EQ 和元数据、通用 Wavelet/Flowmix 八类型与稀疏 ID、RAW/PEQ 拖动、滤波器表、撤销重做、绑定输入 SHA 的原子工程/自动恢复、未知布局候选扫描、CSV/JSON/ReaLab HAR、数字/实测/估计曲线分开展示。
- Actions https://github.com/uselessbug/heytap-firmware-eq-studio/actions/runs/37782348640 全部成功：Linux、Windows 各 21 项测试及 Ruff；源码 GUI 启动；Windows 便携包生成；真实冻结 EXE 启动。报告核对 frozen=true、Qt 6.8.3、正确源 SHA、5 个合成 RAW 点/1 PEQ/1 测量。
- Windows 便携 ZIP 产物为 `HeyTapFirmwareEQStudio-windows-180c96236f77d341dc6f15aa0cda24c8a1e7f16e`，103,965,785 字节。已查看冻结启动截图：中文、图表、控件及表格正常显示。用户本机 Windows 操作仍待确认。
- 未完成：桌面完整预设拟合/受限固件导出、同步版本与 getter 补丁、元数据写入、完整在线来源/品牌/型号浏览和缓存、测量随工程恢复、长期任务取消、实机验证。当前外部 EQ 编辑不等于已写入固件。保留 CLI 仍可按原 README 生成/校验计划。
- Flowmix 新发现：测量拦截器使用 Authorization Bearer；UA 为 okhttp/5.3.2。原匿名请求不足以复现 APK 请求。完整复现 Bearer + 该 UA 后 sources、brands、headphones 和 Enco X4 测量均为 200；详细合同见 docs/flowmix-live-validation.json。本地诊断脚本临时读用户选定的哈希匹配 APK，不硬编码或保存令牌。执行与回传内容见 `docs/local-checks.md`。
- 真实附件已经按完整路径重新下载：官方 112/116、RAR、Flowmix APK、ReaLab HAR。RAR 实际两份文件名/哈希与当前读取结果见 `docs/current-input-validation.json`。二进制原附件未提交。

下一个阶段从本地诊断结果接入在线浏览；并复用/模块化原 CLI 的拟合计划与实际误差重算，构建受限导出。版本 getter 必须重新核对实际指令并建立仿真，不依据历史报告直接写入。

## 1. 恢复时事实与交接入口（当前桌面状态见文首）

- 仓库：https://github.com/uselessbug/heytap-firmware-eq-studio
- 工作分支：`feat/python-desktop-studio`。
- 草稿 PR：https://github.com/uselessbug/heytap-firmware-eq-studio/pull/1 。尚未合并。
- 已恢复并推送 36 项旧文件：34 个文本文件、2 个完整工具包 ZIP；其中包含 11 个 Python 源文件。另有机器可读的 `research/recovery-manifest.json`。
- 第一批源码提交：`19eb7ff1c1d52862455fed62a1ed7fad7a386492`。
- 完整工具包归档提交：`9f49f0162a4a14721b67355faaa9081c006aa48d`。
- 36 项恢复文件的 Git blob SHA-1 已与本地原字节逐项核对。源文件保持原字节，没有把重写代码当作恢复结果。

**完整 PySide6 桌面源码尚未恢复。** 原工作路径 `/workspace/scratch/74819c2fd648/heytap-firmware-eq-studio` 在执行环境离线后恢复时不存在。当前同名目录是从旧工具包重新建立的目录，不能认为它包含此前 GUI 实现。

此前对话报告过“32 项 pytest、Ruff 通过”及“修改版本 123 的固件验证通过”，但相关源码、测试文件、GUI 截图和新拟合结果未找到。`docs/local-validation.json` 保留这些历史记录，并标注不可从当前源码复现。**当前可重跑结果请看 `docs/recovered-validation.json`，不要把两阶段结果混为一套验证。**

恢复时可运行部分是 CLI 研究原型。之后已重建桌面只读固件检查、通用 EQ、候选扫描、工程保存、GUI 和 Actions；当前写入/版本/在线浏览仍待完成。

## 2. 用户目标与已决定的技术方向

用户希望做一个本地通用固件 EQ 图形编辑工具，首个适配对象为 OPPO Enco X4。

- 使用 Python 的前端库，把界面和处理逻辑放在同一个本地工程中；不采用前后端分离。
- 之前选型为 **PySide6 + pyqtgraph**，计算使用 NumPy / SciPy。
- 导入固件、显示现有 EQ，直接拖动曲线或编辑滤波器。
- 导入 Wavelet GraphicEQ 和 Flowmix RAW + PEQ 两种格式。
- 用给定 EQ 覆盖既有预设，覆盖相应输出路径和内部状态。
- 编辑已确认的其他固件信息，包括版本号；自动校验字段由封包程序计算。
- 应对固件 EQ ID / 表索引变化和不同机型：结构扫描、适配器、代码指纹与语义验证。
- 显示人工耳原始测量和修改后的估计频响；方便从 Flowmix 或离线文件取得测量数据。
- 用 GitHub Actions 检查并打包，减少重复安装和本地打包工作。

用户已授权仓库访问和推送当前代码。保持现有工作分支和草稿 PR；没有收到合并 main 的指令。不要上传原厂固件、完整 APK / HAR 或任何访问令牌。

## 3. 已上传源码的位置

| 路径 | 内容与用途 |
| --- | --- |
| `research/enco_x4_eq_toolkit/eq_tool.py` | EQ 解析、RBJ 响应、跨采样率拟合、计划生成、受限替换 |
| `research/enco_x4_eq_toolkit/opkg_tool.py` | OPKG 完整性、LZMA 分块解析及重新封包 |
| `research/enco_x4_eq_toolkit/validate_tool.py` | 使用两个官方样本验证两份 EQ、72 条记录、封包及错误拒绝 |
| `research/enco_x4_eq_toolkit/verify_arm.py` | 用 Unicorn / Capstone 验证实际固件索引与滤波器系数函数 |
| `research/enco_x4_eq_toolkit/extract_realab.py` | 从 HAR 的 HTML 初始数据提取频响数字 |
| `research/enco_x4_eq_toolkit/mapping.json` | 名称、类型、索引与已知输入哈希 |
| `research/enco_x4_eq_toolkit/examples/` | 两份原 EQ 文件及 116 的两份拟合计划 |
| `research/enco_x4_structure/opkg_tool.py` | 更早的 OPKG 研究版本，保留原样 |
| `research/enco_x4_structure/validate_samples.py` | 四个样本的校验、字节一致回包、差异和隔离修改验证 |
| `research/scripts/` | 原始 DEX 扫描、参数扫描和报告生成脚本，共 4 个 Python 文件 |
| `research/archives/enco_x4_eq_toolkit.zip` | 完整 EQ 工具包：包括报告、5 条测量 CSV、反汇编、大型证据和绘图 |
| `research/archives/enco_x4_structure_toolkit.zip` | 完整结构工具包：包括完整参数导出、差异数据和报告 |
| `research/recovery-manifest.json` | 恢复文件的 SHA-256、Git blob SHA-1、大小及缺失说明 |

解开的源码和小型支撑文件可直接浏览；较大的报告、CSV、SVG、PNG 和反汇编保留在原 ZIP 中。两份 `opkg_tool.py` 分属不同阶段，未强行去重。

`research/scripts/` 是历史分析脚本，部分使用原工作路径和分析目录，依赖原输入及派生数据。它们已保存，但不应视为可直接在任意目录运行的应用入口。DEX 脚本还需要 androguard / loguru。

## 4. 原始输入

| 文件 | 说明 |
| --- | --- |
| `sAnN-16128-1_all_112_0` | 官方 112，实际软件版本为 1.1.2 |
| `sAnN-16128-1_all_116_0` | 官方 116，实际软件版本为 1.1.6 |
| `1_all_113_0_oppo_enco_x4_06EC10(6).bin` | 第三方修改固件，来自用户的 RAR |
| `1_all_101_0_oppo_enco_x4_06EC10(7).bin` | 第三方修改固件，来自同一 RAR |
| `欢律_全能版17.6.5-深色模式.apk` | 第三方修改的 HeyTap APK；用于名称与协议研究 |
| `Flowmix-Beta-5-10.apk` | 用于 Flowmix 格式、数据源接口和模型研究 |
| `www.realab.com_Archive [26-10-07 08-25-02].har` | 包含 Enco X4 人工耳测量的 HTML 响应 |
| `Technics-AZ80.txt` | Wavelet GraphicEQ；已在 examples 中保存 |
| `Technics-AZ80-Optimized.txt` | Flowmix RAW + 五个偏好 PEQ；已在 examples 中保存 |

原固件、APK、HAR 需要从用户原附件取得；不包含在 GitHub 源码中。旧工作环境的固件输入位于 `/workspace/scratch/74819c2fd648/inputs/Enco X4/`，这个路径不是新对话必然可访问的备份。

## 5. 两份 EQ 的含义与恢复 CLI 的解析限制

`Technics-AZ80.txt` 含 127 个 `GraphicEQ` 点，是以 Enco X4 丹拿原声为基线拟合 AZ80 频响的修正。

`Technics-AZ80-Optimized.txt` 是 Flowmix 文件：`[RAW]` 中仍为 `GraphicEQ:`，其余为 `[PEQ]` 和 `[METADATA]`。RAW 与原文件有约 0.05 dB 的四舍五入差异，另外叠加：

| PEQ | 频率 Hz | 增益 dB | Q | 类型 |
| --- | ---: | ---: | ---: | --- |
| 1 | 250 | 1.2 | 1.50 | PEAK |
| 2 | 450 | 1.8 | 1.40 | PEAK |
| 3 | 700 | 0.8 | 1.50 | PEAK |
| 4 | 1800 | -2.0 | 1.30 | PEAK |
| 5 | 5800 | 0.5 | 1.00 | PEAK |

`PEQ_COUNT: 5`、`RAW_BANDS: 127`；`SELECTED_PEQ: 0` 仅为界面选择，五个滤波器都参与响应。

保留的研究 CLI 能处理这两个具体附件，但只支持从 1 连续编号的 PEAK / PK PEQ。它不支持稀疏 ID、省略类型、全部 Flowmix 类型或通用 EQ 编辑 / 导出。桌面通用解析器现已支持 PEAK、LS、HS、LP、HP、NOTCH、BAND_PASS、ALL_PASS，验证重复 ID、数量声明和非法数值。无类型的三参数行计划按 Peak 处理。

不能把 127 个点直接写到固件；要拟合到最多 18 个固件滤波器槽。目标是幅度近似，没有验证 Wavelet / Flowmix 的实际 DSP、相位或逐采样等价。

**替换时以匹配路径 / 状态的丹拿原声完整滤波链为基线。** 直接叠加到清亮高音或丹拿高解析原有滤波链会改变用户指定的基准。保留基线 HP / LP / AP，拟合 Peak / Shelf；同时验证 44.1、48、96 kHz。当前质量门限是在路径峰值下 30 dB 范围内 RMS ≤ 0.45 dB、最大误差 ≤ 1.5 dB。

旧 CLI 的整体增益校验限于 -60..0 dB。此前发现原固件部分高解析记录有 +1 dB；重建 GUI / 适配器时应从实际数据制定范围，避免把合法记录判坏。不要不经验证直接放宽其他机型的全部数值。

## 6. 已确认的固件结构与映射

详细文档见 `docs/firmware-format.md`，原始证据在工具包中。

- 已验证为单段 OPKG v1：整包 SHA-256 位于字节 10..41，覆盖 42 至文件末尾；分块带 CRC / SHA 校验。
- 数据块头 32 字节，magic `0x55AA66BB`；原始分块 256 KiB；LZMA-alone 使用 64 MiB 字典。
- 不变的压缩块保留原字节；重新封包需逐项校验，未知扩展保留。
- EQ 共 184 条，每条 300 字节；四张表各 46 个指针，再跟空指针。通过指针取记录。
- 记录为 `<ffI` 加 18 个 `<Ifff`。**槽字段顺序是 type_id、gain_dB、fc_Hz、Q**，不是频率在增益前。
- 四组按顺序为 `other_output2`、`india_output2`、`other_output1`、`india_output1`。没有证据把它们直接命名为左耳 / 右耳。
- 固件滤波器值：0 Low shelf、1 Peak、2 High shelf、3 Low pass、4 High pass、5 All pass；5 不是 Notch。

| 样本 | 原始数据字节数 | EQ 区间，末地址不含 | 四张表的原始数据地址 |
| --- | ---: | --- | --- |
| 112 | 8,717,764 | 0x735758..0x742EF8 | 0x84AE58、0x84AF14、0x84AFD0、0x84B08C |
| 116 | 8,650,680 | 0x724F04..0x7326A4 | 0x83A840、0x83A8FC、0x83A9B8、0x83AA74 |

112 与 116 的整段 EQ 参数字节相同，位置发生变化；已重新验证。第三方 113 对比 112 原始数据变化 20,898 字节，第三方 101 变化 2,455 字节；具体变动见归档证据。

| 名称 | APK modeType | 固件 EQ ID | 每组表内索引 |
| --- | ---: | ---: | --- |
| 丹拿原声 | 42 | 0 | 0..8 |
| 清亮高音 | 46 | 1 | 9..17 |
| 纯享人声 | 28 | 2 | 18..26 |
| 澎湃低音 | 29 | 3 | 27..35 |
| 丹拿高解析 | 43 | 7 | 36..44 |

内部状态到预设内偏移：1→0，2→1，3/4→2，5→3，6→4，7→5，9→6，8→7，14→8。其用户界面子模式名称尚未完整确认。

每预设四组路径 × 九个状态 = 36 条；两个目标共 72 条。特殊标志使用索引 45，保持。未知状态的回退固定索引 8；若目标选丹拿原声，修改记录 8 也会改变回退响应。当前两个目标是丹拿高解析和清亮高音，原声回退记录保持。

## 7. 最新可重跑验证与复现

本次恢复后已重新执行：

1. `validate_tool.py`：两份 EQ 的解析、全部五个 PEQ、全通幅度；112 / 116 各替换 72 条记录；完整性、范围外字节、容量、重叠计划、篡改 HP、伪造误差和损坏输入的拒绝。
2. `validate_samples.py`：四个样本、135 个块的完整性；未修改时字节一致回包；EQ 指针、112 / 116 参数区一致、已知第三方差异、隔离 EQ 修改和损坏校验拒绝。

这些检查均通过，输入原文件保持。CLI **没有改版本号**；输出分别保持 112 / 116。没有实机刷写测试。

快速检查：

```bash
cd research/enco_x4_eq_toolkit
python -m pip install -r requirements.txt
python eq_tool.py mapping
python eq_tool.py inspect examples/Technics-AZ80-Optimized.txt
python validate_tool.py ORIGINAL_112 ORIGINAL_116 --output tool-check.json
```

生成新计划和导出示例：

```bash
python eq_tool.py plan ORIGINAL_116 examples/Technics-AZ80.txt az80.json --target 丹拿高解析
python eq_tool.py plan ORIGINAL_116 examples/Technics-AZ80-Optimized.txt optimized.json --target 清亮高音
python eq_tool.py apply ORIGINAL_116 edited.opkg az80.json optimized.json
```

计划绑定输入哈希。仓库中的 plan116 只用于匹配的 116 样本；112 应重新生成。验证脚本中的重定位针对已确认相同的记录，不是适配新固件的通用做法。生成计划可能需要数分钟，输出必须是新路径。

四样本结构验证在 `research/enco_x4_structure` 目录运行 `python validate_samples.py ORIGINAL_112 ORIGINAL_116 THIRD_113 THIRD_101`。

`verify_arm.py` 需要另外安装 capstone / unicorn，本次恢复后未重新执行；归档中有前一阶段的结果。此前 32 项 pytest 和版本 getter 的 2,000 次仿真也未重新执行。

## 8. 元数据与未知固件适配的重建线索

当前恢复代码不提供完整元数据编辑。此前设计为同步容器版本、嵌入 `SW_VER` 等等宽 ASCII 文本和运行时 getter；还包括 `BUILD_DATE`、`REV_INFO`、已确认的头字段。地址、长度、分区及自动校验值保持只读。

此前记录的版本 getter：112 原始地址 `0xA5958`，116 `0xA6BC8`。计划使用 12 字节 Thumb 补丁写三个数字字节，保留 r1 / r4，并用 000..999 × 对齐 / 未对齐 SRAM 仿真保护相邻字节。补丁源码未恢复，必须重新核对实际指令和调用约定，不能只依据这段文字写入。

未知版本应扫描合理的参数记录与连续指针表，展示候选地址 / 参数，再验证名称、选择逻辑、滤波器公式和 getter。仅发现相似结构不等于已确认可写。

此前适配器设计使用产品 `0x06EC10`、原始数据长度、结构检查、选择函数及系数代码指纹共同判断。已修改 EQ / 文本仍可被已知适配器识别，避免把整包哈希作为唯一可编辑条件。以下指纹来自此前记录，本次已从哈希匹配的官方原始数据重新核对一致；适配器源码仍未恢复：

| 样本 / 区域 | 原始数据范围 | SHA-256 |
| --- | --- | --- |
| 112 选择逻辑 | 0x30E78..0x31074 | b32a48278cf763913b5628d9ef1f945b66ff0b9dd070998ca35a33b5c2978dd0 |
| 116 选择逻辑 | 0x30E78..0x31074 | 5d0cb27c1e6ead6c2bc2b0b295d0d57909df3ca5515956b37cdb1b0d07adfd81 |
| 112 系数代码 | 从 0x147C4C 起 0x700 字节 | e061b11094721c77b44655e1b77b1f2f93b316212b69af61d7c0b8c3f3d865f6 |
| 116 系数代码 | 从 0x14A60C 起 0x700 字节 | 1e40b745cf092e37de58d9150ee54a36152b00fe59685d72a49299ce325ffe16 |

## 9. 测量数据与 Flowmix

官方文档：https://docs.flowmix.ykload.com/ 。详细接口表见 `docs/flowmix-api.md`。

APK 观察到 `cn.ykload.flowmix.network.FrequencyResponseApi`，主域名 `https://fr-api.ykload.cn/`，备选 `https://fr-api.ykload.com/`。七个 GET：

- `/api/sources`
- `/api/sources/{sourceName}/brands`
- `/api/sources/{sourceName}/brands/{brandName}/headphones`
- `/api/sources/{sourceName}/brands/{brandName}/headphones/{headphoneName}`
- `/api/headphones`
- `/api/targets`
- `/api/targets/{targetName}`

模型为 `DataApiResponse(success,data,message)`；耳机数据带来源 / 品牌 / 型号 / lastUpdated / frequencyData；测量条件带 title / frequencies / spl_values。此合同来自 APK，真实联网响应尚未验证。路径参数需逐段编码。

匿名请求返回 567 / 502，不能据此判断服务故障或认证规则。**使用 APK 内置凭据请求外部服务曾被自动审批拒绝**：当时授权含接口分析，但未含凭据对外使用。没有换方式重试。后续应仅从 APK 导入公开域名 / 路径，接受用户自行提供的令牌，或先取得明确的新授权；交接本身不增加凭据使用授权。任何令牌都不能提交 GitHub。

HAR HTML 的初始数据可提取五条 Enco X4 频响：丹拿原声 / 丹拿高解析 / 纯享人声 / 清亮高音 / 澎湃低音；每条 957 个有效点，约 20..19,897 Hz，B&K 5128、ANC 开，日期 2026-09-15。没有对应固件版本和内部 ANC 子状态。

完整 EQ 工具 ZIP 包含这五条 CSV。固件数字 EQ 增益、人工耳实测 SPL、叠加修正后的估计 SPL 需要各自标注。整体声学估计是测量加修正，不能把一条数字滤波响应直接当成耳机频响。

网络客户端的缓存只保存所需数值，不含令牌 / 请求头；阻止认证头跨主机重定向或 HTTP 降级。联网数据获取不能阻塞已有离线导入功能。

## 10. 后续建议执行顺序

1. 先读当前源码、恢复清单和两套验证脚本，确认当前仓库可以复跑的能力。
2. 从 EQ CLI 复用 OPKG / 拟合核心，建立 `src/heytap_eq` 包；补通用 EQ 格式和未知布局只读发现，重建适配器。
3. 重建 Session：与输入 SHA 绑定的工程、暂存修改、撤销 / 重做、完整表 / 状态校验、HP / LP / AP 基线保护和实际误差重算。异常工程恢复应回滚，手动修改后不能保留过期拟合指标。
4. 重建 PySide6 / pyqtgraph 界面：固件路径 / 状态 / 采样率选择、曲线拖动、滤波器表、拟合质量、测量叠加、元数据表；拟合 / 网络 / 导出放后台并支持取消。
5. 实现等宽元数据编辑和经过仿真验证的版本 getter 补丁。新 getter 保持只读直到核实。
6. 重建 `pyproject.toml`、测试、启动 / 打包脚本、Linux / Windows Actions；验证真实样本在本地进行，CI 使用不含厂商数据的合成夹具。
7. 完成 Windows 冻结程序的启动检查和产物上传，更新 PR 的交付状态。

此前拟定模块：`opkg.py`、`adapters.py`、`eq_formats.py`、`dsp.py`、`metadata.py`、`session.py`、`flowmix.py`、`apk_config.py`、`measurements.py`、`plot.py`、`gui.py`、`cli.py`。这些是重建目录线索，不是当前已存在文件。

测试应覆盖格式数量 / 稀疏 ID、RBJ 特殊类型和稳定性、损坏容器、未变压缩块、未知 / 重排指针表、范围外字节保护、项目绑定与回滚、版本补丁寄存器 / 相邻字节、网络重定向以及 GUI 拖动 / 撤销。不要依赖可编辑报告中的自报误差。

此前 PyInstaller 在带系统包的 Linux venv 中发生 Qt 库重复符号链接导致 COLLECT 失败；Windows 未验证。可先检查纯净构建环境并运行冻结后的启动测试。Linux 中文字体检查可用 Noto CJK；此前 GUI 字体 / 截图验证文件未恢复。

同类项目研究见 `docs/related-projects.md`。检索找到固件降级、蓝牙控制、手机模块和固件归档，本次没有找到可直接替代本项目的完整固件 EQ GUI。

本地封包和仿真通过只能确认所测试的格式与代码行为；OTA 接受、双单元实际响应及刷写后的工作状态仍待实机确认。



## 11. 桌面重建阶段（2026-10-08）

已建立 src/heytap_eq 包、最小 Qt Widgets 窗口、锁定版本的干净虚拟环境 CI、Linux/Windows 源码启动探针，以及 Windows PyInstaller 冻结程序的实际启动探针。此阶段源码已保存，CI 结果待 GitHub Actions 返回；不声称旧 32 项测试覆盖本实现。后续接入固件只读检查、通用 EQ、离线测量和工程恢复。

用户已明确授权必要时使用 Flowmix APK 内置凭据进行测量只读请求；任何凭据仍不得入库。此前自动审批拒绝属于旧授权上下文。

### 已保存的桌面里程碑

- `a46fab8c80d10131bebfbb70e33933088993d1d4`：最小工程与 Actions。运行 https://github.com/uselessbug/heytap-firmware-eq-studio/actions/runs/37778955089 三个 job 均成功，包括 Linux / Windows 源码启动、Windows 便携包生成和实际冻结 EXE 启动。此时仅有最小窗口，不能将其当作功能完成。
- 下一阶段引入独立 OPKG 核心、完整代码指纹识别、通用 EQ 导入、三采样率响应、数值测量导入、原子工程保存与恢复、撤销重做。桌面固件当前只读。当前新增测试尚待对应 Actions，不沿用旧验证结果。
- Flowmix Beta 5-10 APK 的 SHA256 为 `79777621b8dd6643f7ab2c0c0c7e77f846a2cb2d6c4ed23b59ac8858798412e2`。已找到混淆后的 FrTokenInterceptor（Lnw0）：请求使用 Authorization Bearer，fr-token 为可选自定义头。当前环境匿名和按 APK Bearer 请求 /api/sources 都得到 567 HTML；令牌值未写入仓库。服务端合同仍未确认。

### 当前桌面功能阶段

已保存独立核心提交 `9abce3514ee7e909a433e5c44ce5759bf49c13d9`；Actions https://github.com/uselessbug/heytap-firmware-eq-studio/actions/runs/37780065614 已成功。随后接入 Qt/pyqtgraph 界面、EQ 导入和编辑、RAW 拖动、撤销重做、原子工程自动恢复、离线测量、数字/实测/估计曲线分开展示，以及安全的 Flowmix 诊断工具。当前 GUI 不写固件；读写拟合链、版本 getter 补丁、未知布局扫描、完整在线浏览和打包视觉 QA 尚待继续。

必要的轻量读取已核对原官方 112/116 的完整文件 SHA、原始数据 SHA、代码指纹、四张表和 184 条记录；优化 EQ 为 127 RAW + 5 PEQ；原 HAR 提取五条各 957 点。新 GUI 测试与冻结程序结果以本阶段 Actions 为准。

本地测量接口与 Windows 操作协助见 `docs/local-checks.md`。已确认 APK 的实际 OkHttp UA 是 `okhttp/5.3.2`；本地脚本同时复现 Bearer 和这个 UA，不将令牌写入仓库。

### 界面补充与诊断验证

`49a758f878cb3623e6fa5fe0ad243bff607d1b3c` 的 Actions https://github.com/uselessbug/heytap-firmware-eq-studio/actions/runs/37781426278 已产生 Windows 便携包及冻结启动报告。后续新增绿色 PEQ 控制点拖动、未知布局只读候选扫描、真实鼠标事件的 RAW 拖动撤销测试、带合成 EQ/测量的启动截图，以及 PowerShell 诊断语法检查。这些补充以最新 Actions 为准。

RAR 解压实际名称和哈希已重新核对：113 的整包 SHA256 为 `ee8674177d6d709d310c66e41167f8765b0140ca6b788ae62ffc8886de1c615a`，101 为 `221a4c47da75dca349ec647434ed9447eed5af1f25524bcc571387870fafd6ea`；四样本均通过轻量完整性读取，详见 `docs/current-input-validation.json`。没有上传这些原始二进制。

当前网络接口只提供脱敏诊断，GUI 在线来源浏览、缓存、拟合/导出后台取消及版本补丁仍未完成。当前已编辑文档属于外部修正目标，不能直接写入固件滤波槽。

### 在线接口实现阶段

已验证 sources 实际 data 为对象列表（name/displayName/description），品牌为字符串列表，型号为对象列表（fileName/originalName）；请求 Enco X4 用 OPPO_Enco_X4。测量五条各 127 点，附 measurement_id/content_version，原 HAR 五条各 957 点。新 FlowmixClient 按真实结构解析，凭据只在内存，缓存只存经验证的索引和测量数值。GUI 来源/品牌/型号选择放独立网络线程，离线文件任务可同时运行；新增合成合同、缓存回退、文件 ID 和线程独立性测试，CI 待对应新提交。固件写入与版本仍未开放。

在线阶段源码提交 `b953c7cf8717458b4213c88be56b24ed59fd1093` 的首轮 CI 在新增并行网络/离线测试中暴露 Qt 崩溃；已按日志改为 MainWindow 的显式 queued Slot 接收线程结束，等待原生线程清理后释放 QThread，并将测试 QApplication 生命周期固定到会话。当前等待修复提交的 Actions；不把失败轮当作验证成功。
