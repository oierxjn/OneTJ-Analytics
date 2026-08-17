# OneTJ Analytics 后端服务

基于 FastAPI 的后端服务，用于 OneTJ 客户端集成测试，当前同时提供数据采集与版本更新检查能力。

## 功能说明

- 提供 `POST /collector/v1/events` 数据采集接口。
- 提供 `GET /updater/v1/check` 自动更新检查接口。
- 对请求 JSON 的字符串字段进行校验。
- 对大部分字段执行去空白（trim）与非空校验。
- `hashId` 为必填统计字段，缺失或空值直接返回 `400`
- 统一响应格式：`status/code/message/request_id`。
- 基于 IP 的限流（默认 `16 次/分钟/IP`）。
- 更新检查基于仓库内 manifest 文件返回 Windows / Android 的最新版本信息。
- 客户端 IP 解析规则：
  - 优先取 `X-Forwarded-For` 的第一个 IP。
  - 若无该头，则回退到直连客户端 IP。
- 对敏感字段（`userid`、`username`）进行脱敏日志记录。

## 数据流架构

默认推荐链路如下：

`Collector API -> Redis Stream -> Worker -> PostgreSQL(events_raw)`

说明：

- API 返回 `200` 表示请求已被接收（`redis` 模式下表示入队成功）。但不等于事件已写入数据库，落库由 worker 异步完成。
- 更新检查接口为同步查询链路：`Updater API -> update_manifest.json -> JSON Response`。

## 本地环境准备（Windows PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## 本地环境准备（Linux）

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 依赖服务准备（Redis + PostgreSQL）

本项目落库链路依赖 Redis 和 PostgreSQL。默认配置见 `.env.example`：

- `REDIS_URL=redis://127.0.0.1:6379/0`
- `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/onetj_analytics`

### Linux 安装（Ubuntu/Debian）

```bash
sudo apt-get update
sudo apt-get install -y redis-server postgresql postgresql-client
sudo systemctl enable --now redis-server
sudo systemctl enable --now postgresql
```

### PostgreSQL 初始化（创建业务库和账号）

```bash
sudo -u postgres psql -c "ALTER USER postgres WITH PASSWORD 'postgres';"
sudo -u postgres createdb onetj_analytics
```

将 `.env` 中 `DATABASE_URL` 调整为：

```dotenv
DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/onetj_analytics
```

### Redis 最小配置（可选）

默认已可本机访问，如需显式确认可检查 `/etc/redis/redis.conf`：

- `bind 127.0.0.1 ::1`
- `port 6379`

修改后重启：

```bash
sudo systemctl restart redis-server
```

### PostgreSQL 最小配置（可选）

默认本机访问场景通常无需改动；若需手工确认：

- `postgresql.conf`：`listen_addresses = '127.0.0.1'`
- `pg_hba.conf`：确保存在 `host all all 127.0.0.1/32 scram-sha-256`（或 md5）

修改后重启：

```bash
sudo systemctl restart postgresql
```

### Windows 开发机建议

Redis 官方不再提供原生 Windows Server 版本，建议使用 WSL2 安装 Redis/PostgreSQL，再通过 `127.0.0.1` 访问；`.env` 连接串可保持与 Linux 相同。

请先确保本机 Redis 和 PostgreSQL 已启动，并且与上述地址一致。可用以下命令做最小连通性检查：

```bash
redis-cli -u redis://127.0.0.1:6379/0 ping
psql "postgresql://postgres:postgres@127.0.0.1:5432/onetj_analytics" -c "SELECT 1;"
```

期望输出：
```
PONG
1
```


## 数据库初始化

先执行建表脚本：

```bash
psql "postgresql://postgres:postgres@127.0.0.1:5432/onetj_analytics" -f sql/init_events.sql
```

## 启动服务（API + Worker）

将 `.env.example` 复制为 `.env` 后，按场景修改配置。

### Windows PowerShell

```powershell
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
.\.venv\Scripts\python -m app.worker
```

### Linux

```bash
source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000
python -m app.worker
```

注意：

- `INGEST_BACKEND=redis` 时，API 和 worker 需要同时运行。
- `INGEST_BACKEND=memory` 时，仅内存暂存，不会写入数据库。
- `GET /updater/v1/check` 不依赖 Redis 和 PostgreSQL，但服务启动时会校验 `UPDATE_MANIFEST_PATH` 指向的 manifest 文件。

## 运行测试

```powershell
.\.venv\Scripts\python -m pytest -q
```

Linux 测试示例：

```bash
source .venv/bin/activate
pytest -q
```

GitLab CI 中也建议使用：

```bash
python -m pytest -q
```

这样可以避免某些 Linux 环境下直接调用 `pytest` 时出现导包路径问题。

## 请求示例

### 采集请求

```bash
curl -X POST "http://127.0.0.1:8000/collector/v1/events" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "Accept: application/json" \
  -d '{
    "hashId":"hash-2333333",
    "userid":"2333333",
    "username":"张三",
    "client_version":"1.2.3+45",
    "device_brand":"HUAWEI",
    "device_model":"Pura 70",
    "dept_name":"计算机学院",
    "school_name":"同济大学",
    "gender":"男",
    "platform":"ohos"
  }'
```

### 更新检查请求

Windows：

```bash
curl "http://127.0.0.1:8000/updater/v1/check?platform=windows&arch=x64&current_version=2.2.4&current_build=11" \
  -H "Accept: application/json"
```

Android：

```bash
curl "http://127.0.0.1:8000/updater/v1/check?platform=android&current_version=2.2.4&current_build=11" \
  -H "Accept: application/json"
```

## 最小端到端验证（确认落库）

1. 启动 Redis、PostgreSQL、API、worker。
2. 发送一条采集请求（见上方请求示例）。
3. 在 PostgreSQL 查询最新数据：

```sql
SELECT id, request_id, hash_id, received_at, platform
FROM events_raw
ORDER BY id DESC
LIMIT 5;
```

如果有新增记录，说明链路已打通。

## 更新检查最小验证

1. 确认 `config/update_manifest.json` 或 `.env` 中 `UPDATE_MANIFEST_PATH` 指向的 manifest 文件存在。
2. 启动 API 服务。
3. 发起一条更新检查请求：

```bash
curl "http://127.0.0.1:8000/updater/v1/check?platform=windows&arch=x64&current_version=2.2.4&current_build=11"
```

期望返回：

```json
{
  "status": "ok",
  "code": "SUCCESS",
  "message": "accepted",
  "request_id": "xxx",
  "data": {
    "has_update": true,
    "latest_version": "2.3.0",
    "latest_build": 12,
    "download_url": "https://download.example.com/OneTJSetup_2.3.0_12.exe",
    "sha256": "4f1f2d5a3e8c2f2b4e8aa56d32298f81f7fd46f0614b7fbf9360dbf6abf35f0f"
  }
}
```

## 配置说明

将 `.env.example` 复制为 `.env` 后按需修改：

- `APP_NAME=OneTJ Data Collector`：服务名称。
- `ENVIRONMENT=test`：运行环境标识。
- `REQUIRE_HTTPS=false`：是否强制 HTTPS。
- `RATE_LIMIT_PER_MINUTE=16`：每分钟每 IP 请求上限。
- `MAX_PAYLOAD_BYTES=1048576`：基于 `Content-Length` 的请求体大小上限。
- `INGEST_BACKEND=memory|redis`：事件接入后端。`memory` 仅用于本地/测试，生产建议 `redis`。
- `REDIS_URL=redis://127.0.0.1:6379/0`：Redis 连接地址。
- `REDIS_STREAM_KEY=collector.events`：Redis Stream 名称。
- `REDIS_STREAM_MAXLEN=1000000`：Stream 近似最大长度。
- `DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/onetj_analytics`：PostgreSQL 连接地址。
- `CONSUMER_GROUP=collector-workers`：worker 消费组名。
- `CONSUMER_NAME=worker-1`：worker 消费者名。
- `BATCH_SIZE=500`：单次读取批量上限。
- `FLUSH_INTERVAL_MS=100`：空轮询时休眠间隔（毫秒）。
- `CONSUME_BLOCK_MS=1000`：`xreadgroup` 阻塞时间（毫秒）。
- `UPDATER_RATE_LIMIT_PER_MINUTE=5`：更新检查接口每分钟每 IP 请求上限。
- `UPDATE_MANIFEST_PATH=config/update_manifest.json`：更新清单文件路径，服务启动时会加载并校验。

## 更新清单说明

默认更新清单位于 `config/update_manifest.json`，按 `platform:arch` 组织版本信息：

- Windows 使用如 `windows:x64` 的 key。
- Android 默认使用 `android:default`。

每个条目至少需要以下字段：

- `latest_version`
- `latest_build`
- `download_url`
- `sha256`

可选字段：

- `release_notes`
- `published_at`
- `mandatory`
- `file_size`
- `min_supported_version`

约束：

- `latest_version` / `min_supported_version` 需要是 `major.minor.patch` 格式。
- `download_url` 必须是 HTTPS 地址。
- `sha256` 必须是 64 位小写十六进制字符串。

### 生成 update_manifest.json（底层工具）

日常发布请直接使用下一节的 `scripts/build_release.py`（自动构建 + 收集产物 + 生成 manifest，无需手工维护任何规格文件）。这里保留的 `scripts/generate_update_manifest.py` 是底层工具：接收一份「发布规格 JSON」（临时文件或程序生成均可），自动计算 `sha256` / `file_size` 并产出 `config/update_manifest.json`。

执行命令：

```bash
python scripts/generate_update_manifest.py --spec <发布规格JSON路径> --output config/update_manifest.json
```

发布规格 JSON 的顶层结构为 `entries` 对象，key 为 `<platform>:<arch>`（Windows 用 `windows:x64`，Android 用 `android:default`），value 为发布条目：

| 字段 | 必填 | 类型 | 说明 |
|---|---|---|---|
| `version` | ✅ | string | 版本号，`major.minor.patch` 格式，如 `2.5.0` |
| `build` | ✅ | integer | 构建号，如 `18` |
| `artifact_path` | ✅ | string | 产物文件路径；相对路径基于 spec 文件所在目录解析 |
| `download_url` | ✅ | string | 客户端下载地址，必须为 HTTPS；文件名需与产物命名规则一致 |
| `release_notes` / `release_notes_file` | 可选 | string | 更新说明；二选一，**不能同时设置**；`release_notes_file` 指向 UTF-8 文本文件 |
| `mandatory` | 可选 | boolean | 是否强制更新 |
| `min_supported_version` | 可选 | string | 最低支持版本，`major.minor.patch` 格式 |
| `published_at` | 可选 | string | 发布时间；缺省时脚本自动写入当前 UTC 时间 |

产物命名规则（脚本在收集 / 推演时按此生成文件名，`download_url` 的文件名必须与之一致）：

- Windows：`OneTJSetup_windows_<version>_<build>.exe`
- Android：`OneTJ_release_<version>_<build>.APK`

双平台完整示例：

```json
{
  "entries": {
    "windows:x64": {
      "version": "2.5.0",
      "build": 18,
      "artifact_path": "dist/OneTJSetup_windows_2.5.0_18.exe",
      "download_url": "https://onetjapi.example.com/downloads/OneTJSetup_windows_2.5.0_18.exe",
      "release_notes_file": "../release-notes/release.md",
      "mandatory": false,
      "min_supported_version": "2.0.0"
    },
    "android:default": {
      "version": "2.5.0",
      "build": 18,
      "artifact_path": "dist/OneTJ_release_2.5.0_18.APK",
      "download_url": "https://onetjapi.example.com/downloads/OneTJ_release_2.5.0_18.APK",
      "release_notes_file": "../release-notes/release.md",
      "mandatory": false,
      "min_supported_version": "2.0.0"
    }
  }
}
```

与 `update_manifest.json` 的字段映射：

| 发布规格 JSON | update_manifest.json | 说明 |
|---|---|---|
| `version` | `latest_version` | 由脚本搬运 |
| `build` | `latest_build` | 由脚本搬运 |
| `download_url` | `download_url` | 由脚本搬运 |
| —（脚本计算） | `sha256`、`file_size` | 基于 `artifact_path` 计算 |
| `release_notes` / `release_notes_file` | `release_notes` | 由脚本搬运 / 读取 |
| `published_at` | `published_at` | 缺省时脚本自动生成 |
| `mandatory` | `mandatory` | 由脚本搬运 |
| `min_supported_version` | `min_supported_version` | 由脚本搬运 |

脚本会自动：

- 读取每个条目的 `artifact_path`
- 支持直接写 `release_notes`，也支持通过 `release_notes_file` 从 UTF-8 文本文件读取
- `release_notes` 和 `release_notes_file` 不能同时设置
- 计算产物的 `sha256`
- 读取产物大小填充 `file_size`
- 如果未提供 `published_at`，自动写入脚本执行时的当前 UTC 时间
- 用现有 Pydantic 模型校验生成结果是否合法

### 一键构建 + 生成 manifest（build_release.py）

[scripts/build_release.py](E:\Program\OneTJ-Analytics\scripts\build_release.py) 把「构建 OneTJ 客户端 -> 收集产物 -> 生成 manifest」整条链路自动化。

**直接执行即真实构建**（默认行为），flutter 一律通过 **fvm** 调用；默认读取 [config/release_config.json](E:\Program\OneTJ-Analytics\config\release_config.json) 提供默认值，命令行 flag 优先：

```bash
python scripts/build_release.py \
    --repo <OneTJ仓库路径> \                     # 缺省取配置 repo 字段
    --platform windows,android \                 # 默认全部
    [--version 2.5.0+18] \                      # 缺省读 pubspec
    [--download-base https://host/downloads] \  # 缺省取配置 download_base
    [--iscc <ISCC.exe路径>] \                    # 缺省自动探测
    [--mandatory] [--min-supported 2.0.0]
```

执行流程：`fvm flutter build windows --release` -> ISCC 打包安装包 -> `fvm flutter build apk --release` -> 收集并重命名产物到 `dist/` -> 生成 `update_manifest.json`（sha256 / file_size 自动计算并校验）-> 结束。

常用附加参数：

- `--skip-build`：跳过 flutter / ISCC 构建，直接收集已有产物并生成 manifest（复用旧产物 / 快速验证收尾流程）；
- `--publish`：生成 manifest 后把产物 scp 发布到下载服务器（需配置 `publish_remote` 或传 `--publish-remote`）；
- `--dry-run`：发布前预览——只做只读检查与路径推演，不执行构建 / 复制 / 写文件（默认不加该参数时直接真实构建）。

每次执行前会做同样的检查并输出：

- **版本**：读自 OneTJ 仓库 `pubspec.yaml` 的 `version: <x.y.z>+<build>`（可用 `--version` 覆盖）；
- **发布配置**：下载基址、强制更新、最低支持版本、release notes、输出 manifest 路径；
- **工具链**：检查 `fvm` 与 `ISCC`（Inno Setup 编译器，用于 Windows 安装包打包）是否可用，支持 `--iscc` 显式指定；
- **setup.iss**：核对 `AppVersion` 与 pubspec 版本是否一致（发布前请先运行 OneTJ 仓库自带的版本同步脚本）；
- **Android 签名**：确认 `android/key.properties` 与 keystore 文件存在（脚本不会读取 / 打印其中的明文口令）；
- **产物推演**：各平台的最终产物文件名与下载地址（如 `OneTJSetup_windows_2.5.0_18.exe`、`OneTJ_release_2.5.0_18.APK`），并检查产物目录中已存在的旧文件；
- **现网 manifest 对比**：对比 `config/update_manifest.json` 当前版本与本次发布版本（升级 / 持平 / 新增）。

发布配置（模板见 [config/release_config.json.example](E:\Program\OneTJ-Analytics\config\release_config.json.example)）：`repo`、`collect_dir`、`download_base`、`iscc`、`release_notes_file`、`min_supported_version`、`output_manifest`，可选 `publish_remote`（`--publish` 时的 scp 目标）。

### 下载文件路由（Nginx `/downloads/`）

客户端更新包的下载地址由三段组成，缺一不可：

`download_url = https://<域名>/downloads/<产物文件名>`
              └── download_base ──┘      └── publish_remote 对应目录中的文件 ──┘

- **`download_base`**（配置）：`https://<域名>/downloads`，对应服务器 Nginx 的 `/downloads/` 路由；
- **Nginx 路由**（服务器配置，需手工维护）：把 `/downloads/` 映射到物理目录 `/srv/onetj-downloads/`：
  ```nginx
  location /downloads/ {
      alias /srv/onetj-downloads/;
      add_header Content-Disposition "attachment";   # 强制下载，避免浏览器直接打开
      types {
          application/vnd.android.package-archive apk;   # APK 正确的 MIME
      }
  }
  ```
- **`publish_remote`**（配置）：`user@host:/srv/onetj-downloads`——即上面 `alias` 指向的**物理目录**（不是项目部署目录），`--publish` 时产物会被 scp 到这里。

发布链路：`--publish`（默认即真实构建；已构建过可加 `--skip-build` 复用产物）-> 产物收集到 `dist/` -> 生成 manifest -> scp 到 `/srv/onetj-downloads/` -> 客户端通过 `https://<域名>/downloads/<文件名>` 下载。

提示：物理目录名（`/srv/onetj-downloads`）是示例，请以服务器上实际 `nginx -T` 查到的 `alias` 为准。


## 常见误区

- 只启动 API 不启动 worker（且 `INGEST_BACKEND=redis`）时，消息会在 Redis 中积压。
- 使用 `INGEST_BACKEND=memory` 时，重启进程后内存中的事件会丢失。

## HTTPS 配置

### 开发环境（推荐 Nginx 自签证书）

适用于本地联调。浏览器或客户端可能提示证书不受信任，属于正常现象。

```bash
# 1) 启动 Uvicorn（HTTP，仅内网/本机）
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 2) 由 Nginx 终止 TLS（证书挂 Nginx）
# 可使用下文 Linux 部署章节中的自签证书与 Nginx 配置模板
```

### 生产环境（正式证书，推荐挂在 Nginx）

正式证书由受信任 CA 签发，不能只靠本地自签完成公网可信部署。

前置条件：

- 已有可访问的公网域名（例如 `api.example.com`）。
- DNS 已将该域名解析到你的服务器公网 IP。

使用 `certbot` 申请证书（Linux）：

```bash
# 方式一：由 certbot 自动配置 Nginx（推荐）
sudo certbot --nginx -d api.example.com

# 方式二：仅签发证书，不自动改 Nginx 配置
sudo certbot certonly --standalone -d api.example.com
```

证书默认路径（Nginx 使用）：

- 证书链：`/etc/letsencrypt/live/api.example.com/fullchain.pem`
- 私钥：`/etc/letsencrypt/live/api.example.com/privkey.pem`

推荐架构（默认）：

- 对外：`Nginx` 监听 `443` 并终止 TLS（证书挂 Nginx）。
- 对内：`Nginx -> Uvicorn` 走 `127.0.0.1:8000` 的 HTTP。

Nginx 反代到 Uvicorn 时，Uvicorn 启动示例：

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 \
  --proxy-headers --forwarded-allow-ips=127.0.0.1
```

说明：

- Let's Encrypt 证书有效期通常为 90 天，需要配置自动续期（`certbot renew`）。
- 生产默认建议采用 `Nginx/Caddy` 反向代理并终止 TLS，应用进程仅监听内网端口。
- 不推荐直接让 Uvicorn 对公网暴露 `443`，除非你明确不使用反向代理。

## Linux 生产运行建议（Ubuntu 24.04 实测）

以下流程已在 `2026-03-05` 实际部署验证通过。

### 1) 安装系统依赖

```bash
sudo apt-get update
sudo apt-get install -y python3-venv nginx openssl curl
```

### 2) 部署代码并准备运行环境

```bash
sudo mkdir -p /opt/OneTJ-Analytics
# 将代码上传到 /opt/OneTJ-Analytics 后执行：
cd /opt/OneTJ-Analytics
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cp .env.example .env
sed -i 's/^ENVIRONMENT=.*/ENVIRONMENT=prod/' .env
```

### 3) 配置 systemd（开机自启）

创建 API 服务 `/etc/systemd/system/onetj-analytics.service`：

```ini
[Unit]
Description=OneTJ Analytics FastAPI Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/OneTJ-Analytics
EnvironmentFile=/opt/OneTJ-Analytics/.env
ExecStart=/opt/OneTJ-Analytics/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

创建 worker 服务 `/etc/systemd/system/onetj-analytics-worker.service`：

```ini
[Unit]
Description=OneTJ Analytics Worker
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/OneTJ-Analytics
EnvironmentFile=/opt/OneTJ-Analytics/.env
ExecStart=/opt/OneTJ-Analytics/.venv/bin/python -m app.worker
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

启动并设置开机自启：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now onetj-analytics
sudo systemctl enable --now onetj-analytics-worker
sudo systemctl status onetj-analytics
sudo systemctl status onetj-analytics-worker
```

查看日志：

```bash
sudo journalctl -u onetj-analytics -f
sudo journalctl -u onetj-analytics-worker -f
```

### 4) 配置 Nginx（HTTPS 反向代理）

内网或无公网域名场景可先用自签证书：

```bash
sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -newkey rsa:2048 -nodes -days 365 \
  -keyout /etc/nginx/ssl/onetj-analytics.key \
  -out /etc/nginx/ssl/onetj-analytics.crt \
  -subj "/CN=192.168.134.136"
```

创建 `/etc/nginx/sites-available/onetj-analytics`：

```nginx
server {
    listen 80 default_server;
    server_name _;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl default_server;
    server_name _;

    ssl_certificate /etc/nginx/ssl/onetj-analytics.crt;
    ssl_certificate_key /etc/nginx/ssl/onetj-analytics.key;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

启用站点并重载：

```bash
sudo ln -sf /etc/nginx/sites-available/onetj-analytics /etc/nginx/sites-enabled/onetj-analytics
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### 5) 联调验证

```bash
curl -I http://192.168.134.136
curl -k -X POST "https://192.168.134.136/collector/v1/events" \
  -H "Content-Type: application/json" \
  -d '{}'
```

期望结果：

- HTTP 返回 `301` 并跳转到 HTTPS。
- HTTPS 接口返回 `{"status":"ok","code":"SUCCESS"...}`。

## 踩坑与排查（实测）

### 1) `pytest -q` 报 `ModuleNotFoundError: No module named 'app'`

现象：

- 在 Linux 上直接运行 `.venv/bin/pytest -q` 可能出现导包失败。

建议：

- 使用 `PYTHONPATH=/opt/OneTJ-Analytics .venv/bin/pytest -q`，或
- 使用 `python -m pytest -q`（确保当前目录是项目根目录）。

### 2) 自签证书下 `curl`/浏览器提示证书不受信任

现象：

- 这是自签证书的正常表现，客户端会提示不受信任。

建议：

- 开发联调可使用 `curl -k` 跳过证书校验。
- 生产环境务必替换为受信任 CA 证书（例如 Let's Encrypt）。

### 3) 反向代理头未传递导致协议识别不完整

建议：

- Nginx 必须转发 `X-Forwarded-Proto`（通常设为 `$scheme`）。
- Uvicorn 建议加 `--proxy-headers --forwarded-allow-ips=127.0.0.1`，让应用正确识别代理后的协议。

## GitLab CI/CD 流水线

仓库根目录已提供 `.gitlab-ci.yml`，默认行为如下：

- 任意分支 `push` 或 `Merge Request` 时自动执行测试。
- `main` 分支 `push` 成功后，出现一个手动 `deploy` 任务。
- 测试阶段固定使用 `INGEST_BACKEND=memory`，因此不依赖 Redis 和 PostgreSQL。
- 部署阶段按当前 README 的 Linux 运行方式，通过 SSH 登录服务器并重启 systemd 服务。
- 当前流水线默认绑定 runner tag：`jkljkluiouio-VM-docker-runner`。

### 部署阶段依赖的 GitLab CI/CD Variables

在 GitLab 项目的 `Settings -> CI/CD -> Variables` 中配置：

- `SSH_PRIVATE_KEY`：用于登录部署服务器的私钥，建议设为 Protected + Masked。
- `DEPLOY_HOST`：部署目标服务器地址。
- `DEPLOY_USER`：部署目标服务器用户。
- `DEPLOY_PORT`：可选，默认 `22`。
- `DEPLOY_PATH`：可选，默认 `/opt/OneTJ-Analytics`。

### 服务器前置条件

部署目标机需要满足以下条件：

- 项目代码已存在于 `DEPLOY_PATH`，并且该目录是一个 Git 工作副本。
- 服务器已按本文 Linux 部署章节准备好 `.env`、Python 运行环境、systemd 服务和 Nginx。
- `DEPLOY_USER` 可以执行：
  - `git fetch --all`
  - `git checkout <commit_sha>`
  - `.venv/bin/python -m pip install -r requirements.txt`
  - `sudo systemctl restart onetj-analytics`
  - `sudo systemctl restart onetj-analytics-worker`
- 如果 `systemctl` 需要提权，建议为该用户配置免密码 sudo，否则 GitLab job 会卡在交互式密码输入。

### 流水线部署动作

手动触发 `deploy` 后，流水线会在服务器执行：

```bash
cd /opt/OneTJ-Analytics
git fetch --all
git checkout <当前流水线提交 SHA>
python3 -m venv .venv   # 仅当 .venv 不存在时创建
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
sudo systemctl restart onetj-analytics
sudo systemctl restart onetj-analytics-worker
sudo systemctl --no-pager --full status onetj-analytics onetj-analytics-worker
```
