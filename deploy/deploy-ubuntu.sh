#!/usr/bin/env bash
# Mintly Ubuntu Automated Server Setup & Deployment Script
set -euo pipefail

echo "=========================================================="
echo "    Mintly — Ubuntu Server Setup & Deployment Script     "
echo "=========================================================="

APP_DIR="${APP_DIR:-$HOME/Mintly}"

# Check for Docker and Docker Compose
if ! command -v docker &> /dev/null; then
    echo "[INFO] Docker not found. Installing Docker Engine..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg lsb-release
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    sudo usermod -aG docker "$USER"
    echo "[SUCCESS] Docker installed."
fi

# Clone or pull latest code
if [ ! -d "$APP_DIR" ]; then
    echo "[INFO] Cloning repository to $APP_DIR..."
    git clone https://github.com/EvanD1st/Mintly.git "$APP_DIR"
    cd "$APP_DIR"
else
    echo "[INFO] Pulling latest changes from git..."
    cd "$APP_DIR"
    git fetch origin
    git checkout main || git checkout master
    git pull origin main || git pull origin master
fi

cd "$APP_DIR/backend"

# Ensure .env exists
if [ ! -f .env ]; then
    echo "[INFO] Creating .env from .env.example..."
    cp .env.example .env
fi

# Run docker compose build and up
echo "[INFO] Starting backend, worker, postgres, and redis services..."
docker compose down || true
docker compose up --build -d

echo ""
echo "=========================================================="
echo "[SUCCESS] Mintly services are running on your Ubuntu server!"
echo "Check backend status: docker compose ps"
echo "Check backend logs:   docker compose logs -f backend"
echo "Check worker logs:    docker compose logs -f worker"
echo "=========================================================="
