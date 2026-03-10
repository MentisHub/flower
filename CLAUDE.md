# CLAUDE.md — flower/

Fork of the Flower framework on branch `mentishub`. Do not merge upstream without review — this branch carries MentisHub-specific additions that are not upstream-compatible.

Docs: flower/framework/docs/source

## MentisHub Additions (branch: `mentishub`)

Three feature branches merged into `mentishub`: `stream-events` and `install-dependencies`.

### 1. `stream-events` — Real-time FL event streaming

`PushEvents` RPC added to Fleet, ClientAppIo, and ServerAppIo. Nodes/apps push structured events to SuperLink; platform consumes via `StreamEvents` (control.proto) and translates into `TrainingRun`/`Round`/`Node` status updates using `EventEmitter2`.

**Key files:**
```
framework/proto/flwr/proto/event.proto       # EventType enum + Event + PushEventsRequest
framework/py/flwr/common/events.py           # EventDispatcher + EventUploader (thread-safe pub/sub)
framework/py/flwr/common/constant.py         # EVENT_UPLOAD_INTERVAL, EVENT_HISTORY_MAX_SIZE
```

**EventDispatcher:** thread-safe pub/sub, capped history. Used by SuperLink's `StreamEvents` to stream to platform.
**EventUploader:** background thread, batches + uploads via `PushEvents` at `EVENT_UPLOAD_INTERVAL`.

**Integration points:** `message_handler.py` (node task events), `flwr/server/` (round/run/node lifecycle), `fleet_servicer.py` (`PushEvents` handler), `grpc_rere_client/` (client-side wiring).

### 2. `install-dependencies` — Content-addressable FAB dependency installation

Allows FABs to declare `[project].dependencies` in `pyproject.toml`; both **ServerApp** and **ClientApp** install them before starting, controlled by `run.install_deps` (a field on the `Run` proto, stored in LinkState).

**Key files:**
```
framework/py/flwr/common/deps.py                     # install_dependencies(), add_deps_to_sys_path()
framework/py/flwr/cli/install.py                     # install_from_fab() + _install_deps_from_fab()
framework/py/flwr/server/serverapp/app.py            # install_from_fab(..., install_deps=run.install_deps)
framework/py/flwr/supernode/runtime/run_clientapp.py # same, for ClientApp process
framework/py/flwr/simulation/run_simulation.py       # same, for simulation mode
```

**Mechanism:** deps installed to `~/.flwr/deps/<sha256>/` keyed by sorted SHA-256 of the dependency list. Idempotent — skipped if directory exists and is non-empty. Added to `sys.path` before app import.

## Constraints

- **Branch:** always stay on `mentishub` — never rebase onto upstream `main` without a full compatibility review of the four modified proto files and `events.py`/`deps.py`
- **Proto changes:** any change to `event.proto`, `control.proto`, `fleet.proto`, `clientappio.proto`, or `serverappio.proto` requires regenerating `@platform/proto` (`pnpm flower:proto` inside Docker)
- **EventType enum:** values are persisted as integers in platform DB (mapped to `RoundStatus`/`TrainingStatus`/`NodeStatus`) — never reorder or remove existing enum values, only append
- **deps.py:** deps directory is content-addressable by SHA-256 of sorted dep list — changing sort order or hash input would break existing installs
