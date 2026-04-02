{
  "timestamp": "2026-04-02T04:23:31Z",
  "server_version": "0.8.4",
  "tests": 117,
  "requests": 331,
  "findings_count": 12,
  "findings_by_severity": {
    "CRITICAL": 6,
    "MEDIUM": 4,
    "HIGH": 2
  },
  "findings": [
    {
      "id": "AUTH-OLD-KEY",
      "title": "Old/revoked API key still works",
      "severity": "CRITICAL",
      "category": "Authentication",
      "detail": "Old key returned 200",
      "evidence": {}
    },
    {
      "id": "BFLA-PROCESS_SUBS-PRO",
      "title": "BFLA: pro key accessed admin endpoint /v1/payments/subscriptions/process-due",
      "severity": "CRITICAL",
      "category": "BFLA",
      "detail": "status=200",
      "evidence": {}
    },
    {
      "id": "BFLA-REVOKE_KEY-FREE",
      "title": "BFLA: free key accessed admin endpoint /v1/infra/keys/revoke",
      "severity": "CRITICAL",
      "category": "BFLA",
      "detail": "status=200",
      "evidence": {}
    },
    {
      "id": "BFLA-REVOKE_KEY-PRO",
      "title": "BFLA: pro key accessed admin endpoint /v1/infra/keys/revoke",
      "severity": "CRITICAL",
      "category": "BFLA",
      "detail": "status=200",
      "evidence": {}
    },
    {
      "id": "RACE-DEP",
      "title": "Race condition: balance mismatch (expected 100009.98, got 99999.98)",
      "severity": "CRITICAL",
      "category": "Race Condition",
      "detail": "initial=99999.98 + 10 deposits = 100009.98, actual=99999.98",
      "evidence": {}
    },
    {
      "id": "AMT-500-NEGATIVE",
      "title": "Deposit crashes on negative amount (-100)",
      "severity": "MEDIUM",
      "category": "Business Logic",
      "detail": "amount=-100 \u2192 500 (should be 422)",
      "evidence": {}
    },
    {
      "id": "AMT-500-NEGATIVE_SMALL",
      "title": "Deposit crashes on negative_small amount (-0.01)",
      "severity": "MEDIUM",
      "category": "Business Logic",
      "detail": "amount=-0.01 \u2192 500 (should be 422)",
      "evidence": {}
    },
    {
      "id": "AMT-500-ZERO",
      "title": "Deposit crashes on zero amount (0)",
      "severity": "MEDIUM",
      "category": "Business Logic",
      "detail": "amount=0 \u2192 500 (should be 422)",
      "evidence": {}
    },
    {
      "id": "ESCROW-CANCEL-BOLA",
      "title": "Non-payer cancelled escrow",
      "severity": "CRITICAL",
      "category": "BOLA",
      "detail": "free agent cancelled escrow owned by pro",
      "evidence": {}
    },
    {
      "id": "INTENT-CAPTURE-500",
      "title": "Intent capture by wrong agent causes 500",
      "severity": "MEDIUM",
      "category": "Business Logic",
      "detail": "Non-owner capture crashes server (should be 403)",
      "evidence": {}
    },
    {
      "id": "RL-BURST-30",
      "title": "No rate limiting on 30 concurrent requests",
      "severity": "HIGH",
      "category": "Rate Limiting",
      "detail": "codes={200: 30}",
      "evidence": {}
    },
    {
      "id": "RL-SUSTAINED",
      "title": "No rate limiting at sustained 20 req/s",
      "severity": "HIGH",
      "category": "Rate Limiting",
      "detail": "60 requests: {200: 60}",
      "evidence": {}
    }
  ],
  "status_distribution": {
    "-2": 3,
    "200": 252,
    "201": 2,
    "400": 6,
    "401": 10,
    "403": 41,
    "404": 5,
    "409": 1,
    "422": 5,
    "500": 6
  },
  "duration_s": 395.6
}