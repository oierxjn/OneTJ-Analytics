# OneTJ Analytics 后端服务

基于 FastAPI 的数据采集后端，用于 OneTJ 客户端集成测试。

## 功能说明

- 仅提供 `POST /collector/v1/events` 接口。
- 对请求 JSON 的字符串字段进行校验。
- 对大部分字段执行去空白（trim）与非空校验。
- `hashId` 为必填统计字段，缺失或空值直接返回 `400`
- 统一响应格式：`status/code/message/request_id`。
- 基于 IP 的限流（默认 `16 次/分钟/IP`）。
- 客户端 IP 解析规则：
  - 优先取 `X-Forwarded-For` 的第一个 IP。
  - 若无该头，则回退到直连客户端 IP。
- 对敏感字段（`userid`、`username`）进行脱敏日志记录。

## 数据流架构

默认推荐链路如下：

`Collector API -> Redis Stream -> Worker -> PostgreSQL(events_raw)`

说明：

- API 返回 `200` 表示请求已被接收（`redis` 模式下表示入队成功）。但不等于事件已写入数据库，落库由 worker 异步完成。

## 本地环境准备（Windows PowerShell）

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
```

## 本地环境准备（Linux）

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
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

## 运行测试

```powershell
.\.venv\Scripts\python -m pytest -q
```

Linux 测试示例：

```bash
source .venv/bin/activate
pytest -q
```

## 请求示例

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
python -m pip install -r requirements-dev.txt

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
