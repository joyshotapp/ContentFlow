#!/usr/bin/env bash
# ============================================================
# GoodBone — 伺服器一鍵部署腳本
# 執行環境：Ubuntu 22.04 LTS / root@172.235.216.10
#
# 使用方式（在本機執行，自動 scp + ssh）：
#   ./deploy/setup_remote.sh
#
# 或先 scp 整個專案，再 ssh 進去手動執行：
#   ssh root@172.235.216.10 "bash /root/contentflow/deploy/server_init.sh"
# ============================================================
set -euo pipefail

SERVER=${SERVER:-root@172.235.216.10}
PROJECT_DIR=${PROJECT_DIR:-/root/contentflow}
DOMAIN=${DOMAIN:-goodbone.com.tw}
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

echo "==> 2. 執行伺服器初始化（commit=$BUILD_COMMIT）"
"$SSH_BIN" "${SSH_OPTS[@]}" "$SERVER" \
    BUILD_COMMIT="$BUILD_COMMIT" \
    BUILD_TIME="$BUILD_TIME" \
    BUILD_SOURCE="$BUILD_SOURCE" \
    PROJECT_DIR="$PROJECT_DIR" \
    DOMAIN="$DOMAIN" \
    'bash -s' << 'REMOTE'
set -euo pipefail
PROJECT_DIR=${PROJECT_DIR:-/root/contentflow}
DOMAIN=${DOMAIN:-goodbone.com.tw}

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
cp "$PROJECT_DIR/deploy/nginx.conf" "/etc/nginx/sites-available/$DOMAIN"
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
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml build
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml up -d

# ── 執行 DB migration ────────────────────────────────
"${COMPOSE_CMD[@]}" -f docker-compose.prod.yml exec -T site \
    python -m alembic upgrade head || echo "WARN: migration 失敗，請手動執行"

echo ""
echo "============================================"
echo " GoodBone 部署完成！"
echo " https://$DOMAIN/"
echo "============================================"
REMOTE
