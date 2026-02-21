# Security Guide - Production Best Practices

## Security Architecture

### Endpoint Security Layers

```
┌─────────────────────────────────────────────────────────┐
│  PUBLIC (No Auth)                                        │
│  - /health               ← Load balancer health check   │
│  - /ready                ← Kubernetes readiness probe   │
│  - /webhooks/twilio      ← Signature validated          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ADMIN (Require X-Admin-Token header)                   │
│  - /health/detailed      ← System diagnostics           │
│  - /metrics              ← Operational metrics          │
│  - /admin/cleanup        ← Manual operations            │
│  - /admin/metrics/reset  ← Dangerous operations         │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  DEV-ONLY (Hidden in production)                        │
│  - /                     ← Returns 404 in production    │
│  - /dev/chat             ← Testing endpoint             │
│  - /dev/media            ← Testing endpoint             │
│  - /dev/reset            ← Testing endpoint             │
│  - /docs                 ← Swagger UI (disabled)        │
│  - /redoc                ← ReDoc (disabled)             │
└─────────────────────────────────────────────────────────┘
```

---

## Implemented Security Features

### 1. ✅ Authentication & Authorization

#### Admin Token (HMAC-based)
```python
# Constant-time comparison prevents timing attacks
if not hmac.compare_digest(provided_token, settings.admin_token):
    raise HTTPException(401)
```

**Requirements:**
- Minimum 32 characters in production
- Stored in environment variable (never in code)
- Validated on startup

**Usage:**
```bash
curl -H "X-Admin-Token: your-secret-token" \
  https://your-api.com/metrics
```

#### Twilio Webhook Signature
```python
# HMAC-SHA1 signature validation
validator = RequestValidator(settings.twilio_auth_token)
if not validator.validate(url, form_data, signature):
    raise HTTPException(403)
```

**Security:**
- Prevents webhook spoofing
- Validates every request
- Required in production (`REQUIRE_WEBHOOK_VALIDATION=true`)

### 2. ✅ Environment-Based Access Control

```python
# Dev-only endpoints return 404 in production
@app.get("/", dependencies=[Depends(require_dev_environment())])
def root():
    # Only works when APP_ENV=dev
    # Returns 404 when APP_ENV=prod
```

**Endpoints hidden in production:**
- `/` - API info
- `/dev/*` - All development endpoints
- `/docs` - Swagger UI
- `/redoc` - ReDoc
- `/openapi.json` - OpenAPI spec

### 3. ✅ Security Headers (OWASP Best Practices)

All responses include:

```http
X-Frame-Options: DENY
X-Content-Type-Options: nosniff
X-XSS-Protection: 1; mode=block
Referrer-Policy: strict-origin-when-cross-origin
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'
Permissions-Policy: geolocation=(), microphone=(), camera=()
Strict-Transport-Security: max-age=31536000; includeSubDomains (prod only)
```

**Protection against:**
- ✅ Clickjacking
- ✅ MIME sniffing attacks
- ✅ XSS attacks
- ✅ Unwanted feature access
- ✅ Information leakage

### 4. ✅ Rate Limiting

**Global rate limiting:**
```python
# Default: 60 requests per minute per IP
RATE_LIMIT_PER_MINUTE=60
```

**Endpoint-specific:**
- Public endpoints: No rate limit (rely on Twilio rate limiting)
- Admin endpoints: Global rate limit
- Dev endpoints: Global rate limit

**Future enhancement:** Per-phone-number rate limiting for webhooks

### 5. ✅ Input Validation

```python
# Pydantic models validate all inputs
class ChatIn(BaseModel):
    chat_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)
```

**Validation:**
- Type checking
- Length limits
- Format validation
- SQL injection prevention (parameterized queries)

### 6. ✅ Information Disclosure Prevention

**Production error responses:**
```python
# Development
{"error": "ValueError: Invalid chat_id format"}

# Production
{"error": "Invalid input"}
```

**What's hidden in production:**
- Stack traces
- Internal paths
- Database errors
- Configuration details
- Endpoint existence (404 for all unknown routes)

### 7. ✅ Logging Security

**Sensitive data masking:**
```python
# Phone numbers
"+12345678900" → "+1234****00"

# Tokens
"secret_abc123xyz" → "***REDACTED***"
```

**What's logged:**
- ✅ Authentication attempts (success/failure)
- ✅ Rate limit violations
- ✅ Webhook validation failures
- ✅ Request IDs for tracing
- ❌ Passwords/tokens
- ❌ Full phone numbers
- ❌ Sensitive payload data

### 8. ✅ CORS Policy

**Production (strict):**
```python
allow_origins=[]           # No browser access
allow_methods=["POST"]     # Only webhooks
allow_headers=["Content-Type"]
```

**Development (permissive):**
```python
allow_origins=["*"]
allow_methods=["*"]
allow_headers=["*"]
```

### 9. ✅ Database Security

**Connection pooling:**
```python
PG_POOL_MIN=2
PG_POOL_MAX=20
```

**Query security:**
- ✅ Parameterized queries (SQL injection prevention)
- ✅ Connection timeouts
- ✅ Statement timeouts
- ✅ Retry logic with circuit breaker

**Example (safe):**
```python
cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))  # ✅
cur.execute(f"SELECT * FROM users WHERE id = {user_id}")      # ❌
```

### 10. ✅ Secrets Management

**Required secrets:**
```bash
ADMIN_TOKEN=<min 32 chars>
TWILIO_AUTH_TOKEN=<from Twilio>
TWILIO_ACCOUNT_SID=<from Twilio>
DATABASE_URL=postgresql://...
```

**Best practices:**
- ✅ Stored in environment variables
- ✅ Never committed to Git
- ✅ Validated on startup
- ✅ Rotated regularly
- ❌ Never in code
- ❌ Never in logs
- ❌ Never in error messages

---

## Security Checklist for Production

### Before Deployment:

- [ ] `APP_ENV=prod`
- [ ] `ADMIN_TOKEN` is at least 32 characters
- [ ] `REQUIRE_WEBHOOK_VALIDATION=true`
- [ ] All Twilio credentials configured
- [ ] Database credentials use strong password
- [ ] SSL/TLS certificate configured
- [ ] Firewall rules allow only necessary ports
- [ ] Server header hidden
- [ ] API docs disabled (`/docs`, `/redoc`)
- [ ] Dev endpoints return 404

### After Deployment:

- [ ] Test `/health` returns 200
- [ ] Test `/dev/chat` returns 404
- [ ] Test `/metrics` requires admin token
- [ ] Test Twilio webhook signature validation
- [ ] Verify security headers in responses
- [ ] Check logs for leaked secrets
- [ ] Monitor for failed auth attempts
- [ ] Set up alerts for webhook validation failures

---

## Attack Vectors & Mitigations

### 1. Webhook Spoofing
**Attack:** Attacker sends fake webhook to process fraudulent messages

**Mitigation:**
- ✅ Twilio signature validation (HMAC-SHA1)
- ✅ Required in production
- ✅ Logged when validation fails
- ✅ Metrics tracked: `webhook_validation_failures_total`

### 2. Brute Force Admin Token
**Attack:** Attacker tries to guess admin token

**Mitigation:**
- ✅ Constant-time comparison (no timing attacks)
- ✅ Minimum 32 character requirement
- ✅ Failed attempts logged
- ✅ Rate limiting applied
- ✅ Consider: Account lockout after N failures

### 3. DDoS / Rate Abuse
**Attack:** Overwhelming API with requests

**Mitigation:**
- ✅ Rate limiting (60/min per IP)
- ✅ Circuit breaker for database
- ✅ Connection pooling
- ✅ Health checks for load balancer
- ✅ Consider: WAF (CloudFlare, AWS WAF)

### 4. SQL Injection
**Attack:** Malicious SQL in user input

**Mitigation:**
- ✅ Parameterized queries only
- ✅ No string concatenation in SQL
- ✅ ORM-like patterns (safe)
- ✅ Input validation (Pydantic)

### 5. Information Disclosure
**Attack:** Extracting system information from errors

**Mitigation:**
- ✅ Generic error messages in production
- ✅ Stack traces hidden
- ✅ 404 for all unknown routes
- ✅ No server version headers
- ✅ Sensitive data masked in logs

### 6. Session Hijacking
**Attack:** Stealing user session

**Mitigation:**
- ✅ No user sessions (stateless webhooks)
- ✅ Each request independently authenticated
- ✅ Message idempotency via database

### 7. CSRF (Cross-Site Request Forgery)
**Attack:** Unauthorized actions from user's browser

**Mitigation:**
- ✅ No browser-based access needed
- ✅ CORS restricted to nothing in production
- ✅ Webhook signature validation
- ✅ No cookies used

### 8. XSS (Cross-Site Scripting)
**Attack:** Injecting malicious scripts

**Mitigation:**
- ✅ API-only (no HTML rendering)
- ✅ JSON responses only
- ✅ CSP headers block scripts
- ✅ Input sanitization

---

## Monitoring for Security Issues

### Metrics to Watch:

```bash
# Authentication failures
webhook_validation_failures_total{provider="twilio"} > 10

# Rate limit triggers (potential attack)
rate_limit_exceeded_total > 100

# Database errors (potential injection attempts)
database_errors_total > 5

# Unauthorized admin attempts
admin_auth_failures_total > 5
```

### Log Patterns:

```bash
# Suspicious activity
grep "Invalid admin token" logs/ | wc -l
grep "Webhook validation failed" logs/ | wc -l
grep "Rate limit exceeded" logs/ | wc -l

# Access to dev endpoints in production
grep "dev-only endpoint in production" logs/
```

### Alerts to Set Up:

1. **Critical:**
   - Webhook validation failures > 5/min
   - Database connection failures
   - Application crashes

2. **Warning:**
   - Admin auth failures > 10/hour
   - Rate limit triggers > 100/hour
   - High database error rate

3. **Info:**
   - New Twilio phone numbers
   - Unusual traffic patterns

---

## Incident Response

### If Webhook Validation Fails:

1. Check Twilio dashboard for webhook configuration
2. Verify `TWILIO_AUTH_TOKEN` is correct
3. Check for man-in-the-middle attacks
4. Temporarily disable webhook, investigate
5. Rotate Twilio auth token if compromised

### If Admin Token Compromised:

1. Generate new 32+ character token immediately
2. Update environment variable
3. Restart application
4. Review logs for unauthorized access
5. Check for data exfiltration
6. Notify security team

### If Database Compromised:

1. Isolate database server
2. Review database logs
3. Check for data exfiltration
4. Restore from backup if needed
5. Rotate all database credentials
6. Update firewall rules

---

## Future Security Enhancements

### Short-term:
- [ ] Add account lockout after failed admin auth
- [ ] Implement per-phone-number rate limiting
- [ ] Add request signing for admin endpoints
- [ ] Implement audit log for all admin actions

### Medium-term:
- [ ] WAF integration (CloudFlare, AWS WAF)
- [ ] SIEM integration for security monitoring
- [ ] Automated threat detection
- [ ] IP whitelist for admin endpoints

### Long-term:
- [ ] OAuth2 for admin access
- [ ] Certificate pinning for Twilio
- [ ] Encrypted database fields (PII)
- [ ] Compliance certifications (SOC 2, GDPR)

---

## Compliance Considerations

### Data Privacy (GDPR, CCPA):
- ✅ Phone numbers masked in logs
- ✅ Data retention policy (session TTL)
- ✅ Data deletion endpoint (`/dev/reset`)
- ⚠️  Add: GDPR data export endpoint
- ⚠️  Add: Right to be forgotten implementation

### PCI-DSS (if handling payments):
- ✅ No credit card data stored
- ✅ TLS in transit
- ⚠️  Add: PCI compliance if payment features added

### HIPAA (if handling health data):
- ❌ Not applicable (no health data)
- ⚠️  Requires additional encryption if added

---

## Testing Security

### Manual Security Tests:

```bash
# 1. Test dev endpoints return 404 in production
export APP_ENV=prod
curl http://localhost:8099/dev/chat  # Should return 404

# 2. Test admin token required
curl http://localhost:8099/metrics  # Should return 401

# 3. Test rate limiting
for i in {1..70}; do
  curl http://localhost:8099/webhooks/twilio &
done
# Should see 429 after 60 requests

# 4. Test security headers
curl -I http://localhost:8099/health
# Should see X-Frame-Options, CSP, etc.

# 5. Test webhook without signature
curl -X POST http://localhost:8099/webhooks/twilio \
  -d "From=+1234567890&Body=test"
# Should return 403 (missing signature)
```

### Automated Security Scans:

```bash
# OWASP ZAP scan
zap-cli quick-scan http://localhost:8099

# Dependency vulnerabilities
pip-audit

# Secret detection
trufflehog --regex --entropy=True .

# Container scanning
docker scan stage0_app:latest
```

---

## References

- [OWASP API Security Top 10](https://owasp.org/www-project-api-security/)
- [Twilio Webhook Security](https://www.twilio.com/docs/usage/webhooks/webhooks-security)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
