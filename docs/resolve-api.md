# Proposed Resolve endpoint for Control Room

Control Room files incidents into Resolve. Resolve does not have this API yet; add it in the
Resolve repo as its own small PR, behind an env flag, before setting `RESOLVE_URL` here.

## Auth
- A service account user ("Control Room") with a scoped API token.
- `Authorization: Bearer <token>`; the token may only create and update tickets it created,
  in the on-call queue. Store a hash, not the token. Rotate by issuing a new one.

## Endpoints (all JSON)

`POST /api/integrations/control-room/tickets` → `201 {"id": "RSV-1042"}`
```json
{
  "title": "RepoLens “Scans finish” SLO burning 15.1× budget",
  "priority": "P1",
  "service": "repolens",
  "slo": "scan-success",
  "tier": "page-1h",
  "context": {
    "remaining": 0.457,
    "burn": {"5m": 80.0, "1h": 15.1, "6h": 2.9, "3d": 0.6, "28d": 0.54},
    "error_ratio": {"5m": 0.40, "1h": 0.0754}
  }
}
```
Priority maps to Resolve's SLA policy: P1 respond 30 m / resolve 4 h, P2 1 h / 8 h, P3 1 d / 5 d.
The SLA clock starts at creation.

`POST /api/integrations/control-room/tickets/{id}/notes` `{"text": "...", "internal": true}` → `204`

`PATCH /api/integrations/control-room/tickets/{id}` `{"status": "open" | "monitoring" | "resolved"}` → `204`

## Idempotency
Send `Idempotency-Key: <service>/<slo>/<class>/<opened_at>` on create, so a retried request
never opens a second ticket. (Not yet sent by `ResolveSink`; see roadmap M4.)
