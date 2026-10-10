Enco X4 OPKG structure toolkit — 2026-10-08

阅读 report.html 获取字段表、哈希范围、内存映射及未解决事项。
运行环境：Python 3.10 或更新版本，标准库，无需安装第三方包。

检查固件：
  python opkg_tool.py inspect "sAnN-16128-1_all_112_0"

提取原始镜像和独立压缩块：
  python opkg_tool.py unpack "sAnN-16128-1_all_112_0" unpacked112

导出 EQ 参数和指针表：
  python opkg_tool.py profiles "sAnN-16128-1_all_112_0" --json profiles112.json

比较同长度底包：
  python opkg_tool.py compare "sAnN-16128-1_all_112_0" "third113.bin" --json diff113.json

用原包做模板回封装修改后的等长 raw.bin：
  python opkg_tool.py repack "sAnN-16128-1_all_112_0" edited_raw.bin rebuilt.opkg

回封装默认保留原包版本号、未知字段及所有未修改压缩块；更新压缩大小、
块 CRC32、原始镜像哈希、压缩内容哈希及包级哈希。输出必须是新的路径。
工具不会自动改变版本返回函数、SW_VER 或 OPKG 版本字段，也不会刷写设备。

复现本次验证：
  python validate_samples.py "official112" "official116" "third113" "third101"
四个路径按官方112、官方116、第三方113、第三方101的顺序填写。
验证过程只读输入；单参数修改测试仅在内存执行。

证据文件：
  evidence/*_layout.json       四个样本的布局、哈希、构建信息
  evidence/*_profiles.json     每个样本184份配置，含全部18个槽位和指针表索引
  evidence/112_to_*_diff.json  连续差异范围及修改配置清单
  evidence/eq_filters.csv      便于筛选的全部滤波器参数（含非激活槽位）
  evidence/eq_profile_diff.csv 配置级变化汇总
  evidence/validation.json    离线验证结果
  evidence/*_q.txt / *_p*.txt  APK包头解析器和数据类的DEX指令证据
  evidence/y8_d$d.txt          APK发送升级元数据的DEX指令证据
  evidence/arm_layout_evidence.txt 主固件初始化/指针表选择代码

type_id 的枚举名称、EQ表索引与界面模式的对应关系尚未完全确定。
other/india 是固件日志中的地区分支；output1/output2 是函数输出指针编号，
没有将其命名为左右耳或低高音单元。
本工具完成离线格式验证，没有验证设备端对刷包的接受、升级版本策略或音效。
