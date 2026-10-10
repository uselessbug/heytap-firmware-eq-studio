# DSSSP 图形编辑区

默认页面为「频响与调音」，「数字 EQ／固件链」保留两路 DSP 预览。
输出路径、内部状态和预览采样率收进「高级预览」；它们不会改变整个预设的写入范围。

- 双击空白图形：在鼠标频率处添加 PEQ；增益按该处现有曲线计算增量。
- 拖动绿色圆点：频率和增益实时预览；松手后记录一次撤销。
- 在绿色点上滚轮：调 Q；右键：打开类型、频率、增益、Q、启用和删除面板。
- 黄色小点：只编辑 RAW 增益，维持原采样频率。
- 空白处滚轮：围绕鼠标位置缩放频率；Shift＋滚轮：纵向缩放。
- 拖动空白处：平移；「复位视图」恢复 20 Hz—20 kHz 和所选 dB 范围。
- 普通编辑和曲线显隐不复位视野；切换测量或对齐方式时重新设置范围。

Python 计算修正与固件滤波器响应。DSSSP 0.8.0 负责 SVG 绘图与交互，
没有使用其内置滤波器公式代替 Python DSP。传入的非等距测量曲线会按当前
对数频率视野重新插值；坐标标签随视野重新生成。空工程没有示例曲线。

频响估计仍表示「所选实测＋当前修正」，没有从固件自动推导物理单元的声学响应。
例如第三方 113 独立修改 output1/output2 并更改高通截止参数，不能把两路 dB
直接相加当作耳机频响。固件数字链仍单独标注「不含整体增益」。

## 构建与检查

Windows 便携包已经包含网页资源和 Qt WebEngine，使用者不需要 Node 或浏览器服务器。
源码开发先在 `frontend` 运行 `npm install`、`npm run build`，再启动 Python。
Actions 自动构建资源，再执行 Node 数学检查、Linux Chromium 鼠标交互检查、
Linux/Windows Python 与真实 Qt WebChannel 检查，最后启动实际冻结 Windows EXE。

打包使用 `--collect-data heytap_eq`；启动检查要求网页握手完成并实际生成 SVG 曲线，
不能只凭窗口打开判定成功。截图与 JSON 检查报告随 Actions 产物保存。

前端依赖为 DSSSP（MIT）、React/React DOM（MIT）；构建时保留依赖许可说明，
并将 DSSSP LICENSE 随本地资源一起打包。引入 Qt WebEngine 后便携包会比原版大。

源码：`frontend/src/editor.jsx`、`frontend/src/math.mjs`、`src/heytap_eq/web_plot.py`。
