#!/bin/bash
# Rebuild and test script for DEV environment

set -e

ADMIN_TOKEN="${ADMIN_TOKEN:-dev-token-min-32-characters-long}"

echo "🧹 Cleaning up old DEV containers and volumes..."
docker compose -f docker-compose.migrate.yml down -v

echo ""
echo "🔨 Building Docker image (clean build)..."
docker compose -f docker-compose.migrate.yml build --no-cache

echo ""
echo "🚀 Starting DEV services..."
docker compose -f docker-compose.migrate.yml up -d

echo ""
echo "⏳ Waiting for services to be healthy (30 seconds)..."
sleep 30

echo ""
echo "📋 Container status:"
docker compose -f docker-compose.migrate.yml ps

echo ""
echo "🏥 Health check (DEV port 8098):"
curl -s http://localhost:8098/health | jq .

echo ""
echo "📊 Detailed health (with Bearer token):"
curl -s -H "Authorization: Bearer $ADMIN_TOKEN" \
  http://localhost:8098/health/detailed | jq .

echo ""
echo "📝 Application logs (last 30 lines):"
docker compose -f docker-compose.migrate.yml logs --tail=30 app

echo ""
echo "✅ DEV build complete! Container is running on port 8098."
echo ""
echo "Next steps:"
echo "  1. Run smoke tests: ./quick_test.sh"
echo "  2. Check logs: docker compose -f docker-compose.migrate.yml logs -f app"
echo "  3. Test dev endpoint:"
echo "     curl -X POST http://localhost:8098/dev/chat \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"chat_id\": \"+1234567890\", \"text\": \"hello\"}'"
