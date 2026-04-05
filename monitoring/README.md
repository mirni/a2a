# A2A Monitoring Stack

Full-fat observability stack for the A2A Commerce Platform: metrics,
logs, dashboards, and alerting — all self-hosted via docker compose.

## Stack

| Service | Image | Purpose | Default port |
| --- | --- | --- | --- |
| Prometheus | `prom/prometheus:v2.53.0` | Metrics scraping + storage (30d retention) | 9090 |
| Grafana | `grafana/grafana:11.1.0` | Dashboards + ad-hoc querying | 3030 |
| Alertmanager | `prom/alertmanager:v0.27.0` | Alert routing (email, Slack, PagerDuty) | 9093 |
| Loki | `grafana/loki:3.1.0` | Log aggregation | 3100 |
| Promtail | `grafana/promtail:3.1.0` | journalctl → Loki shipper | — |
| node-exporter | `prom/node-exporter:v1.8.1` | Host-level metrics (CPU, mem, disk) | 9100 |

Ports are overridable via env vars (`PROMETHEUS_PORT`, `GRAFANA_PORT`,
etc.) — see `docker-compose.yml`.

---

## Quick start

```bash
cd monitoring
docker compose up -d
# Grafana → http://localhost:3030  (admin / admin, change on first login)
```

The stack scrapes the gateway at `host.docker.internal:8000` by default.
Override with:

```bash
A2A_GATEWAY_HOST=api.greenhelix.net:443 ./run_monitor.sh
```

`run_monitor.sh` renders `prometheus/prometheus.yml` from the template
before `docker compose up`.

---

## What gets scraped

See `prometheus/prometheus.yml`. The gateway exposes Prometheus-format
metrics at `GET /v1/metrics` (IP-allow-listed via
`METRICS_ALLOWED_IPS` env var).

**Application metrics** (prefix `a2a_*`):

| Metric | Type | Labels |
| --- | --- | --- |
| `a2a_requests_total` | counter | `method`, `route`, `status` |
| `a2a_errors_total` | counter | `route`, `error_type` |
| `a2a_request_duration_ms` | histogram | `route` |
| `a2a_auth_failures_total` | counter | `reason` |
| `a2a_db_errors_total` | counter | `db`, `operation` |
| `a2a_webhook_failures_total` | counter | `destination` |
| `a2a_backup_last_success_timestamp` | gauge | — |

**Host metrics** (prefix `node_*`): CPU, memory, disk, filesystem, load.

---

## Dashboards

Grafana loads dashboards from `grafana/dashboards/*.json` on startup:

| Dashboard | Purpose |
| --- | --- |
| `gateway-overview.json` | RED method (Rate / Errors / Duration) per route |
| `business-metrics.json` | Revenue, wallet balances, payment success rate |
| `infra-health.json` | CPU / memory / disk / open files per host |

Add new dashboards by dropping JSON exports into `grafana/dashboards/`
and restarting the `grafana` service.

---

## Alerts

Rules live in `prometheus/alerts.yml`. See `docs/sre/alerts.md` for
the full SLO map, on-call playbook, and alert-to-runbook mapping.

Alerts route through `alertmanager/alertmanager.yml` → configured
receivers (email/Slack/PagerDuty).

**To add a new alert:**
1. Edit `prometheus/alerts.yml` with a new `- alert:` stanza
2. `docker compose kill -s HUP prometheus` to hot-reload
3. Verify in Prometheus UI → Alerts tab
4. Document the runbook in `docs/sre/alerts.md`

---

## Loki / log queries

Grafana → Explore → Loki datasource. Example queries:

```logql
# All gateway errors in the last hour
{unit="a2a-gateway.service"} |= "ERROR" | json

# 5xx responses only
{unit="a2a-gateway.service"} |~ `HTTP/1\.[01]" 5\d\d`

# Specific agent
{unit="a2a-gateway.service"} | json | agent_id="agent-123"
```

---

## Operations

### Reload Prometheus config without restart

```bash
docker compose kill -s HUP prometheus
```

### Check Alertmanager receiver config

```bash
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
```

### Export current dashboards from Grafana

Grafana UI → Dashboard → Share → Export → Save to file → copy into
`grafana/dashboards/` and commit.

### Disk usage

Prometheus TSDB retains 30 days. Expect ~500 MB – 2 GB per month of
scraped data. Loki retains logs per its own config (default 7 days —
see `loki/loki.yml`).

---

## Security notes

- **Grafana admin password**: change from default `admin` immediately.
  Set `GRAFANA_ADMIN_PASSWORD` in a shell env or `.env` before `up`.
- **Metrics endpoint is IP-allow-listed** on the gateway side. Add the
  monitoring host's IP to `METRICS_ALLOWED_IPS` in gateway env.
- **Do not expose ports 9090/9093/3100** on a public interface. Bind
  to localhost or put them behind Tailscale / nginx basic-auth.
- **Alertmanager receiver secrets** (Slack webhooks, PagerDuty keys)
  belong in `alertmanager.yml` via env vars, not committed literals.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Prometheus "up=0" for gateway target | IP not in `METRICS_ALLOWED_IPS`; or wrong `A2A_GATEWAY_HOST` |
| Grafana dashboards empty | Prometheus datasource URL wrong — check `grafana/provisioning/datasources/` |
| Alerts firing but no notification | `amtool check-config` and check Alertmanager UI → Status |
| Loki "no logs" | Promtail container lacks access to `/var/log/journal` — see compose volumes |
| Out-of-memory on Prometheus | Reduce retention: `--storage.tsdb.retention.time=14d` |

---

*Owner: CTO. Review cadence: quarterly. Last reviewed: 2026-04-05.*
