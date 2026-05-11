#!/usr/bin/env bash
# ============================================================
# ContentFlow — 伺服器一鍵部署腳本
# 執行環境：Ubuntu 22.04 LTS / root@172.235.216.10
#
# 使用方式（在本機執行，自動 scp + ssh）：
#   DOMAIN=example.com ./deploy/setup_remote.sh
#
# 或先 scp 整個專案，再 ssh 進去手動執行：
#   ssh root@172.235.216.10 "bash /root/contentflow/deploy/server_init.sh"
# ============================================================
set -euo pipefail

SERVER=${SERVER:-root@172.235.216.10}
PROJECT_DIR=${PROJECT_DIR:-/root/contentflow}
DOMAIN=${DOMAIN:-}
DEFAULT_BUILD_COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    if ! git diff --quiet --ignore-submodules HEAD -- 2>/dev/null; then
        DEFAULT_BUILD_COMMIT="${DEFAULT_BUILD_COMMIT}-dirty"
    fi
fi
BUILD_COMMIT=${CONTENTFLOW_BUILD_COMMIT:-$DEFAULT_BUILD_COMMIT}
BUILD_TIME=${CONTENTFLOW_BUILD_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}
BUILD_SOURCE=${CONTENTFLOW_BUILD_SOURCE:-local-rsync}
TMP_ARCHIVE=""

if command -v ssh.exe >/dev/null 2>&1; then
    SSH_BIN=$(command -v ssh.exe)
else
    SSH_BIN=$(command -v ssh)
fi

if command -v scp.exe >/dev/null 2>&1; then
    SCP_BIN=$(command -v scp.exe)
else
    SCP_BIN=$(command -v scp)
fi

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
RSYNC_SHELL="$SSH_BIN -o StrictHostKeyChecking=accept-new"

cleanup_local_artifacts() {
    if [[ -n "$TMP_ARCHIVE" && -f "$TMP_ARCHIVE" ]]; then
        rm -f "$TMP_ARCHIVE"
    fi
}

trap cleanup_local_artifacts EXIT

upload_project() {
    if command -v rsync >/dev/null 2>&1; then
        echo "==> 1. 上傳專案（rsync）"
        rsync -e "$RSYNC_SHELL" -avz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
              --exclude='.venv' --exclude='outputs/' \
              "$(pwd)/" "$SERVER:$PROJECT_DIR/"
        return
    fi

    if ! command -v tar >/dev/null 2>&1 || ! command -v scp >/dev/null 2>&1; then
        echo "ERROR: 未找到 rsync，且 tar/scp fallback 也不可用"
        exit 1
    fi

    if [[ -z "${CONTENTFLOW_BUILD_SOURCE:-}" ]]; then
        BUILD_SOURCE="local-scp"
    fi

    echo "==> 1. 上傳專案（tar + scp fallback；未偵測到 rsync）"
    TMP_ARCHIVE=$(mktemp "${TMPDIR:-/tmp}/contentflow-deploy.XXXXXX.tar.gz")
    tar -czf "$TMP_ARCHIVE" \
        --exclude='.git' \
        --exclude='__pycache__' \
        --exclude='*.pyc' \
        --exclude='.venv' \
        --exclude='outputs/' \
        .
    "$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" "mkdir -p '$PROJECT_DIR'"
    "$SCP_BIN" "${SSH_OPTS[@]}" "$TMP_ARCHIVE" "$SERVER:/tmp/contentflow-deploy.tar.gz"
}

upload_project

echo "==> 2. Run remote deploy (commit=$BUILD_COMMIT)"
"$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" \
    BUILD_COMMIT="$BUILD_COMMIT" \
    BUILD_TIME="$BUILD_TIME" \
    BUILD_SOURCE="$BUILD_SOURCE" \
    PROJECT_DIR="$PROJECT_DIR" \
    DOMAIN="$DOMAIN" \
    'bash -s' << 'REMOTE'
set -euo pipefail
PROJECT_DIR=${PROJECT_DIR:-/root/contentflow}
    DOMAIN=${DOMAIN:-}

mkdir -p "$PROJECT_DIR"

if [[ -f /tmp/contentflow-deploy.tar.gz ]]; then
    echo "==> 解壓部署封包（tar + scp fallback）"
    tar -xzf /tmp/contentflow-deploy.tar.gz -C "$PROJECT_DIR" --strip-components=1
    rm -f /tmp/contentflow-deploy.tar.gz
fi

# ── 安裝基礎套件 ────────────────────────────────────────
apt-get update -q
apt-get install -y -q docker.io nginx certbot python3-certbot-nginx curl

if ! docker compose version >/dev/null 2>&1 && ! command -v docker-compose >/dev/null 2>&1; then
    apt-get install -y -q docker-compose-plugin \
        || apt-get install -y -q docker-compose-v2 \
        || apt-get install -y -q docker-compose
fi

systemctl enable --now docker nginx

# ── 建立 .env.prod（如果還沒有）───────────────────────────
if [[ ! -f "$PROJECT_DIR/.env.prod" ]]; then
    echo "WARN: .env.prod 不存在，從範本建立，請立刻填入 API 金鑰！"
    cp "$PROJECT_DIR/deploy/.env.prod.example" "$PROJECT_DIR/.env.prod"
fi

while IFS= read -r env_line; do
    [[ -z "$env_line" || "$env_line" =~ ^[[:space:]]*# ]] && continue
    export "$env_line"
done < <(sed '1s/^\xEF\xBB\xBF//; s/\r$//' "$PROJECT_DIR/.env.prod")

if [[ -z "$DOMAIN" && -n "${SITE_URL:-}" ]]; then
    DOMAIN=$(printf '%s' "$SITE_URL" | sed -E 's#^https?://([^/]+)/?.*$#\1#')
fi

if [[ -z "$DOMAIN" ]]; then
    echo "ERROR: DOMAIN 未設定，且無法從 SITE_URL 推導。請用 DOMAIN=example.com ./deploy/setup_remote.sh 或在 .env.prod 設定 SITE_URL。"
    exit 1
fi

# ── 資料目錄 ────────────────────────────────────────────
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/outputs"

# ── 部署版本資訊 ────────────────────────────────────────
cat > "$PROJECT_DIR/.build-meta.env" <<EOF
CONTENTFLOW_BUILD_COMMIT=${BUILD_COMMIT}
CONTENTFLOW_BUILD_TIME=${BUILD_TIME}
CONTENTFLOW_BUILD_SOURCE=${BUILD_SOURCE}
EOF

set -a
. "$PROJECT_DIR/.build-meta.env"
set +a

if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
else
    echo "ERROR: docker compose / docker-compose 均不可用"
    exit 1
fi

# ── nginx 設定 ─────────────────────────────────────────
NGINX_TEMPLATE="$PROJECT_DIR/deploy/nginx.conf"
if [[ "${PLATFORM_MODE:-managed-site}" == "control-plane" || "${MANAGED_SITE_ENABLED:-true}" == "false" ]]; then
    NGINX_TEMPLATE="$PROJECT_DIR/deploy/nginx.control-plane.conf"
fi

sed "s/__DOMAIN__/$DOMAIN/g" "$NGINX_TEMPLATE" > "/etc/nginx/sites-available/$DOMAIN"
ln -sf "/etc/nginx/sites-available/$DOMAIN" "/etc/nginx/sites-enabled/$DOMAIN"
rm -f /etc/nginx/sites-enabled/default

# 先用 HTTP 測試 nginx，之後再申請 SSL
nginx -t && systemctl reload nginx

# ── 申請 Let's Encrypt SSL ─────────────────────────────
if [[ ! -d "/etc/letsencrypt/live/$DOMAIN" ]]; then
    echo "==> 申請 SSL 憑證..."
    certbot --nginx -d "$DOMAIN" -d "www.$DOMAIN" \
        --non-interactive --agree-tos -m "admin@$DOMAIN" \
        --redirect
    nginx -t && systemctl reload nginx
else
    echo "SSL 憑證已存在，略過申請"
fi

# ── 建構 & 啟動 Docker ────────────────────────────────
cd "$PROJECT_DIR"
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml pull || true
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml build \
    || { echo "ERROR: docker build 失敗，中止部署"; exit 1; }

echo "==> 啟動容器..."
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml up -d --force-recreate site scheduler db \
    || { echo "ERROR: docker up 失敗"; exit 1; }

# ── 等待服務就緒（最多 120 秒）──────────────────────────
echo "==> 等待 HTTP 服務就緒（最多 120 秒）..."
DEPLOY_OK=0
for i in $(seq 1 24); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/health 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "200" || "$HTTP_CODE" == "503" ]]; then
        DEPLOY_OK=1
        echo "  服務已回應 HTTP $HTTP_CODE（第 $((i*5)) 秒）"
        break
    fi
    printf "  [%02d/24] 等待中（%s）...\r" "$i" "$(date -u +%H:%M:%S)"
    sleep 5
done
echo ""
if [[ $DEPLOY_OK -eq 0 ]]; then
    echo "WARN: 服務在 120 秒內未回應 /health，可能仍在啟動中"
    echo "  手動確認: curl http://127.0.0.1:8000/health"
    echo "  容器狀態: docker ps"
fi

# ── 執行 DB migration ────────────────────────────────
echo "==> 執行 DB migration..."
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml exec -T site \
    python -m contentflow.db_bootstrap || echo "WARN: migration 失敗，請手動執行"

# ── 最終健康驗證 ─────────────────────────────────────
echo "==> 最終健康驗證..."
HEALTH_JSON=$(curl -sf http://127.0.0.1:8000/health 2>/dev/null || echo '{"status":"unreachable"}')
HEALTH_STATUS=$(echo "$HEALTH_JSON" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
BUILD_TAG=$(echo "$HEALTH_JSON" | python3 -c \
    "import sys,json; d=json.load(sys.stdin); print(d.get('build_commit','?'))" 2>/dev/null || echo "?")

echo ""
if [[ "$HEALTH_STATUS" == "ok" ]]; then
    echo "============================================"
    echo " ContentFlow 部署成功！"
    echo " 網址  : https://$DOMAIN/"
    echo " commit: $BUILD_TAG"
    echo " 狀態  : $HEALTH_STATUS"
    echo "============================================"
else
    echo "============================================"
    echo " WARN: 部署完成，但健康狀態為: $HEALTH_STATUS"
    echo " 網址  : https://$DOMAIN/"
    echo " 詳細  : curl http://127.0.0.1:8000/health"
    "${COMPOSE_CMD[@]}" -f docker-compose.prod.yml ps
    echo "============================================"
fi
REMOTE
