#!/usr/bin/env bash
# Bootstraps the API host: Docker + compose stack (API + Caddy TLS).
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update && apt-get install -y ca-certificates curl gnupg
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu noble stable" > /etc/apt/sources.list.d/docker.list
apt-get update && apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

mkdir -p /opt/sol-analyzer && cd /opt/sol-analyzer
cat > .env <<ENV
API_DOMAIN=${api_domain}
API_SHARED_SECRET=${api_shared_secret}
API_IMAGE=${api_image}
SOLANA_RPC_URL=http://${rpc_private_ip}:8899
SOL_PRICE_USD=150
ENV
chmod 600 .env
curl -fsSL https://raw.githubusercontent.com/aidenhaidar/sol-analyzer/main/deploy/docker-compose.yml -o docker-compose.yml
curl -fsSL https://raw.githubusercontent.com/aidenhaidar/sol-analyzer/main/deploy/Caddyfile -o Caddyfile
docker compose pull && docker compose up -d
