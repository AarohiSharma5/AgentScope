# Architecture

AgentScope is a layered system: a lightweight SDK/engine layer produces traces, a
Flask service layer persists and queries them, a database stores everything, and
a React dashboard (plus REST API and CLI) surfaces it. All diagrams below render
on GitHub via Mermaid.

## System overview

```mermaid
flowchart LR
    subgraph App["Your AI App"]
        SDKC["agentscope-lite SDK<br/>(trace · Agent · Tool · Workflow)"]
        TR["TraceRecorder<br/>(request + agent + RAG)"]
        ORC["AgentOrchestrator · WorkflowEngine"]
        ENG["ReplayEngine · EvaluationEngine<br/>ModelComparisonEngine"]
    end

    subgraph FE["Frontend — React + nginx :8080"]
        UI["Dashboards: Requests · Agent Runs · RAG<br/>Workflows · Conversations · Replays<br/>Evaluations · Comparisons · Diffs · Analytics · Live"]
    end

    CLI["agentscope CLI"]

    subgraph BE["Backend — Flask + gunicorn :8000"]
        API["REST API (routes)"]
        SVC["Service layer<br/>trace · workflow · message · replay<br/>evaluation · comparison · prompt · diff · auth · audit"]
        SUB["Subsystems<br/>streaming · plugins · providers · exporting"]
    end

    DB[("PostgreSQL / SQLite")]

    SDKC -->|"POST /api/traces"| API
    TR -->|"persist via services"| SVC
    ORC --> SVC
    ENG --> SVC
    UI -->|"GET /api/* (proxied)"| API
    CLI -->|"REST"| API
    UI -->|"SSE /api/stream"| API
    API --> SVC
    API --> SUB
    SVC --> DB
    SUB --> DB
```

The three services run as containers on one Docker network: the React app
(nginx) proxies `/api` to the Flask backend, which persists to the database. The
SDK/engine layer stays lightweight — all persistence and business logic live in
the service layer, never in routes.

## Request → trace lifecycle

```mermaid
sequenceDiagram
    participant App as Your app (SDK)
    participant API as Flask API
    participant SVC as Service layer
    participant DB as Database
    participant LTM as LiveTraceManager
    participant UI as Dashboard

    App->>API: POST /api/traces
    API->>SVC: create_trace(payload)
    SVC->>DB: INSERT trace (+ agent runs, steps, tools...)
    SVC-->>LTM: emit(trace.finished, ...)
    LTM-->>UI: SSE event (live update)
    App->>API: GET /api/traces/:id
    API->>SVC: get_trace(id)
    SVC->>DB: SELECT
    DB-->>App: serialized trace
```

## Data model (high level)

```mermaid
erDiagram
    Trace ||--o{ AgentRun : has
    AgentRun ||--o{ AgentStep : has
    AgentStep ||--o{ ToolExecution : records
    AgentStep ||--o{ MemoryAccess : records
    AgentStep ||--o{ RetrieverTrace : records
    RetrieverTrace ||--o{ RetrievedDocument : returns
    AgentRun ||--o{ PromptVersion : versions
    ConversationRun ||--o{ AgentNode : contains
    ConversationRun ||--o{ AgentMessage : logs
    WorkflowDefinition ||--o{ WorkflowExecution : runs
    ConversationRun ||--o{ ReplayRun : replayed_by
    ConversationRun ||--o{ EvaluationRun : evaluated_by
    EvaluationRun ||--o{ EvaluationMetric : has
    ConversationRun ||--o{ ModelComparison : compared_in
```

## Multi-tenancy & auth (v1.0)

```mermaid
erDiagram
    Organization ||--o{ Membership : has
    User ||--o{ Membership : in
    Organization ||--o{ Project : owns
    Organization ||--o{ ApiKey : issues
    Project ||--o{ ApiKey : scopes
    Organization ||--o{ AuditLog : records
```

- `Organization` is the tenant boundary; `Project` is the finest isolation scope.
- A `User` belongs to organizations through a `Membership` carrying a role
  (`admin` / `developer` / `viewer`).
- `ApiKey`s are scoped to an organization (and optionally a project); only their
  SHA-256 hash is stored.
- Authorization funnels through a single `authorize_org` / `authorize_project`
  choke point for consistent isolation and RBAC.

## v0.5 engine flow

```mermaid
flowchart LR
    CONV[("Traced conversation")] --> REPLAY["ReplayEngine<br/>rebuild snapshot →<br/>re-run under new model/params"]
    REPLAY --> NEWCONV[("Replay conversation<br/>+ ReplayRun")]
    NEWCONV --> EVAL["EvaluationEngine<br/>pluggable evaluators →<br/>weighted overall score"]
    EVAL --> ER[("EvaluationRun<br/>+ EvaluationMetrics")]
    CONV --> CMP["ModelComparisonEngine<br/>replay + evaluate each model"]
    CMP --> CR[("ModelComparison records<br/>+ summary / side-by-side")]
```

## Extension subsystems (v0.6)

```mermaid
flowchart TB
    subgraph Streaming
        SVC1[Service events] --> LTM[LiveTraceManager] --> SSE[SSE / WebSocket] --> LIVE[Live dashboard]
    end
    subgraph Plugins
        DISC[Auto-discovery] --> REG1[PluginRegistry] --> CONTRIB[Tools · Evaluators · Memories<br/>Retrievers · LLM providers · UI]
    end
    subgraph Providers
        ADPT[Adapters self-register] --> REG2[ProviderRegistry] --> DISC2[Discoverable capabilities]
    end
    subgraph ExportImport
        COLLECT[Collect entities] --> BUNDLE[Trace Bundle] --> FMT[OTel · JSON · CSV · SQLite · PG · Zip]
        BUNDLE --> IMP[Importers → DB reconstruction → replay]
    end
```

## Directory map

```
AgentScope/
├── docker-compose.yml           # db + backend + frontend, one command
├── docs/                        # this documentation
├── examples/                    # runnable example programs
├── backend/
│   └── app/
│       ├── __init__.py          # app factory
│       ├── config.py            # env-based config (Postgres / SQLite fallback)
│       ├── models/              # trace, agent_trace, rag_trace, workflow_trace,
│       │                        #   evaluation_trace, auth
│       ├── routes/              # traces, agent_traces, chat, rag, workflows,
│       │                        #   evaluations, stream, plugins, providers,
│       │                        #   exports, auth, organizations
│       ├── services/            # trace, workflow, message, replay, evaluation,
│       │                        #   comparison, prompt, diff, auth, audit
│       ├── orchestration/       # AgentOrchestrator, WorkflowEngine, ReplayEngine
│       ├── evaluation/          # EvaluationEngine + pluggable evaluators
│       ├── comparison/          # ModelComparisonEngine
│       ├── retrieval/           # vendor-neutral RetrievalService + adapters
│       ├── streaming/           # LiveTraceManager + events (v0.6)
│       ├── plugins/             # PluginManager/Registry/Loader/Base (v0.6)
│       ├── providers/           # provider abstraction + adapters (v0.6)
│       ├── exporting/           # export/import subsystem (v0.6)
│       ├── auth/                # JWT, keys, roles, rate limit, decorators (v1.0)
│       ├── serializers/         # reusable ORM→JSON serializers
│       └── utils/               # trace_recorder SDK, pagination, validation
├── frontend/                    # React (Vite) + Tailwind, nginx-served
└── sdk/                         # agentscope-lite package (SDK + CLI)
```

## Design principles

- **Layered & additive** — each version extends without breaking earlier ones.
- **No business logic in routes** — routes validate and delegate to services.
- **Vendor-neutral** — providers, retrievers and model names are pluggable
  strings; no hard dependency on any vendor.
- **Backward compatible** — SQLite and PostgreSQL both supported; auth is opt-in.
