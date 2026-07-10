<img src="assets/logo.png" width="72" align="left" alt="logo"/>

# X-COM+ 串口调试助手

复刻 XCOM 的跨平台串口调试工具（Python + PySide6 + pyserial），自用向，只保留与串口收发直接相关的功能。

## 功能

**串口设置**：端口枚举/刷新，波特率（常用档位 + 任意自定义），数据位 5~8，停止位 1/1.5/2，校验位 无/奇/偶/Mark/Space，流控 无/RTS-CTS/XON-XOFF，DTR/RTS 电平控制，编码 UTF-8/GBK。

**接收（日志区，常驻界面上方）**
- 16 进制显示、时间戳显示（每包前缀 `[HH:MM:SS.mmm]`）切换时已收数据整体重渲染
- 停止显示（暂停刷新但继续计数）、清除接收、保存窗口到 txt
- 增量解码，中文等多字节字符跨包接收不乱码
- 接收缓冲 1MB、显示 5 万行/8M 字符上限，长时间挂机内存不膨胀

**单条发送**：16 进制发送、发送新行（\r\n）、定时发送（周期可设）、清除发送；文件发送一组：打开文件/发送文件/停止发送 + 实时进度条（流式分块，不卡界面）。

**多条发送**
- 标签分组：标签行末尾 "+" 号添加，右键标签重命名/删除，双击重命名
- 标签内分页：每页 10 条命令（左右两列各 5 条），命令编号随页全局递增；
  页操作：页码 x/y、移除此页、添加页、首页/上一页/下一页/尾页、页码跳转
- 每条命令独立 HEX 勾选与发送按钮；发送新行选项（默认开）；循环发送轮发当前页非空命令
- 编辑条目：表格批量编辑当前标签全部命令（HEX/指令/描述），可清空、导入/导出 INI（.ini）
- 所有标签/页/命令自动保存到 `xcom_multisend.json`，重启恢复

**状态栏**：串口状态、RX/TX 字节计数、复位计数。

## 运行

需要 Python 3.8+（推荐 3.10+）。

**快捷启动**：Windows 双击 `启动.bat`（用 pythonw 启动，无控制台黑框），Linux/macOS 运行 `./start.sh`（首次会自动安装依赖）。

**手动启动**：

```bash
pip install -r requirements.txt
python run.py
```

## 打包成 exe（Windows）

双击 `打包exe.bat`，等待完成后在 `dist\X-COM+.exe` 得到单文件程序——
双击直接运行、无控制台窗口、自带图标、无需安装 Python，可复制到任意电脑使用。

- 首次打包会自动安装 PyInstaller，耗时几分钟；产物约 60~80MB（内含 Qt 运行库）
- 打包后 `xcom_multisend.json` / `xcom_error.log` 保存在 exe 所在目录
- 个别杀毒软件可能对 PyInstaller 单文件误报，添加信任即可

Windows 下若报 `DLL load failed`，安装微软 VC++ Redistributable（vc_redist.x64.exe）。
程序异常时会弹窗并把完整 traceback 写入 `xcom_error.log`。

## 项目结构

```
├── run.py                  # 入口（含全局异常捕获）
├── requirements.txt
├── 开发说明书.md            # 设计与功能范围说明
└── xcom/
    ├── serial_manager.py   # 串口打开/关闭 + 后台收数线程
    ├── main_window.py      # 主窗口：日志区、串口设置、单条发送
    └── multi_send.py       # 多条发送：标签 + 分页 + 持久化
```

生成的本地文件（已 gitignore）：`xcom_multisend.json` 多条发送配置，`xcom_error.log` 异常日志。
