# Postman Collection for Stage0 Bot

## 📦 Contents

- **Stage0_Bot.postman_collection.json** - Complete API test collection
- **Stage0_Bot.postman_environment.json** - Environment variables

## 🚀 Quick Start

### 1. Import into Postman

1. Open Postman
2. Click **Import** button
3. Select both files:
   - `Stage0_Bot.postman_collection.json`
   - `Stage0_Bot.postman_environment.json`
4. Click **Import**

### 2. Configure Environment

1. Select **Stage0 Bot - Development** environment (top-right dropdown)
2. Click the eye icon to view/edit environment
3. Update variables:
   - `base_url`: Your server URL (default: `http://localhost:8099`)
   - `admin_token`: Your admin token (set in `.env` file)

### 3. Start the Server

```bash
# Make sure PostgreSQL is running
docker-compose up -d postgres

# Start the bot server
python -m uvicorn app.transport.http_app:app --reload --port 8099
```

### 4. Run Tests

**Option A: Run entire collection**
- Click on collection name → Click **Run** → Click **Run Stage0 Bot**

**Option B: Run individual folders**
- Expand collection → Right-click folder → Click **Run**

**Option C: Run individual requests**
- Click on request → Click **Send**

## 📋 Collection Structure

### 1. Health & Status (4 requests)
- **Basic Health Check** - Simple health endpoint
- **Readiness Check** - Database connectivity check
- **Detailed Health Check** - Full system health (admin)
- **Metrics** - System metrics (admin)

**Tests:**
- Response time < 50ms
- Status is healthy
- Database checks pass

### 2. Complete Conversation Flow (6 requests)
Full end-to-end conversation testing:
1. **Start Conversation** - Send greeting
2. **Provide Name** - Enter name
3. **Provide Phone** - Enter phone number
4. **Provide Move Date** - Enter move date
5. **Provide From Location** - Enter origin
6. **Provide To Location** - Complete flow

**Tests:**
- Each step transitions correctly
- Responses are fast (<100ms)
- Lead is created and session deleted on completion
- Lead ID is tracked

**Features:**
- Auto-generates unique `chat_id` for each test run using timestamp
- Auto-generates unique `message_id` for each request using GUID (`{{$guid}}`)
- Idempotency test uses same `message_id` for both requests
- Saves `lead_id` to environment for verification
- Console logs for database verification queries

### 3. Idempotency Tests (2 requests)
Tests duplicate message detection:
1. **Send Message Once** - Create initial message
2. **Send Same Message Again** - Verify duplicate detection

**Tests:**
- First message processes normally
- Second message returns "(duplicate ignored)"
- Response time < 50ms (async idempotency check)

### 4. Media Handling (1 request)
Tests media/image upload:
- **Send Media** - Send media URL

**Tests:**
- Media is acknowledged
- Response includes "photo"

### 5. Admin Operations (3 requests)
Admin-only operations:
- **Reset Chat Session** - Delete a session
- **Cleanup Expired Sessions** - Remove old sessions
- **Reset Metrics** - Clear metrics counters

**Tests:**
- Admin token authentication works
- Operations complete successfully
- Proper authorization required

### 6. Performance Tests (1 request)
Tests async performance benefits:
- **Fast Response Test** - Measure response time

**Tests:**
- Response < 50ms (asyncpg benefit)
- No blocking detected

## 🔑 Dynamic Variables

The collection uses Postman's dynamic variables to generate unique IDs:

### Message IDs
- **`{{$guid}}`** - Generates a unique GUID for each request
- Example: `msg-a1b2c3d4-e5f6-7890-abcd-ef1234567890`
- Ensures every message is unique (prevents false idempotency hits)

### Chat IDs
- **`${Date.now()}`** - Generates timestamp-based unique ID
- Example: `test-1706024400000`
- Set in pre-request scripts for conversation flows

### Idempotency Test Exception
The idempotency test folder uses a special approach:
1. **First request:** Generates and saves a `message_id` to collection variable
2. **Second request:** Reuses the SAME `message_id`
3. This tests that duplicates are properly detected

```javascript
// Pre-request script (first request)
const messageId = pm.variables.replaceIn("dup-{{$guid}}");
pm.collectionVariables.set("idempotency_msg_id", messageId);

// Both requests use: {{idempotency_msg_id}}
```

## 🧪 Automated Tests

Each request includes automatic tests that verify:

### Response Validation
```javascript
pm.test("Status code is 200", function () {
    pm.response.to.have.status(200);
});
```

### Performance Validation
```javascript
pm.test("Response time is less than 100ms", function () {
    pm.expect(pm.response.responseTime).to.be.below(100);
});
```

### Data Validation
```javascript
pm.test("Step is ask_name", function () {
    var jsonData = pm.response.json();
    pm.expect(jsonData.step).to.eql("ask_name");
});
```

### Variable Management
```javascript
// Save lead_id for later use
pm.collectionVariables.set("test_lead_id", jsonData.lead_id);
```

## 📊 Test Results

When you run the collection, you'll see:
- **Green** checkmarks ✅ - Tests passed
- **Red** X marks ❌ - Tests failed
- Response times for each request
- Console logs with debugging info

### Expected Performance (Async Benefits)

With asyncpg, you should see:
- Health check: **< 10ms**
- Dev chat (new session): **< 50ms**
- Dev chat (existing session): **< 30ms**
- Concurrent requests: All complete quickly

## 🔍 Debugging

### View Console Logs

After running a request:
1. Click on request
2. Open **Test Results** tab (bottom)
3. Expand test to see console logs

Example logs:
```
Lead ID: lead-abc123
Check database: SELECT * FROM leads WHERE lead_id = 'lead-abc123'
Session should be deleted: SELECT * FROM sessions WHERE chat_id = 'test-1234'
```

### Check Environment Variables

1. Click eye icon (top-right)
2. View current values of:
   - `test_chat_id` - Current test chat ID
   - `test_lead_id` - Last created lead ID

### Verify in Database

After running tests, check database:

```sql
-- View test sessions
SELECT * FROM sessions
WHERE chat_id LIKE 'test-%'
ORDER BY updated_at DESC;

-- View test leads
SELECT * FROM leads
WHERE chat_id LIKE 'test-%'
ORDER BY created_at DESC;

-- View idempotency records
SELECT * FROM inbound_messages
WHERE message_id LIKE 'msg-%'
ORDER BY created_at DESC;
```

## 🎯 Common Scenarios

### Scenario 1: Test Full Flow

1. Run **Complete Conversation Flow** folder
2. Watch tests pass for all 6 steps
3. Check console for lead_id
4. Verify in database:
   ```sql
   SELECT * FROM leads WHERE lead_id = 'your-lead-id';
   SELECT * FROM sessions WHERE chat_id = 'your-chat-id'; -- Should be empty
   ```

### Scenario 2: Test Idempotency

1. Run **Idempotency Tests** folder
2. First request should succeed
3. Second request should return "duplicate ignored"
4. Verify in database:
   ```sql
   SELECT * FROM inbound_messages WHERE message_id = 'dup-msg-1';
   ```

### Scenario 3: Performance Testing

1. Run **Performance Tests** folder multiple times
2. Check response times in test results
3. All should be < 50ms (async benefit)
4. Run concurrently (Collection Runner → Iterations: 10)

### Scenario 4: Load Testing

1. Open Collection Runner
2. Select entire collection
3. Set **Iterations**: 10
4. Set **Delay**: 0ms
5. Click **Run**
6. Verify all pass with fast response times

## ⚙️ Configuration

### Custom Base URL

Update environment:
```json
{
  "key": "base_url",
  "value": "http://your-server:8099"
}
```

### Custom Admin Token

Update environment:
```json
{
  "key": "admin_token",
  "value": "your-actual-admin-token"
}
```

### Production Environment

Create new environment:
1. Duplicate **Stage0 Bot - Development**
2. Rename to **Stage0 Bot - Production**
3. Update variables:
   - `base_url`: Production URL
   - `admin_token`: Production token

## 🐛 Troubleshooting

### Issue: Connection Refused

**Problem:** Cannot connect to server

**Solution:**
1. Check server is running: `ps aux | grep uvicorn`
2. Check port: `netstat -an | grep 8099`
3. Verify `base_url` in environment

### Issue: Admin Tests Fail

**Problem:** 401 Unauthorized on admin endpoints

**Solution:**
1. Check `admin_token` in environment
2. Verify token in `.env` file matches
3. Token must be at least 32 characters in production

### Issue: Slow Response Times

**Problem:** Requests taking > 100ms

**Solution:**
1. Verify async migration is complete
2. Check database performance
3. Check `asyncpg` is installed: `pip show asyncpg`

### Issue: Tests Fail Randomly

**Problem:** Tests pass sometimes, fail other times

**Solution:**
1. Check for leftover test data in database
2. Run cleanup: `DELETE FROM sessions WHERE chat_id LIKE 'test-%'`
3. Ensure unique chat_ids are generated

## 📝 Best Practices

1. **Always use unique chat_ids** - Tests auto-generate them
2. **Check console logs** - They provide SQL queries for verification
3. **Run cleanup** - Delete test data periodically
4. **Monitor performance** - Track response times
5. **Use environments** - Separate dev/staging/production

## 🚀 CI/CD Integration

Run tests from command line using Newman:

```bash
# Install Newman
npm install -g newman

# Run collection
newman run Stage0_Bot.postman_collection.json \
  -e Stage0_Bot.postman_environment.json \
  --reporters cli,json \
  --reporter-json-export results.json

# Check exit code
echo $?  # 0 = success, 1 = failures
```

## 📚 Additional Resources

- **TESTING.md** - Manual testing guide
- **BUILD_AND_TEST_GUIDE.md** - Automated tests
- **MIGRATION_STATUS.md** - Async migration details

## ✅ Success Criteria

All tests should pass with:
- ✅ All status codes 200
- ✅ All response times < 100ms
- ✅ All assertions passing
- ✅ Proper state transitions
- ✅ Database consistency
- ✅ Idempotency working
- ✅ Admin auth working

Happy Testing! 🎉
