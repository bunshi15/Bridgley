#!/bin/bash
# Quick smoke test - runs a simple conversation flow
# Uses DEV port 8098 by default

set -e

BASE_URL="${BASE_URL:-http://localhost:8098}"
CHAT_ID="+12345678900"
ADMIN_TOKEN="${ADMIN_TOKEN:-dev-token-min-32-characters-long}"

echo "🧪 Running quick smoke test on $BASE_URL..."
echo ""

# Test 1: Health check
echo "1. Health check..."
curl -s $BASE_URL/health | jq -r '.status' | grep -q "healthy" && echo "✅ Health check passed" || echo "❌ Health check failed"

# Test 2: First message
echo "2. Sending first message (welcome)..."
RESPONSE=$(curl -s -X POST $BASE_URL/dev/chat \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"$CHAT_ID\", \"text\": \"Hello\"}")

STEP=$(echo $RESPONSE | jq -r '.step')
LEAD_ID=$(echo $RESPONSE | jq -r '.lead_id')

if [ "$STEP" == "welcome" ]; then
  echo "✅ Welcome step - lead_id: $LEAD_ID"
else
  echo "❌ Expected welcome step, got: $STEP"
  echo "Response: $RESPONSE"
  exit 1
fi

# Test 3: Second message (cargo)
echo "3. Sending cargo description..."
RESPONSE=$(curl -s -X POST $BASE_URL/dev/chat \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"$CHAT_ID\", \"text\": \"Furniture\"}")

STEP=$(echo $RESPONSE | jq -r '.step')
if [ "$STEP" == "cargo" ]; then
  echo "✅ Cargo step"
else
  echo "❌ Expected cargo step, got: $STEP"
  exit 1
fi

# Test 4: Idempotency test
echo "4. Testing idempotency (duplicate message)..."
RESPONSE=$(curl -s -X POST $BASE_URL/dev/chat \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"+19999999999\", \"text\": \"Test\", \"message_id\": \"duplicate_123\"}")

RESPONSE2=$(curl -s -X POST $BASE_URL/dev/chat \
  -H "Content-Type: application/json" \
  -d "{\"chat_id\": \"+19999999999\", \"text\": \"Test\", \"message_id\": \"duplicate_123\"}")

REPLY=$(echo $RESPONSE2 | jq -r '.reply')
if [[ "$REPLY" == *"duplicate ignored"* ]]; then
  echo "✅ Idempotency working"
else
  echo "❌ Idempotency not working"
  exit 1
fi

# Test 5: Metrics (with Bearer token)
echo "5. Checking metrics..."
METRICS=$(curl -s -H "Authorization: Bearer $ADMIN_TOKEN" $BASE_URL/metrics)
if [[ "$METRICS" == *"bot_requests_total"* ]]; then
  echo "✅ Metrics tracking"
else
  echo "❌ Metrics not working"
  exit 1
fi

echo ""
echo "🎉 All smoke tests passed!"
