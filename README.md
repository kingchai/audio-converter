# 声转 SONORA

一个基于 Flask 与 FFmpeg 的在线音频转 MP3 工具。支持拖拽和批量上传常见音频、视频文件，可选择输出码率，并在转换完成后下载单个 MP3 或打包下载全部结果。

## 功能特性

- 批量上传与异步转换，实时展示每个任务的转换进度
- 统一输出 MP3，支持 `128`、`192`、`320 kbps`
- 支持从常见视频容器中提取音轨
- 单文件下载与多文件 ZIP 打包下载
- 按浏览器会话隔离任务，其他会话无法读取或下载结果
- 使用 FFprobe 预检文件，拒绝损坏或无法识别的媒体
- 自动清理过期的输入文件、输出文件和任务记录
- 内置请求限流、上传限制、超时控制和统一错误响应
- 提供健康检查与能力查询接口
- 支持通过 Nginx 部署在 `/audio/` 子路径
- 响应式中文界面，无需前端构建步骤

## 支持格式

输入格式：

`WAV`、`M4A`、`AAC`、`FLAC`、`OGG`、`OGA`、`WMA`、`AIFF`、`AIF`、`MP3`、`MP4`、`MOV`、`WebM`

输出格式：

`MP3`（libmp3lame，保留源文件元数据，写入 ID3v2.3）

## 默认限制

| 项目 | 默认值 |
| --- | ---: |
| 单个文件大小 | 200 MB |
| 单次上传总大小 | 500 MB |
| 单次文件数量 | 10 个 |
| 可选输出码率 | 128 / 192 / 320 kbps |
| 转换超时 | 900 秒 |
| 文件与任务保留时间 | 30 分钟 |
| 并行转换线程 | 2 |
| 单个 IP 请求频率 | 30 次/分钟 |

以上限制均由后端校验，其中大部分可以通过环境变量调整。

## 技术栈

- Python 3.10+
- Flask 3.1.1
- Gunicorn 23.0.0
- FFmpeg / FFprobe
- 原生 HTML、CSS、JavaScript
- Nginx + systemd（生产部署示例）

## 项目结构

```text
audio-converter/
├── app/
│   ├── api/
│   │   └── routes.py          # 转换、状态查询和下载 API
│   ├── services/
│   │   ├── converter.py       # FFmpeg 调度、校验、进度与清理
│   │   └── job_store.py       # 线程安全的内存任务存储
│   ├── static/
│   │   ├── index.html         # 单页界面
│   │   ├── app.js             # 上传、轮询与下载交互
│   │   └── styles.css         # 页面样式
│   ├── __init__.py            # Flask 应用创建与错误处理
│   ├── config.py              # 环境变量配置
│   └── errors.py              # 业务异常定义
├── deploy/
│   ├── audio-converter.service
│   └── nginx.conf
├── instance/jobs/             # 临时输入和转换结果
├── .env.example
├── requirements.txt
└── wsgi.py
```

## 快速开始

### 1. 获取源码

```bash
git clone https://github.com/kingchai/audio-converter.git
cd audio-converter
```

### 2. 安装 FFmpeg

macOS：

```bash
brew install ffmpeg
```

Ubuntu / Debian：

```bash
sudo apt update
sudo apt install ffmpeg
```

安装后确认两个命令均可用：

```bash
ffmpeg -version
ffprobe -version
```

### 3. 创建 Python 环境

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell 激活虚拟环境时使用：

```powershell
.venv\Scripts\Activate.ps1
```

### 4. 设置开发环境变量

应用直接读取进程环境变量，本地运行不会自动加载 `.env` 文件。至少建议设置随机的 `SECRET_KEY`：

```bash
export SECRET_KEY="dev-secret-change-me"
export SESSION_COOKIE_SECURE=false
```

### 5. 启动服务

```bash
python wsgi.py
```

浏览器访问：<http://127.0.0.1:8010>

健康检查：

```bash
curl http://127.0.0.1:8010/health
```

当 `ffmpeg_available` 和 `ffprobe_available` 均为 `true` 时，服务已具备转换能力。

## 环境变量

可复制 `.env.example` 作为生产配置起点：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SECRET_KEY` | `change-this-secret-before-production` | Flask 会话签名密钥；生产环境必须替换 |
| `SESSION_COOKIE_SECURE` | `false` | HTTPS 部署时设为 `true` |
| `JOB_DIR` | `instance/jobs` | 临时文件目录 |
| `FFMPEG_BIN` | `ffmpeg` | FFmpeg 命令或绝对路径 |
| `FFPROBE_BIN` | `ffprobe` | FFprobe 命令或绝对路径 |
| `MAX_FILE_SIZE` | `209715200` | 单文件最大字节数 |
| `MAX_TOTAL_SIZE` | `524288000` | 单次请求最大总字节数 |
| `MAX_FILES` | `10` | 单次最大文件数 |
| `JOB_TTL_SECONDS` | `1800` | 非转换中任务的保留时间 |
| `CONVERSION_TIMEOUT_SECONDS` | `900` | 单个转换任务超时 |
| `MAX_WORKERS` | `2` | FFmpeg 转换线程数 |

所有数值型配置必须是大于 `0` 的整数。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 根路径健康检查 |
| `GET` | `/api/health` | API 健康检查 |
| `GET` | `/api/capabilities` | 查询格式、码率与上传限制 |
| `POST` | `/api/convert` | 使用 `multipart/form-data` 创建批量转换任务 |
| `GET` | `/api/convert/<job_id>` | 查询任务状态和进度 |
| `DELETE` | `/api/convert/<job_id>` | 删除非转换中的任务及文件 |
| `GET` | `/api/download/<job_id>` | 下载已完成的 MP3 |
| `POST` | `/api/download-batch` | 将多个已完成任务打包为 ZIP 下载 |

创建转换任务示例：

```bash
curl -c cookies.txt -b cookies.txt \
  -F "files=@example.wav" \
  -F "bitrate=192" \
  http://127.0.0.1:8010/api/convert
```

接口使用 Flask 会话识别任务所有者。后续查询和下载请求需要携带创建任务时获得的 Cookie。

任务状态包括：

- `queued`：等待转换
- `converting`：转换中
- `success`：转换成功
- `error`：转换失败

## 生产部署

仓库提供了 systemd 与 Nginx 示例，默认安装位置为 `/opt/projects/audio-converter`，Python 虚拟环境为 `/opt/projects/venv`。

### 1. 准备配置

```bash
cp .env.example .env
```

编辑 `.env`，至少替换 `SECRET_KEY`，并在 HTTPS 环境保持：

```dotenv
SESSION_COOKIE_SECURE=true
```

确保运行服务的用户对 `JOB_DIR` 具有读写权限。

### 2. 安装 systemd 服务

根据服务器的实际用户、目录和虚拟环境路径检查 `deploy/audio-converter.service`，然后执行：

```bash
sudo cp deploy/audio-converter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now audio-converter
sudo systemctl status audio-converter
```

示例服务使用一个 Gunicorn 进程和四个请求线程：

```text
gunicorn --workers 1 --threads 4 --timeout 960 --bind 127.0.0.1:8010 wsgi:app
```

### 3. 配置 Nginx

将 `deploy/nginx.conf` 中的片段加入目标站点的 `server` 块。示例会把 `/audio/` 代理到 `127.0.0.1:8010`，同时将请求体上限和代理读写超时与应用配置对齐。

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 运行说明

- 任务元数据存储在当前进程内存中，Gunicorn 必须保持单 worker；多进程会导致轮询或下载请求找不到任务。
- 服务重启后，内存中的任务记录会丢失。临时文件会保留到后续清理或人工清理。
- 上传文件只用于本次转换。输入文件在转换结束后删除，输出文件和任务默认在最后更新时间 30 分钟后清理。
- 过期清理在收到请求时触发，并且最多每 60 秒检查一次；服务长时间完全空闲时，文件可能保留到下一次请求到来。
- ZIP 批量包在内存中生成，大批量高码率结果会增加进程内存占用。
- 生产环境应使用 HTTPS、随机长 `SECRET_KEY`，并限制临时目录权限。
- 当前限流数据保存在进程内存中，适合单实例 MVP；若水平扩展，建议改用 Redis 等共享存储。

## 常见问题

### 健康检查显示 FFmpeg 不可用

确认 `ffmpeg`、`ffprobe` 已安装并位于 systemd 服务的 `PATH` 中；也可以将 `FFMPEG_BIN` 和 `FFPROBE_BIN` 配置为绝对路径。

### 上传时返回 413

同时检查三处限制：应用的 `MAX_TOTAL_SIZE`、Nginx 的 `client_max_body_size`，以及单文件 `MAX_FILE_SIZE`。

### 转换任务一直查询不到

请确认查询请求携带了创建任务时的会话 Cookie，并确认 Gunicorn 只启动了一个 worker。

### 部署在子路径后静态资源或接口 404

请完整使用仓库中的 `deploy/nginx.conf` 片段，并保留 `/audio` 到 `/audio/` 的重定向规则。

## 开发建议

在提交改动前，至少检查：

```bash
python -m compileall app wsgi.py
```

如需将服务扩展为多实例或支持重启恢复，建议将任务元数据迁移到 Redis 或数据库，并将文件迁移到共享对象存储。

## 许可证

当前仓库尚未包含许可证文件。在复制、分发或用于商业项目前，请由项目维护者补充明确的开源许可证。
