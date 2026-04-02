# Cloudflare Hardening Guide — greenhelix.net

**Last updated:** 2026-04-02
**Region:** Ashburn
**Plan:** Free (recommendations note where paid features apply)
**Client profile:** Primarily AI agents (programmatic HTTP clients, not browsers)

---

## Current State Assessment

| Area | Current | Status |
|------|---------|--------|
| SSL/TLS mode | Full (strict) | OK |
| DNSSEC | Not enabled | FIX |
| Email Security — SPF | `~all` (softfail) | TIGHTEN |
| Email Security — DKIM | Configured (cf2024-1, RSA/SHA-256) | OK |
| Email Security — DMARC | Not configured | FIX |
| Managed Transforms (security headers) | All OFF | FIX |
| Remove X-Powered-By | OFF | FIX |
| Non-HTTPS traffic | 252 requests (last 24h) | FIX |
| Web3 | Not subscribed | OK (skip) |

---

## 1. DNS Settings

### 1.1 Enable DNSSEC

**Priority: HIGH**

Go to **DNS > Settings** and click **Enable DNSSEC**.

After Cloudflare generates the DS record, add it at your domain registrar. Cloudflare will guide you through this. This protects against DNS cache poisoning and forged DNS answers.

- Multi-signer DNSSEC: Leave **OFF** (single provider)
- Multi-provider DNS: Leave **OFF** (single provider)
- Secondary DNS override: Leave **OFF**

### 1.2 Email Security (SPF/DKIM/DMARC)

**Priority: MEDIUM**

**Current state:** SPF and DKIM are already configured via Cloudflare Email Routing. DMARC is missing.

**Action 1 — Add DMARC record** (click "Create record" in Email > DMARC):

```
Type: TXT
Name: _dmarc
Content: v=DMARC1; p=quarantine; rua=mailto:postmaster@greenhelix.net
TTL: Auto
```

Start with `p=quarantine` to monitor. After a few weeks of clean reports, tighten to `p=reject`.

**Action 2 — Tighten SPF from `~all` to `-all`:**

Current: `"v=spf1 include:_spf.mx.cloudflare.net ~all"` (softfail — unauthorized senders flagged but delivered)

Change to: `"v=spf1 include:_spf.mx.cloudflare.net -all"` (hardfail — unauthorized senders rejected)

Only safe if Cloudflare Email Routing is your sole email sender. If you add another provider later (e.g. SendGrid, SES), add their `include:` before `-all`.

**DKIM — no change needed.** The `cf2024-1` selector with SHA-256/RSA is correctly configured.

### 1.3 DNS Records

Ensure all proxied records (orange cloud) are enabled for records that should go through Cloudflare (api.greenhelix.net, test.greenhelix.net, sandbox.greenhelix.net, www). Any records that must bypass Cloudflare (e.g., mail, Tailscale) should be DNS-only (grey cloud).

---

## 2. SSL/TLS

### 2.1 Encryption Mode

**Current: Full (strict)** — correct, keep this.

### 2.2 Edge Certificates

Go to **SSL/TLS > Edge Certificates**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| Always Use HTTPS | **ON** | Redirects all HTTP to HTTPS. Eliminates the 252 non-secure requests. |
| HTTP Strict Transport Security (HSTS) | **Enable** | Tells clients to always use HTTPS. Set: `max-age=31536000`, `includeSubDomains`, `preload`. (Your origin already sends this header, but having Cloudflare set it too provides defense-in-depth.) |
| Minimum TLS Version | **TLS 1.2** | Drop TLS 1.0 and 1.1. All modern HTTP clients (including Python `requests`, `httpx`, `aiohttp`, Go, Node.js) support TLS 1.2+. |
| Opportunistic Encryption | **ON** | Allows HTTP/2 upgrade from HTTP links. |
| TLS 1.3 | **ON** | Already handling 25.5k requests. Keep enabled. |
| Automatic HTTPS Rewrites | **ON** | Rewrites `http://` links in responses to `https://`. Prevents mixed content. |

### 2.3 Origin Server

Go to **SSL/TLS > Origin Server**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| Origin Certificate | Verify active | You already use Cloudflare origin certs (per TEST_SERVER_SETUP.md). Make sure it's not expiring soon. |
| Authenticated Origin Pulls | **ON** | Ensures only Cloudflare can connect to your origin. Your nginx should verify the Cloudflare client certificate. This prevents bypass of Cloudflare by hitting the origin IP directly. |

To configure Authenticated Origin Pulls on the origin, download the Cloudflare CA from `https://developers.cloudflare.com/ssl/origin-configuration/authenticated-origin-pull/set-up/zone-level/` and add to nginx:

```nginx
ssl_client_certificate /etc/nginx/cloudflare-origin-pull-ca.pem;
ssl_verify_client on;
```

---

## 3. Security

### 3.1 WAF (Web Application Firewall)

Go to **Security > WAF**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| Cloudflare Managed Ruleset | **ON** | Blocks known attack patterns (SQLi, XSS, RCE). Low false-positive rate for API traffic. |
| Cloudflare OWASP Core Ruleset | **ON** (Paranoia Level 1) | Standard OWASP rules. Start at PL1 to avoid blocking legitimate agent traffic. Monitor for false positives, then consider PL2. |

**Important for AI agent traffic:** If the managed WAF blocks legitimate agent requests (large JSON payloads, unusual User-Agent strings), create exception rules for your API paths (`/v1/*`) rather than disabling the WAF entirely.

### 3.2 Bots

Go to **Security > Bots**:

**This is critical for your use case.** Your clients ARE bots (AI agents). Default bot protection will block them.

| Setting | Recommended | Why |
|---------|-------------|-----|
| Bot Fight Mode | **OFF** | Your clients are programmatic. Bot Fight Mode will challenge/block them. |
| Super Bot Fight Mode (Pro+) | If available, set "Definitely automated" to **Allow** | AI agents will be classified as "definitely automated". |

If bot protection is blocking your agents (Cloudflare error 1010), add a **WAF Custom Rule** to skip bot checks for authenticated API traffic:

```
Rule name: Allow authenticated API traffic
Expression: (http.request.uri.path matches "^/v1/") and (http.request.headers["authorization"][0] ne "")
Action: Skip — All remaining custom rules, Rate limiting, Bot Fight Mode
```

### 3.3 DDoS

Go to **Security > DDoS**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| HTTP DDoS attack protection | **ON** (default) | Keep defaults. Cloudflare's adaptive DDoS is effective. |
| L3/L4 DDoS protection | **ON** (default) | Keep defaults. |
| DDoS override | Don't create overrides unless seeing false positives | Monitor first. |

### 3.4 Security Settings

Go to **Security > Settings**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| Security Level | **Medium** or **Low** | For API-only traffic, "Low" is appropriate. "High" or "I'm Under Attack" will challenge every request — bad for agents. |
| Challenge Passage | **30 minutes** | If challenges occur, solved challenges are remembered for this duration. |
| Browser Integrity Check | **OFF** | This checks for common HTTP headers associated with bots — your clients ARE bots. Turn this off or agents will get 403s. |
| Privacy Pass | **ON** | Reduces repeat challenges. |

---

## 4. Rules

### 4.1 Managed Transforms

Go to **Rules > Settings > Managed Transforms**:

**HTTP Request Headers:**

| Transform | Recommended | Why |
|-----------|-------------|-----|
| Add TLS client auth headers | OFF | Not needed unless using mTLS client certs from agents. |
| Add visitor location headers | OFF | Not needed for API. Adds overhead. |
| Remove visitor IP headers | OFF | Keep client IP visible for rate limiting/audit. |
| Add "True-Client-IP" header | **ON** | Useful for logging the real client IP behind Cloudflare. Your rate limiter may need this. |
| Add leaked credentials checks header | OFF | Only useful for login forms. Your API uses API keys, not passwords. |

**HTTP Response Headers:**

| Transform | Recommended | Why |
|-----------|-------------|-----|
| Remove "X-Powered-By" headers | **ON** | Removes server technology fingerprinting. Defense in depth. |
| Add security headers | OFF | Your application middleware already adds all security headers (CSP, X-Frame-Options, HSTS, etc.). Enabling this would duplicate them. Keep OFF to avoid header conflicts. |

### 4.2 Transform Rules (Custom)

Create a transform rule to add `Cache-Control` headers for API responses:

```
Rule name: API no-cache
Expression: (http.request.uri.path matches "^/v1/")
Action: Set Response Header
  Cache-Control: no-store, no-cache, must-revalidate
```

This ensures API responses are never cached by Cloudflare or intermediate proxies. Your API returns dynamic, per-request data (balances, transactions, etc.) that must never be stale.

### 4.3 Page Rules / Cache Rules

Go to **Caching > Cache Rules**:

Create a cache bypass rule for the API:

```
Rule name: Bypass cache for API
Expression: (http.request.uri.path matches "^/v1/")
Action: Bypass cache
```

For static assets (if any, e.g., OpenAPI spec, website):

```
Rule name: Cache static assets
Expression: (http.request.uri.path eq "/v1/openapi.json") or (http.request.uri.path matches "^/static/")
Action: Cache — Edge TTL: 1 hour, Browser TTL: 5 minutes
```

### 4.4 Rate Limiting Rules

Go to **Security > WAF > Rate limiting rules**:

Your application already has per-key rate limiting. Add Cloudflare-level IP rate limiting as an outer defense:

```
Rule name: API IP rate limit
Expression: (http.request.uri.path matches "^/v1/")
Characteristics: IP
Period: 10 seconds
Requests: 100
Action: Block for 60 seconds
```

```
Rule name: Auth brute force protection
Expression: (http.request.uri.path matches "^/v1/") and (http.response.code eq 401)
Characteristics: IP
Period: 1 minute
Requests: 20
Action: Block for 10 minutes
```

---

## 5. Speed / Performance

### 5.1 Caching

Go to **Caching > Configuration**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| Caching Level | **Standard** | Default. Cache rules override per-path. |
| Browser Cache TTL | **Respect Existing Headers** | Let your origin control browser caching. |
| Always Online | **OFF** | API responses must be live. Stale data is dangerous for financial transactions. |
| Crawler Hints | **OFF** | Not applicable. Your clients are agents, not search engines. |

### 5.2 Speed Settings

Go to **Speed > Optimization**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| Auto Minify (JS/CSS/HTML) | **OFF** | API returns JSON, not HTML. No benefit. |
| Brotli compression | **ON** | Compresses JSON responses. Reduces bandwidth for agent clients. Most HTTP libraries support Brotli. |
| Early Hints | **OFF** | Only useful for browsers loading HTML pages. |
| Rocket Loader | **OFF** | JavaScript optimization. Not applicable for API. |
| Mirage | **OFF** | Image optimization. Not applicable. |
| Polish | **OFF** | Image optimization. Not applicable. |

---

## 6. Network

Go to **Network**:

| Setting | Recommended | Why |
|---------|-------------|-----|
| HTTP/2 | **ON** | Better multiplexing for concurrent API calls from agents. |
| HTTP/3 (QUIC) | **ON** | Modern transport. Python `httpx` and Go clients support it. Reduces connection setup latency. |
| WebSockets | **ON** | Required for your SSE/WebSocket endpoints (documented in routes/websocket.py). |
| gRPC | OFF | Not used. |
| Onion Routing | OFF | Not needed. |
| IP Geolocation | **ON** | Adds `CF-IPCountry` header. Useful for analytics/audit logging. |
| Maximum Upload Size | **100 MB** (default) | Fine for API payloads. |
| Response Buffering | OFF | Keep off for SSE streaming responses. |

---

## 7. Web3

**Skip.** Not relevant for this platform. Do not subscribe.

---

## 8. AI Crawl Control

Go to **AI Crawl Control**:

This controls whether AI crawlers (GPTBot, ClaudeBot, etc.) can scrape your site.

| Setting | Recommended | Why |
|---------|-------------|-----|
| Block AI crawlers | **ON** for website, **OFF** for API | AI crawlers shouldn't scrape your website content, but your API is designed for AI agents and should be accessible. |

If available, configure per-path: block crawlers on website paths, allow on `/v1/*`.

---

## 9. Firewall (Origin Server)

These are server-side (UFW/iptables) settings, not Cloudflare UI:

### 9.1 Restrict Origin to Cloudflare IPs Only

Your origin nginx should only accept connections from Cloudflare. Combined with Authenticated Origin Pulls (Section 2.3), this prevents direct-to-origin attacks.

```bash
# UFW rules — allow only Cloudflare IP ranges on port 443
# Get current ranges: https://www.cloudflare.com/ips/
ufw default deny incoming
ufw allow from 173.245.48.0/20 to any port 443
ufw allow from 103.21.244.0/22 to any port 443
ufw allow from 103.22.200.0/22 to any port 443
ufw allow from 103.31.4.0/22 to any port 443
ufw allow from 141.101.64.0/18 to any port 443
ufw allow from 108.162.192.0/18 to any port 443
ufw allow from 190.93.240.0/20 to any port 443
ufw allow from 188.114.96.0/20 to any port 443
ufw allow from 197.234.240.0/22 to any port 443
ufw allow from 198.41.128.0/17 to any port 443
ufw allow from 162.158.0.0/15 to any port 443
ufw allow from 104.16.0.0/13 to any port 443
ufw allow from 104.24.0.0/14 to any port 443
ufw allow from 172.64.0.0/13 to any port 443
ufw allow from 131.0.72.0/22 to any port 443
# Tailscale (for staging deployment)
ufw allow in on tailscale0
# SSH (restrict to your IP or Tailscale)
ufw allow in on tailscale0 to any port 22
```

### 9.2 nginx: Restore Real Client IP

Add to nginx config so your application sees the real client IP (not Cloudflare's):

```nginx
# /etc/nginx/conf.d/cloudflare-real-ip.conf
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
real_ip_header CF-Connecting-IP;
```

---

## 10. Implementation Checklist

Apply in this order (least disruptive first):

### Immediate (no risk of breaking agents)

- [ ] **Enable DNSSEC** (DNS > Settings)
- [ ] **Always Use HTTPS = ON** (SSL/TLS > Edge Certificates)
- [ ] **Minimum TLS Version = 1.2** (SSL/TLS > Edge Certificates)
- [ ] **Enable HSTS** (SSL/TLS > Edge Certificates) — max-age=31536000, includeSubDomains, preload
- [ ] **Automatic HTTPS Rewrites = ON** (SSL/TLS > Edge Certificates)
- [ ] **Remove X-Powered-By = ON** (Rules > Settings > Managed Transforms)
- [ ] **Add True-Client-IP header = ON** (Rules > Settings > Managed Transforms)
- [ ] **Brotli = ON** (Speed > Optimization)
- [ ] **HTTP/2 = ON** (Network)
- [ ] **HTTP/3 = ON** (Network)
- [ ] **WebSockets = ON** (Network)
- [ ] **IP Geolocation = ON** (Network)
- [ ] **Add SPF/DMARC DNS records** (DNS > Records)
- [ ] **Always Online = OFF** (Caching)
- [ ] **Crawler Hints = OFF** (Caching)

### After testing (may affect agent traffic)

- [ ] **Bot Fight Mode = OFF** (Security > Bots)
- [ ] **Browser Integrity Check = OFF** (Security > Settings)
- [ ] **Security Level = Low or Medium** (Security > Settings)
- [ ] **WAF Managed Ruleset = ON** (Security > WAF) — monitor for false positives
- [ ] **Cache bypass rule for /v1/** (Caching > Cache Rules)
- [ ] **API no-cache transform rule** (Rules > Transform Rules)

### After validating (requires coordination)

- [ ] **Authenticated Origin Pulls = ON** (SSL/TLS > Origin Server) + nginx config change
- [ ] **Cloudflare IP rate limiting rules** (Security > WAF > Rate Limiting)
- [ ] **UFW restrict port 443 to Cloudflare IPs** (server-side)
- [ ] **nginx set_real_ip_from Cloudflare** (server-side)

---

## 11. Monitoring

After applying changes, monitor for 24-48 hours:

1. **Cloudflare Analytics > Security** — check for false positive blocks
2. **Cloudflare Analytics > Traffic** — verify no drop in legitimate traffic
3. **Application logs** — check for increased 403s or connection errors
4. **Agent client tests** — run your SDK test suite against the live API
5. **SSL Labs test** — run `ssllabs.com/ssltest` against api.greenhelix.net to verify TLS config

---

## 12. Settings NOT Recommended

| Setting | Why Skip |
|---------|----------|
| Web3 Gateway | Not relevant to this platform |
| Cloudflare Access (Zero Trust) | Adds authentication layer that would break public API access |
| Under Attack Mode | Challenges every request — breaks all agent clients |
| Auto Minify | API returns JSON, not HTML/JS/CSS |
| Rocket Loader | JavaScript-only optimization |
| Mirage/Polish | Image-only optimizations |
| Email Routing | Only if you want Cloudflare to handle email for the domain |
