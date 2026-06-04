#!/usr/bin/env bash
# ============================================================
# init-letsencrypt.sh — 自动申请 Let's Encrypt SSL 证书
# ============================================================
#
# 用法:
#   chmod +x init-letsencrypt.sh
#   ./init-letsencrypt.sh yourdomain.com www.yourdomain.com
#
# 前置条件:
#   1. 域名已解析到本服务器 IP
#   2. 本脚本所在服务器 80 端口可从公网访问
#   3. docker compose 已启动（nginx 需要运行）
#
# 证书位置:
#   certbot 会将证书输出到 ./certbot/etc/live/<domain>/
#   需要手动复制到 nginx/ssl/ 目录，或修改 nginx.conf 指向 certbot 路径
# ============================================================

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "用法: $0 <domain1> [domain2] [...]"
    echo "示例: $0 baohegui.com www.baohegui.com"
    exit 1
fi

DOMAINS=("$@")
PRIMARY_DOMAIN="${DOMAINS[0]}"

echo "==> 将为以下域名申请证书: ${DOMAINS[*]}"

# certbot 数据目录
CERTBOT_DIR="./certbot"
mkdir -p "${CERTBOT_DIR}/etc" "${CERTBOT_DIR}/www"

# 构建 certbot 域名参数
DOMAIN_ARGS=""
for d in "${DOMAINS[@]}"; do
    DOMAIN_ARGS="${DOMAIN_ARGS} -d ${d}"
done

# 先用 staging 环境测试（避免触发 Let's Encrypt 频率限制）
echo ""
echo "==> [1/3] 测试证书申请（staging 环境）..."
docker compose run --rm \
    -v "$(pwd)/${CERTBOT_DIR}/etc:/etc/letsencrypt" \
    -v "$(pwd)/${CERTBOT_DIR}/www:/var/www/certbot" \
    certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --staging \
    --email "admin@${PRIMARY_DOMAIN}" \
    --agree-tos \
    --no-eff-email \
    ${DOMAIN_ARGS}

echo ""
echo "==> Staging 测试通过！"

# 正式申请
echo ""
echo "==> [2/3] 正式申请证书..."
docker compose run --rm \
    -v "$(pwd)/${CERTBOT_DIR}/etc:/etc/letsencrypt" \
    -v "$(pwd)/${CERTBOT_DIR}/www:/var/www/certbot" \
    certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "admin@${PRIMARY_DOMAIN}" \
    --agree-tos \
    --no-eff-email \
    ${DOMAIN_ARGS}

# 复制证书到 nginx/ssl/
echo ""
echo "==> [3/3] 复制证书到 nginx/ssl/..."
CERT_SRC="${CERTBOT_DIR}/etc/live/${PRIMARY_DOMAIN}"
cp "${CERT_SRC}/fullchain.pem" nginx/ssl/fullchain.pem
cp "${CERT_SRC}/privkey.pem"   nginx/ssl/privkey.pem

echo ""
echo "==> ✅ 完成！证书已放置到 nginx/ssl/"
echo "    请执行 'docker compose restart nginx' 使新证书生效"
echo ""
echo "==> ⚠️  定期续签 (crontab):"
echo "    0 3 * * 1 cd $(pwd) && docker compose run --rm certbot renew --quiet && docker compose restart nginx"
