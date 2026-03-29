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

### 用脚本生成 manifest

可以把发布元数据写到一个 JSON 规格文件里，再由脚本自动计算 `sha256` 和 `file_size`，生成最终的 `config/update_manifest.json`：

```json
{
  "entries": {
    "windows:x64": {
      "version": "2.3.0",
      "build": 12,
      "artifact_path": "dist/OneTJSetup_2.3.0_12.exe",
      "download_url": "https://download.example.com/OneTJSetup_2.3.0_12.exe",
      "release_notes_file": "../release-notes/windows-2.3.0.md",
      "mandatory": false,
      "min_supported_version": "2.0.0"
    }
  }
}
```

执行命令：

```bash
python scripts/generate_update_manifest.py --spec config/release_spec.json --output config/update_manifest.json
```

可以先从 [config/release_spec.json.example](E:\Program\OneTJ-Analytics\config\release_spec.json.example) 复制一份作为你的发布输入文件。

脚本会自动：

- 读取每个条目的 `artifact_path`
- 支持直接写 `release_notes`，也支持通过 `release_notes_file` 从 UTF-8 文本文件读取
- `release_notes` 和 `release_notes_file` 不能同时设置
- 计算产物的 `sha256`
- 读取产物大小填充 `file_size`
- 如果未提供 `published_at`，自动写入脚本执行时的当前 UTC 时间
- 用现有 Pydantic 模型校验生成结果是否合法

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
