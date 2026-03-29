#!/usr/bin/env bash
# =============================================================================
# A2A Commerce Platform — Server Smoke Tests
#
# Usage:
#   ./check_server.sh                          # defaults to https://api.greenhelix.net
#   ./check_server.sh https://localhost:8000    # custom base URL
#   API_KEY=ak_... ./check_server.sh           # with API key for auth tests
# =============================================================================

set -euo pipefail

BASE="${1:-https://api.greenhelix.net}"
BASE="${BASE%/}"
API_KEY="${API_KEY:-}"

PASS=0
FAIL=0
SKIP=0

green()  { printf '\033[0;32m%s\033[0m' "$*"; }
red()    { printf '\033[0;31m%s\033[0m' "$*"; }
yellow() { printf '\033[1;33m%s\033[0m' "$*"; }

pass() { echo "  $(green PASS)  $1"; PASS=$((PASS + 1)); }
fail() { echo "  $(red FAIL)  $1"; shift; [[ $# -gt 0 ]] && echo "        $*"; FAIL=$((FAIL + 1)); }
skip() { echo "  $(yellow SKIP)  $1"; SKIP=$((SKIP + 1)); }

# Curl wrappers
get()  { curl -sf --max-time 10 "${BASE}$1"; }
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }
post() { curl -s --max-time 10 -X POST -H "Content-Type: application/json" "$@"; }
jq_check() { python3 -c "import sys,json; d=json.load(sys.stdin); $1"; }

echo ""
echo "A2A Server Smoke Tests"
echo "Target: $BASE"
echo "$(date -Iseconds)"
echo "======================================"

# ---------------------------------------------------------------------------
# 1. Public endpoints
# ---------------------------------------------------------------------------
echo ""
echo "--- Public Endpoints ---"

# Health
HEALTH=$(get /v1/health 2>&1) && pass "GET /v1/health returns 200" || fail "GET /v1/health returns 200" "$HEALTH"

echo "$HEALTH" | jq_check "assert d['status']=='ok'" 2>/dev/null \
    && pass "health status=ok" || fail "health status=ok"

echo "$HEALTH" | jq_check "assert d['tools']>0, f\"tools={d['tools']}\"" 2>/dev/null \
    && pass "health tools > 0" || fail "health tools > 0"

# Pricing
PRICING=$(get /v1/pricing 2>&1) && pass "GET /v1/pricing returns 200" || fail "GET /v1/pricing returns 200" "$PRICING"
echo "$PRICING" | jq_check "assert len(d)>0" 2>/dev/null \
    && pass "pricing catalog non-empty" || fail "pricing catalog non-empty"

# OpenAPI
get /v1/openapi.json >/dev/null 2>&1 \
    && pass "GET /v1/openapi.json returns 200" || fail "GET /v1/openapi.json returns 200"

# Metrics
get /v1/metrics >/dev/null 2>&1 \
    && pass "GET /v1/metrics returns 200" || fail "GET /v1/metrics returns 200"

# Signing key
get /v1/signing-key >/dev/null 2>&1 \
    && pass "GET /v1/signing-key returns 200" || fail "GET /v1/signing-key returns 200"

# Backward-compat redirect
STATUS=$(code -X GET "${BASE}/health")
[[ "$STATUS" =~ ^30[17]$ ]] \
    && pass "GET /health redirects ($STATUS)" || fail "GET /health redirects (got $STATUS)"

# ---------------------------------------------------------------------------
# 2. Auth enforcement
# ---------------------------------------------------------------------------
echo ""
echo "--- Auth Enforcement ---"

STATUS=$(code -X POST -H "Content-Type: application/json" \
    -d '{"tool":"get_balance","params":{"agent_id":"test"}}' \
    "${BASE}/v1/execute")
[[ "$STATUS" == "401" || "$STATUS" == "402" ]] \
    && pass "no key → $STATUS (rejected)" || fail "no key → 401/402 (got $STATUS)"

STATUS=$(code -X POST -H "Content-Type: application/json" \
    -H "Authorization: Bearer fake_key_12345" \
    -d '{"tool":"get_balance","params":{"agent_id":"test"}}' \
    "${BASE}/v1/execute")
[[ "$STATUS" == "401" ]] \
    && pass "bad key → 401" || fail "bad key → 401 (got $STATUS)"

# ---------------------------------------------------------------------------
# 3. Authenticated tool execution
# ---------------------------------------------------------------------------
echo ""
echo "--- Tool Execution (requires API_KEY) ---"

if [[ -z "$API_KEY" ]]; then
    skip "get_balance — no API_KEY set"
    skip "get_usage_summary — no API_KEY set"
    skip "search_services — no API_KEY set"
    skip "get_trust_score — no API_KEY set"
    skip "check_db_integrity — no API_KEY set"
    skip "unknown tool → 400 — no API_KEY set"
else
    exec_tool() {
        post -H "Authorization: Bearer ${API_KEY}" \
            -d "{\"tool\":\"$1\",\"params\":$2}" \
            "${BASE}/v1/execute"
    }

    exec_tool_code() {
        code -X POST -H "Content-Type: application/json" \
            -H "Authorization: Bearer ${API_KEY}" \
            -d "{\"tool\":\"$1\",\"params\":$2}" \
            "${BASE}/v1/execute"
    }

    # get_balance (free tier) — smoke-test has no wallet, so accept either result or structured error
    RESP=$(exec_tool get_balance '{"agent_id":"smoke-test"}' 2>&1) \
        && echo "$RESP" | jq_check "assert 'result' in d or 'error' in d, d" 2>/dev/null \
        && pass "get_balance returns response" \
        || fail "get_balance" "$RESP"

    # get_usage_summary
    RESP=$(exec_tool get_usage_summary '{"agent_id":"smoke-test"}' 2>&1) \
        && echo "$RESP" | jq_check "assert 'result' in d, d" 2>/dev/null \
        && pass "get_usage_summary returns result" \
        || fail "get_usage_summary" "$RESP"

    # search_services
    RESP=$(exec_tool search_services '{"query":"test"}' 2>&1) \
        && echo "$RESP" | jq_check "assert 'result' in d, d" 2>/dev/null \
        && pass "search_services returns result" \
        || fail "search_services" "$RESP"

    # get_trust_score — uses server_id, accept result or structured error (no server registered)
    RESP=$(exec_tool get_trust_score '{"server_id":"smoke-test"}' 2>&1) \
        && echo "$RESP" | jq_check "assert 'result' in d or 'error' in d, d" 2>/dev/null \
        && pass "get_trust_score returns response" \
        || fail "get_trust_score" "$RESP"

    # check_db_integrity (pro tier)
    RESP=$(exec_tool check_db_integrity '{"database":"billing"}' 2>&1) \
        && echo "$RESP" | jq_check "assert d.get('result',{}).get('ok')==True, d" 2>/dev/null \
        && pass "check_db_integrity ok=true" \
        || fail "check_db_integrity" "$RESP"

    # Unknown tool
    STATUS=$(exec_tool_code nonexistent_tool_xyz '{}')
    [[ "$STATUS" == "400" ]] \
        && pass "unknown tool → 400" || fail "unknown tool → 400 (got $STATUS)"
fi

# ---------------------------------------------------------------------------
# 4. TLS
# ---------------------------------------------------------------------------
echo ""
echo "--- TLS ---"

if [[ "$BASE" == https://* ]]; then
    DOMAIN=$(echo "$BASE" | sed 's|https://||;s|/.*||;s|:.*||')

    echo | openssl s_client -connect "${DOMAIN}:443" -servername "$DOMAIN" 2>/dev/null \
        | grep -q 'Verify return code: 0' \
        && pass "TLS handshake valid" || fail "TLS handshake"

    echo | openssl s_client -connect "${DOMAIN}:443" -servername "$DOMAIN" 2>/dev/null \
        | openssl x509 -noout -checkend 604800 2>/dev/null \
        && pass "Certificate valid > 7 days" || fail "Certificate expiring soon"
else
    skip "TLS — not HTTPS"
    skip "Certificate — not HTTPS"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "======================================"
TOTAL=$((PASS + FAIL + SKIP))
echo "Total: $TOTAL | $(green "Pass: $PASS") | $(red "Fail: $FAIL") | $(yellow "Skip: $SKIP")"
echo ""

if [[ $FAIL -gt 0 ]]; then
    red "SOME CHECKS FAILED"; echo ""
    exit 1
else
    green "ALL CHECKS PASSED"; echo ""
    exit 0
fi
