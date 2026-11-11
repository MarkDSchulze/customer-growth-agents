# Components and ownership

```mermaid
flowchart TD
  UI[Next.js operator console] --> API[FastAPI: signed identity and tenant scope]
  API --> DB[(PostgreSQL: receipts, workflows, decisions, audit, outbox)]
  DB --> E[Outbox dispatcher / Kafka consumer]
  E --> K[Kafka local broker]
  K --> E
  E --> T[Temporal durable workflow]
  T --> A[Marketing / Advertising / Sales / Commerce / Service planners]
  A --> P[Deterministic policy and experiment assignment]
  P --> G[Execution gateway: recheck, approval, kill switch]
  G --> M[Typed mock context and journey adapters]
  M --> V[(Independent synthetic vendor receipts)]
  G --> DB
```

Implementation map: `growth.api` authenticates operators/producers; `growth.engine` owns transactional orchestration metadata; `growth.agents` returns typed proposals; `growth.policy` applies hard gates; `growth.adapters` defines protocol boundaries and mock implementations; `growth.event_worker` owns broker delivery; `growth.temporal_worker` owns durable timers and bounded retry orchestration. [ADR-007](adr/007-local-reference-runtime.md) explains the deployment and storage choices.
