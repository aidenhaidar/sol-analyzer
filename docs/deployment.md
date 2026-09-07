# Deployment

```
browser ──► Cloudflare Worker (web/)                 ──► API host on AWS (Docker: Caddy TLS, FastAPI + C++ lib, sol-stream)
             static assets + /api proxy + edge cache       │  x-api-secret required; /ws/* -> sol-stream (WebSocket)
             /ws/* WebSocket passthrough                    ├─► Geyser gRPC (Helius LaserStream / Triton / own node plugin)
                                                           └─► Solana RPC node on AWS (optional; Agave, private RPC :8899)
```

The Python/C++ API cannot run on Workers (native library, ML model), so it lives on AWS
next to the RPC node, where holder scans are cheap. The Worker is the only public entry
point: it serves `web/dist`, forwards `/api/*` with a shared secret, and caches responses
per route (5 s for candles, 60 s for holder risk).

## 1. AWS (Terraform, `infra/aws`)

Creates a VPC, an RPC node (`r7i.16xlarge`, io2 volumes for ledger and accounts) and an
API host (`c7a.xlarge`, Elastic IP). Security groups only allow 443 on the API host from
Cloudflare's IP ranges, and 8899 on the RPC node from the API host.

```bash
cd infra/aws
terraform init
terraform apply \
  -var key_name=my-keypair \
  -var 'admin_cidrs=["203.0.113.4/32"]' \
  -var api_domain=api.example.com \
  -var api_shared_secret="$(openssl rand -hex 32)"
```

Then create an A record for `api_domain` pointing at the `api_public_ip` output
(DNS-only / grey cloud, since the Worker calls it directly). Caddy on the API host
obtains the certificate automatically.

**RPC node.** `rpc-node/user-data.sh` installs Agave, tunes the kernel, mounts the
volumes, and runs a non-voting `agave-validator` with the account indexes the predictive
engine needs (`spl-token-owner`, `spl-token-mint`, `program-id`) and transaction history
enabled. First sync from a snapshot takes hours; watch with:

```bash
ssh ubuntu@<rpc_public_ip> journalctl -fu agave-rpc
curl -s http://10.0.1.10:8899 -d '{"jsonrpc":"2.0","id":1,"method":"getHealth"}' -H 'content-type: application/json'
```

Testnet is cheaper for a first run: `-var solana_cluster=testnet -var rpc_instance_type=r7i.4xlarge`.

**API host.** `api-host/user-data.sh` installs Docker and starts `deploy/docker-compose.yml`
with `SOLANA_RPC_URL` set to the node's private IP. The image is built by the Deploy
workflow and published to `ghcr.io/<owner>/sol-analyzer-api`. To update:

```bash
ssh ubuntu@<api_public_ip> 'cd /opt/sol-analyzer && sudo docker compose pull && sudo docker compose up -d'
```

Add `SOLANATRACKER_API_KEY` to `/opt/sol-analyzer/.env` for live candles and holder history,
and `GEYSER_ENDPOINT` / `GEYSER_X_TOKEN` for the real-time holder stream (empty runs the
simulated feed). The Deploy workflow also publishes `ghcr.io/<owner>/sol-analyzer-stream`.

## 2. Cloudflare Workers (`web/`)

```bash
cd web
npm run build
npx wrangler secret put API_SHARED_SECRET      # same value as terraform's api_shared_secret
npx wrangler deploy --var API_ORIGIN:https://api.example.com
```

`wrangler.toml` binds `dist/` as static assets with SPA fallback and routes `/api/*`
through the Worker first. Attach a custom domain in the Cloudflare dashboard or add a
`routes` block.

## 3. GitHub Actions

* `ci.yml` runs all four test suites on every push.
* `deploy.yml` (on `main`) builds and pushes the API image, then deploys the Worker.
  Required repository secrets: `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`,
  `API_SHARED_SECRET`; repository variable: `API_ORIGIN`.

## Local check of the production path

```bash
docker build -t sol-analyzer-api .
docker run -p 8787:8787 -e API_SHARED_SECRET=dev sol-analyzer-api
cd web && npm run build && npx wrangler dev --var API_ORIGIN:http://localhost:8787
```

Then set the `API_SHARED_SECRET` secret in `web/.dev.vars` to `dev`.
