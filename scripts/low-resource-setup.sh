#!/bin/bash
# ================================================
# AI Code Review Bot -- Low-resource server setup
# Target: 2-core 2GB server
# Usage:  sudo bash scripts/low-resource-setup.sh
# ================================================

set -euo pipefail

echo "========================================"
echo "  Low-resource server setup (2C/2G)"
echo "========================================"

# ─────────────────────────────────────────────
# 1. Create 2GB swap (OOM buffer)
# ─────────────────────────────────────────────
echo ""
echo "[1/5] Configuring swap..."

if swapon --show | grep -q "/swapfile"; then
    echo "  [OK] Swap already exists, skip"
else
    fallocate -l 2G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=2048 status=progress
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile

    if ! grep -q "/swapfile" /etc/fstab; then
        echo "/swapfile none swap sw 0 0" >> /etc/fstab
    fi

    sysctl vm.swappiness=10
    if ! grep -q "vm.swappiness" /etc/sysctl.conf; then
        echo "vm.swappiness=10" >> /etc/sysctl.conf
    fi

    echo "  [OK] Swap 2GB created and enabled"
fi

# ─────────────────────────────────────────────
# 2. Tune kernel parameters
# ─────────────────────────────────────────────
echo ""
echo "[2/5] Tuning kernel parameters..."

sysctl -w net.core.somaxconn=256 2>/dev/null || true
sysctl -w net.ipv4.tcp_max_syn_backlog=256 2>/dev/null || true

# Use default heuristic (safer for database workloads)
sysctl -w vm.overcommit_memory=0 2>/dev/null || true

echo "  [OK] Kernel parameters tuned"

# ─────────────────────────────────────────────
# 3. Clean unused Docker resources (preserve named volumes)
# ─────────────────────────────────────────────
echo ""
echo "[3/5] Cleaning unused Docker resources..."
docker system prune -af 2>/dev/null || echo "  [WARN] Docker not running, skip"
echo "  [OK] Cleanup done"

# ─────────────────────────────────────────────
# 4. Limit Docker log size
# ─────────────────────────────────────────────
echo ""
echo "[4/5] Configuring Docker log limits..."

DOCKER_DAEMON_JSON="/etc/docker/daemon.json"
if [ ! -f "$DOCKER_DAEMON_JSON" ]; then
    cat > "$DOCKER_DAEMON_JSON" << 'EOF'
{
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "10m",
        "max-file": "2"
    },
    "default-ulimits": {
        "nofile": {
            "Name": "nofile",
            "Hard": 65536,
            "Soft": 65536
        }
    }
}
EOF
    systemctl restart docker 2>/dev/null || true
    echo "  [OK] Docker log limits configured (10m x 2 files)"
else
    echo "  [INFO] daemon.json exists, manually add log limits:"
    echo '    "log-driver": "json-file",'
    echo '    "log-opts": {"max-size": "10m", "max-file": "2"}'
fi

# ─────────────────────────────────────────────
# 5. Show resource status
# ─────────────────────────────────────────────
echo ""
echo "[5/5] Current resource status:"
echo "  --------------------------------"
echo "  Memory:"
free -h | head -2
echo ""
echo "  Swap:"
swapon --show
echo ""
echo "  Disk:"
df -h / | tail -1
echo "  --------------------------------"

echo ""
echo "========================================"
echo "  [OK] Setup complete!"
echo ""
echo "  Next: rebuild and start services:"
echo "  docker compose up -d --build"
echo ""
echo "  Monitoring:"
echo "  watch -n2 free -h          # memory"
echo "  docker stats --no-stream    # container resources"
echo "  dmesg | grep -i oom         # OOM check"
echo "========================================"
