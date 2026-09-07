#!/usr/bin/env bash
# Bootstraps an Agave (Solana) RPC node on Ubuntu 24.04. Runs once at first boot.
# Cluster: ${cluster}
set -euxo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update && apt-get install -y curl build-essential pkg-config libssl-dev libudev-dev jq nvme-cli

# ---- disks: ledger on /dev/sdf (nvme1n1), accounts on /dev/sdg (nvme2n1)
mkdir -p /mnt/ledger /mnt/accounts
for pair in "nvme1n1:/mnt/ledger" "nvme2n1:/mnt/accounts"; do
  dev=$${pair%%:*}; mnt=$${pair##*:}
  if [ -b /dev/$dev ] && ! blkid /dev/$dev >/dev/null; then mkfs.ext4 -F /dev/$dev; fi
  if [ -b /dev/$dev ]; then
    echo "/dev/$dev $mnt ext4 defaults,noatime 0 2" >> /etc/fstab
    mount $mnt
  fi
done

# ---- kernel tuning recommended by the Agave docs
cat > /etc/sysctl.d/21-agave-validator.conf <<'SYSCTL'
net.core.rmem_default = 134217728
net.core.rmem_max = 134217728
net.core.wmem_default = 134217728
net.core.wmem_max = 134217728
vm.max_map_count = 1000000
fs.nr_open = 1000000
SYSCTL
sysctl -p /etc/sysctl.d/21-agave-validator.conf
cat > /etc/security/limits.d/90-solana-nofiles.conf <<'LIM'
* - nofile 1000000
LIM

# ---- user + binaries
useradd -m -s /bin/bash sol || true
chown -R sol:sol /mnt/ledger /mnt/accounts
su - sol -c 'sh -c "$(curl -sSfL https://release.anza.xyz/stable/install)"'
su - sol -c '/home/sol/.local/share/solana/install/active_release/bin/solana-keygen new --no-passphrase -so /home/sol/validator-keypair.json'

if [ "${cluster}" = "mainnet-beta" ]; then
  ENTRYPOINTS="--entrypoint entrypoint.mainnet-beta.solana.com:8001 --entrypoint entrypoint2.mainnet-beta.solana.com:8001 --entrypoint entrypoint3.mainnet-beta.solana.com:8001"
  KNOWN="--known-validator 7Np41oeYqPefeNQEHSv1UDhYrehxin3NStELsSKCT4K2 --known-validator GdnSyH3YtwcxFvQrVVJMm1JhTS4QVX7MFsX56uJLUfiZ --known-validator DE1bawNcRJB9rVm3buyMVfr8mBEoyyu73NBovf2oXJsJ --known-validator CakcnaRDHka2gXyXbOsH4yFJ6bVHoK8rgNRqKtu7hRXP"
  EXPECTED="--expected-genesis-hash 5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d"
else
  ENTRYPOINTS="--entrypoint entrypoint.testnet.solana.com:8001 --entrypoint entrypoint2.testnet.solana.com:8001"
  KNOWN="--known-validator 5D1fNXzvv5NjV1ysLjirC4WY92RNsVH18vjmcszZd8on"
  EXPECTED="--expected-genesis-hash 4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY"
fi

# ---- RPC-only validator (no voting); indexes needed by getTokenLargestAccounts /
# getTokenAccountsByOwner / getSignaturesForAddress used by the predictive engine.
cat > /home/sol/run-rpc.sh <<RUN
#!/usr/bin/env bash
exec /home/sol/.local/share/solana/install/active_release/bin/agave-validator \\
  --identity /home/sol/validator-keypair.json \\
  $ENTRYPOINTS $KNOWN $EXPECTED \\
  --only-known-rpc \\
  --no-voting \\
  --ledger /mnt/ledger \\
  --accounts /mnt/accounts \\
  --rpc-port 8899 \\
  --rpc-bind-address 0.0.0.0 \\
  --private-rpc \\
  --full-rpc-api \\
  --enable-rpc-transaction-history \\
  --enable-extended-tx-metadata-storage \\
  --account-index program-id \\
  --account-index spl-token-owner \\
  --account-index spl-token-mint \\
  --dynamic-port-range 8000-8020 \\
  --limit-ledger-size 50000000 \\
  --wal-recovery-mode skip_any_corrupted_record \\
  --log -
RUN
chmod +x /home/sol/run-rpc.sh && chown sol:sol /home/sol/run-rpc.sh

cat > /etc/systemd/system/agave-rpc.service <<'UNIT'
[Unit]
Description=Agave RPC node
After=network.target
[Service]
User=sol
LimitNOFILE=1000000
Environment=RUST_LOG=solana=info
ExecStart=/home/sol/run-rpc.sh
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now agave-rpc
