# Execution and recovery

```mermaid
sequenceDiagram
  participant API as Authenticated event API
  participant DB as PostgreSQL + outbox
  participant B as Kafka
  participant W as Temporal
  participant G as Policy gateway
  participant V as Mock vendor store
  API->>DB: validate, dedupe event and create cart workflow atomically
  DB->>B: publish outbox (at least once)
  B->>W: start stable workflow ID
  W->>DB: resolve source context, record policy decision and stable cohort
  W->>G: approved intent
  G->>V: lookup tenant/action receipt before retries
  G->>DB: recheck consent, cases, order, stock, cap, approval, switches
  G->>V: accept approved mock journey with stable key
  alt acknowledgement lost or worker crash
    W->>G: retry activity
    G->>V: reconcile existing receipt, never resend accepted action
  end
  G->>DB: persist action, confirmed mock exposure and action-event outbox
  API->>DB: authoritative synthetic order event closes observation
  W->>DB: observe completion or expire window
```

Unconfirmed vendor status goes to FAILED_REVIEW and DLQ. Only operator replay can reopen it, and replay revalidates policy and reconciles first. Permanent errors cannot be replayed. Duplicate event IDs with changed contents are rejected; different abandonment event IDs for the same tenant/cart reuse the workflow. Late order events never reopen an action. Workflow cancellation prevents subsequent activation. Normal retries are bounded and Temporal schedules backoff; inline mode is a synchronous testing convenience.
