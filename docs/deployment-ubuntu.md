# Mintly Ubuntu Server Hosting & Deployment Guide

This document describes how to host the Mintly backend and worker stack on your Ubuntu server, either automatically via GitHub Actions CI/CD or directly via script.

---

## Architecture on Ubuntu Server

The Mintly backend stack runs containerized via Docker Compose:
* **`backend` service:** FastAPI app running on port `8000` (`http://localhost:8000`).
* **`worker` service:** Lease-locked Python background worker handling mint scheduling and recovery.
* **`postgres` service:** PostgreSQL 16 database for persistent task and wallet storage.
* **`redis` service:** Redis cache and message bus.

---

## Option A: Automated Deployment via GitHub Actions CI/CD

The workflow at `.github/workflows/ci-cd.yml` automatically tests and deploys changes on push to `main`.

### Required GitHub Repository Secrets
Go to your repository on GitHub: **Settings > Secrets and variables > Actions > New repository secret**, and add:

1. `UBUNTU_HOST`: The public IP or domain of your Ubuntu server (e.g. `203.0.113.195`).
2. `UBUNTU_USER`: The SSH username (e.g. `ubuntu` or `root`).
3. `UBUNTU_SSH_KEY`: The private SSH key used to log into the Ubuntu server (e.g. the contents of `~/.ssh/id_ed25519` or `~/.ssh/id_rsa`).
4. *(Optional)* `UBUNTU_SSH_PORT`: Custom SSH port if not `22`.
5. *(Optional)* `UBUNTU_APP_DIR`: Custom installation directory (defaults to `~/Mintly`).

Whenever you push to `main`:
1. GitHub Actions runs Python pytest (`16 tests`).
2. GitHub Actions runs Flutter analyzer and widget tests.
3. Upon test success, it connects via SSH to your Ubuntu server, pulls the latest code, and runs `docker compose up --build -d`.

---

## Option B: One-Command Direct Deployment on Ubuntu

Log into your Ubuntu server via SSH:
```bash
ssh user@your-ubuntu-server-ip
```

Clone the repository and run the setup script:
```bash
git clone https://github.com/EvanD1st/Mintly.git
cd Mintly
bash deploy/deploy-ubuntu.sh
```

The script will:
1. Install Docker & Docker Compose plugin if missing.
2. Initialize backend configuration (`.env` from `.env.example`).
3. Build and launch all 4 containers in detached mode.

---

## Managing Services on Ubuntu

From the `backend` directory:
```bash
cd ~/Mintly/backend

# View status of running containers
docker compose ps

# View live backend logs
docker compose logs -f backend

# View live worker logs
docker compose logs -f worker

# Restart services
docker compose restart

# Stop services
docker compose down
```

---

## Setting up Nginx Reverse Proxy & SSL (Recommended)

To expose the backend over HTTPS:

```nginx
server {
    server_name api.yourdomain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable SSL with Certbot:
```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.yourdomain.com
```
