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

SERVER=root@172.235.216.10
PROJECT_DIR=/root/contentflow
DOMAIN=goodbone.com.tw

echo "==> 1. 上傳專案（排除 .git / __pycache__ / outputs）"
rsync -avz --exclude='.git' --exclude='__pycache__' --exclude='*.pyc' \
      --exclude='.venv' --exclude='outputs/' \
      "$(pwd)/" "$SERVER:$PROJECT_DIR/"

echo "==> 2. 執行伺服器初始化"
ssh "$SERVER" bash << 'REMOTE'
set -euo pipefail
PROJECT_DIR=/root/contentflow
DOMAIN=goodbone.com.tw

# ── 安裝基礎套件 ────────────────────────────────────────
apt-get update -q
apt-get install -y -q docker.io docker-compose-plugin nginx certbot python3-certbot-nginx curl

systemctl enable --now docker nginx

# ── 建立 .env.prod（如果還沒有）───────────────────────────
if [[ ! -f "$PROJECT_DIR/.env.prod" ]]; then
    echo "WARN: .env.prod 不存在，從範本建立，請立刻填入 API 金鑰！"
    cp "$PROJECT_DIR/deploy/.env.prod.example" "$PROJECT_DIR/.env.prod"
fi

# ── 資料目錄 ────────────────────────────────────────────
mkdir -p "$PROJECT_DIR/data" "$PROJECT_DIR/outputs"

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
docker compose -f docker-compose.prod.yml pull || true
docker compose -f docker-compose.prod.yml build
docker compose -f docker-compose.prod.yml up -d

# ── 執行 DB migration ────────────────────────────────
sleep 5
docker compose -f docker-compose.prod.yml exec api \
    python -m alembic upgrade head || echo "WARN: migration 失敗，請手動執行"

echo ""
echo "============================================"
echo " GoodBone 部署完成！"
echo " https://$DOMAIN/"
echo "============================================"
REMOTE
