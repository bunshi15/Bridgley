# Production Deployment Guide

Complete guide for deploying Bridgley to production with security best practices.

---

## Quick Start

```bash
# 1. Copy environment template
cp .env.production.example .env

# 2. Generate strong tokens
python -c "import secrets; print('ADMIN_TOKEN=' + secrets.token_urlsafe(32))"
python -c "import secrets; print('DB_PASSWORD=' + secrets.token_urlsafe(24))"

# 3. Edit .env with your values (Twilio credentials, etc.)
nano .env

# 4. Deploy
docker-compose -f docker-compose.prod.yml --env-file .env up -d

# 5. Check logs
docker-compose -f docker-compose.prod.yml logs -f app

# 6. Verify deployment
curl http://localhost:8099/health
```

---

## Prerequisites

### Required:
- Docker 20.10+
- Docker Compose 2.0+
- Twilio account with verified phone number
- SSL certificate (for production webhook endpoint)

### Recommended:
- Reverse proxy (nginx, traefik)
- Monitoring system (Prometheus, Grafana)
- Log aggregation (ELK, Loki)
- Error tracking (Sentry)

---

## Step-by-Step Deployment

### 1. Prepare Environment

```bash
# Clone repository (if not already done)
git clone <your-repo>
cd stage0_bot

# Copy production environment template
cp .env.production.example .env
```

### 2. Generate Security Credentials

```bash
# Admin token (32+ characters)
python -c "import secrets; print(secrets.token_urlsafe(32))"
# Example output: xB3mK9pL2vN8qR4wT7yU1zA5sC6dF0gH

# Database password
openssl rand -base64 32
# Example output: 3k8L9mN2pQ5rS7tU1vW4xY6zA8bC0dE=
```

### 3. Configure Environment Variables

Edit `.env` file:

```bash
# Application
TENANT_ID=Bridgley_01

# Database
DB_PASSWORD=3k8L9mN2pQ5rS7tU1vW4xY6zA8bC0dE=

# Security
ADMIN_TOKEN=xB3mK9pL2vN8qR4wT7yU1zA5sC6dF0gH

# Twilio (get from https://console.twilio.com/)
TWILIO_AUTH_TOKEN=your-actual-auth-token
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxx
TWILIO_PHONE_NUMBER=+1234567890
```

### 4. Verify Configuration

```bash
# Check environment file is correct
cat .env | grep -v "^#" | grep -v "^$"

# Ensure .env is not tracked by git
echo ".env" >> .gitignore
```

### 5. Build and Deploy

```bash
# Build production image
docker-compose -f docker-compose.prod.yml --env-file .env build

# Start services
docker-compose -f docker-compose.prod.yml --env-file .env up -d

# Verify services are running
docker-compose -f docker-compose.prod.yml ps
```

Expected output:
```
NAME                 STATUS              PORTS
Bridgley_db_prod       Up (healthy)        5432/tcp
Bridgley_app_prod      Up (healthy)        0.0.0.0:8099->8099/tcp
```

### 6. Verify Deployment

```bash
# Health check (should return {"status": "healthy"})
curl http://localhost:8099/health

# Try accessing dev endpoint (should return 404 in production)
curl http://localhost:8099/

# Try accessing metrics without token (should return 401)
curl http://localhost:8099/metrics

# Access metrics with admin token (should return metrics)
curl -H "X-Admin-Token: your-admin-token" http://localhost:8099/metrics
```

### 7. Configure Twilio Webhook

1. Go to Twilio Console: https://console.twilio.com/
2. Navigate to: Phone Numbers → Active Numbers
3. Select your phone number
4. Under "Messaging":
   - Webhook URL: `https://your-domain.com/webhooks/twilio`
   - Method: `POST`
5. Save changes

**Note**: Webhook URL must be HTTPS in production!

### 8. Test Webhook (Local with ngrok)

For testing before DNS setup:

```bash
# Install ngrok (if not installed)
# https://ngrok.com/download

# Start ngrok tunnel
ngrok http 8099

# Update Twilio webhook to ngrok URL
# https://abc123.ngrok.io/webhooks/twilio

# Send test SMS to your Twilio number
# Check logs
docker-compose -f docker-compose.prod.yml logs -f app
```

---

## Security Checklist

Before going live:

- [ ] `APP_ENV=prod` in environment
- [ ] `ADMIN_TOKEN` is 32+ characters
- [ ] `DB_PASSWORD` is strong (24+ characters)
- [ ] `REQUIRE_WEBHOOK_VALIDATION=true`
- [ ] All Twilio credentials configured
- [ ] `.env` file is NOT in git
- [ ] SSL/TLS certificate installed
- [ ] Firewall rules configured
- [ ] Database not exposed externally
- [ ] Reverse proxy configured (if using)
- [ ] Monitoring/alerts set up

---

## Production Architecture

### Minimal Setup (Single Server)

```
Internet
   ↓
[nginx + SSL]
   ↓
[Docker: app + db]
```

### Recommended Setup (High Availability)

```
Internet
   ↓
[Load Balancer + SSL]
   ↓
[App Server 1]  [App Server 2]
   ↓                 ↓
      [PostgreSQL HA]
```

---

## Reverse Proxy Configuration

### Nginx Example

```nginx
# /etc/nginx/sites-available/bridgley

upstream bridgley_backend {
    server localhost:8099;
}

server {
    listen 80;
    server_name your-domain.com;

    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name your-domain.com;

    # SSL Configuration
    ssl_certificate /etc/ssl/certs/your-cert.pem;
    ssl_certificate_key /etc/ssl/private/your-key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;

    # Logging
    access_log /var/log/nginx/stage0_access.log;
    error_log /var/log/nginx/stage0_error.log;

    # Health check (no auth)
    location /health {
        proxy_pass http://stage0_backend;
    }

    # Twilio webhook (no auth, signature validated by app)
    location /webhooks/twilio {
        proxy_pass http://stage0_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Admin endpoints (restrict by IP if possible)
    location /metrics {
        # Optional: Restrict to internal IPs
        # allow 10.0.0.0/8;
        # deny all;

        proxy_pass http://stage0_backend;
        proxy_set_header X-Admin-Token $http_x_admin_token;
    }

    # Block all other routes
    location / {
        return 404;
    }
}
```

Enable and reload:
```bash
sudo ln -s /etc/nginx/sites-available/bridgley /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Monitoring

### Prometheus Metrics

Add to `docker-compose.prod.yml`:

```yaml
  prometheus:
    image: prom/prometheus:latest
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    networks:
      - stage0_network
```

### Prometheus Configuration

Create `prometheus.yml`:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'stage0_bot'
    static_configs:
      - targets: ['app:8099']
    metrics_path: '/metrics'
    bearer_token: 'your-admin-token'
```

### Key Metrics to Monitor

```bash
# Get metrics
curl -H "X-Admin-Token: your-token" http://localhost:8099/metrics

# Critical metrics:
# - webhook_validation_failures_total (should be 0)
# - admin_auth_failures_total (should be low)
# - database_errors_total (should be 0)
# - rate_limit_exceeded_total (monitor for attacks)
```

### Alerts

Set up alerts for:
- Webhook validation failures > 5/min
- Database errors > 10/min
- Admin auth failures > 10/hour
- Health check failures
- High memory/CPU usage

---

## Backup and Recovery

### Database Backup

```bash
# Manual backup
docker exec bridgley_db_prod pg_dump -U bridgley bridgley > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore from backup
docker exec -i bridgley_db_prod psql -U bridgley bridgley < backup_20240122_120000.sql
```

### Automated Backup Script

Create `backup.sh`:

```bash
#!/bin/bash
BACKUP_DIR="/backups/stage0"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/bridgley_$DATE.sql"

mkdir -p "$BACKUP_DIR"

docker exec bridgley_db_prod pg_dump -U bridgley bridgley > "$BACKUP_FILE"
gzip "$BACKUP_FILE"

# Keep only last 30 days
find "$BACKUP_DIR" -name "*.sql.gz" -mtime +30 -delete

echo "Backup completed: ${BACKUP_FILE}.gz"
```

Add to crontab:
```bash
# Daily backup at 2 AM
0 2 * * * /path/to/backup.sh
```

---

## Scaling

### Horizontal Scaling

1. **Use external PostgreSQL** (managed service or HA cluster)
2. **Update docker-compose.prod.yml**:
   ```yaml
   environment:
     DATABASE_URL: postgresql://user:pass@external-db-host:5432/bridgley
   ```
3. **Deploy multiple app instances** behind load balancer
4. **Configure sticky sessions** at load balancer (for rate limiting)

### Vertical Scaling

Update resource limits in `docker-compose.prod.yml`:

```yaml
services:
  app:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 512M
```

---

## Troubleshooting

### App won't start

```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs app

# Common issues:
# - Missing environment variables
# - Weak admin token (< 32 chars)
# - Database connection failed
# - Migration errors
```

### Webhook validation fails

```bash
# Check Twilio credentials
echo $TWILIO_AUTH_TOKEN

# Check logs for signature validation
docker-compose -f docker-compose.prod.yml logs app | grep -i signature

# Temporarily disable validation for testing (NOT FOR PRODUCTION)
# REQUIRE_WEBHOOK_VALIDATION=false
```

### Database connection issues

```bash
# Check database is healthy
docker-compose -f docker-compose.prod.yml ps db

# Test connection manually
docker exec -it bridgley_db_prod psql -U bridgley -d bridgley -c "SELECT 1;"

# Check connection string
echo $DATABASE_URL
```

### High memory usage

```bash
# Check container stats
docker stats bridgley_app_prod

# Adjust connection pool
# PG_POOL_MAX=10  # Reduce if needed
```

---

## Maintenance

### Update Application

```bash
# Pull latest code
git pull

# Rebuild and restart
docker-compose -f docker-compose.prod.yml --env-file .env build
docker-compose -f docker-compose.prod.yml --env-file .env up -d

# Check health
curl http://localhost:8099/health
```

### View Logs

```bash
# Follow logs
docker-compose -f docker-compose.prod.yml logs -f app

# Last 100 lines
docker-compose -f docker-compose.prod.yml logs --tail=100 app

# Filter for errors
docker-compose -f docker-compose.prod.yml logs app | grep ERROR
```

### Clean Up

```bash
# Remove old images
docker image prune -a

# Remove unused volumes
docker volume prune

# Full cleanup (CAREFUL!)
docker system prune -a --volumes
```

---

## Security Best Practices

1. **Never expose database** port externally
2. **Use strong passwords** (32+ characters)
3. **Rotate admin token** regularly (monthly)
4. **Enable webhook validation** in production
5. **Use HTTPS** for all external access
6. **Restrict admin endpoints** by IP if possible
7. **Monitor for suspicious activity** (failed auth attempts)
8. **Keep dependencies updated** regularly
9. **Use read-only filesystem** (if possible)
10. **Run as non-root user** (already configured)

---

## Support

For issues:
1. Check logs: `docker-compose -f docker-compose.prod.yml logs app`
2. Review SECURITY_GUIDE.md
3. Check TROUBLESHOOTING.md
4. Review health checks: `curl http://localhost:8099/health/detailed -H "X-Admin-Token: your-token"`

---

## Quick Reference

### Commands

```bash
# Deploy
docker-compose -f docker-compose.prod.yml --env-file .env up -d

# Stop
docker-compose -f docker-compose.prod.yml down

# Restart
docker-compose -f docker-compose.prod.yml restart app

# Logs
docker-compose -f docker-compose.prod.yml logs -f app

# Health check
curl http://localhost:8099/health

# Metrics (requires admin token)
curl -H "X-Admin-Token: your-token" http://localhost:8099/metrics
```

### Files

- `Dockerfile.prod` - Production Docker image
- `docker-compose.prod.yml` - Production orchestration
- `.env` - Environment variables (NEVER COMMIT!)
- `.env.production.example` - Environment template

### Ports

- 8099 - Application HTTP port
- 5432 - PostgreSQL (not exposed externally)

---

