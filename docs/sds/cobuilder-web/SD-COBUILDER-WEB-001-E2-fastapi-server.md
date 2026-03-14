---
title: "SD-COBUILDER-WEB-001 Epic 2: FastAPI Web Server Core"
status: active
type: solution-design
last_verified: 2026-03-12
grade: authoritative
prd_ref: PRD-COBUILDER-WEB-001
epic: E2
---

# SD-COBUILDER-WEB-001 Epic 2: FastAPI Web Server Core

## 1. Problem Statement

The CoBuilder pipeline system currently has no programmatic HTTP interface. Operators interact with initiatives through CLI tools (`cobuilder pipeline node-ops`, `cobuilder pipeline edge-ops`), direct filesystem manipulation, and manual signal file creation. The web frontend (E7-E9) requires a REST API layer that exposes initiative lifecycle operations, artifact browsing, and `wait.human` signal writing over HTTP.

This epic builds the FastAPI application that serves as the backend for all web UI operations. It wraps the existing Python modules (`parser.py`, `node_ops.py`, `signal_protocol.py`, `InitiativeManager` from E1) behind a clean REST interface with Pydantic request/response models, path-traversal-safe artifact serving, and CORS configuration for the localhost development frontend.

**Dependency**: Epic 1 (Initiative DOT Graph Lifecycle) must be complete. This epic consumes `InitiativeManager.create()`, `detect_phase()`, `get_pending_reviews()`, `extend_after_prd_review()`, and `extend_after_sd_review()`.

---

## 2. Technical Architecture

### 2.1 FastAPI Application Structure

```
cobuilder/web/
├── __init__.py
├── api/
│   ├── __init__.py
│   ├── main.py              # FastAPI app factory, CORS, lifespan, router mounting
│   ├── config.py            # Settings via pydantic-settings (env vars)
│   ├── dependencies.py      # Shared FastAPI dependencies (InitiativeManager, etc.)
│   ├── models.py            # All Pydantic request/response schemas
│   └── routers/
│       ├── __init__.py
│       ├── initiatives.py   # CRUD for initiatives (create, list, get)
│       ├── artifacts.py     # PRD/SD markdown content serving
│       └── signals.py       # Signal writing + graph extension triggers
```

### 2.2 Router Organization

| Router | Prefix | Responsibility |
|--------|--------|----------------|
| `initiatives` | `/api/initiatives` | Create, list, get initiatives; list artifacts per initiative |
| `artifacts` | `/api/artifacts` | Serve raw markdown file content by path |
| `signals` | `/api/initiatives/{id}/signal` and `.../extend` | Write signal files, trigger graph extension |

All routers are mounted on the single FastAPI app instance. No sub-applications or middleware beyond CORS.

### 2.3 Configuration

Settings are loaded from environment variables via `pydantic-settings`:

```python
# cobuilder/web/api/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Web server configuration."""

    project_target_repo: str
    """Absolute path to the target repository root.
    All DOT files live under {project_target_repo}/.claude/attractor/pipelines/.
    All artifacts (PRDs, SDs) are resolved relative to this root."""

    pipelines_dir: str = ""
    """Override for pipeline DOT directory. Defaults to
    {project_target_repo}/.claude/attractor/pipelines/ if empty."""

    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:3001"]
    """Allowed CORS origins for the frontend dev server."""

    host: str = "127.0.0.1"
    port: int = 8100

    model_config = {"env_prefix": "COBUILDER_WEB_"}

    @property
    def resolved_pipelines_dir(self) -> str:
        if self.pipelines_dir:
            return self.pipelines_dir
        return f"{self.project_target_repo}/.claude/attractor/pipelines"
```

Environment variable mapping:

| Env Var | Field | Required | Default |
|---------|-------|----------|---------|
| `COBUILDER_WEB_PROJECT_TARGET_REPO` | `project_target_repo` | Yes | -- |
| `COBUILDER_WEB_PIPELINES_DIR` | `pipelines_dir` | No | `{target_repo}/.claude/attractor/pipelines` |
| `COBUILDER_WEB_CORS_ORIGINS` | `cors_origins` | No | `["http://localhost:3000", "http://localhost:3001"]` |
| `COBUILDER_WEB_HOST` | `host` | No | `127.0.0.1` |
| `COBUILDER_WEB_PORT` | `port` | No | `8100` |

### 2.4 Dependency Injection

```python
# cobuilder/web/api/dependencies.py
from functools import lru_cache
from .config import Settings

@lru_cache
def get_settings() -> Settings:
    return Settings()

def get_initiative_manager(settings: Settings = Depends(get_settings)) -> InitiativeManager:
    """Return a configured InitiativeManager instance.
    InitiativeManager is stateless (reads DOT files on each call),
    so a new instance per request is fine."""
    return InitiativeManager(
        pipelines_dir=settings.resolved_pipelines_dir,
        target_repo=settings.project_target_repo,
    )
```

---

## 3. API Specification

### 3.1 Pydantic Models

```python
# cobuilder/web/api/models.py
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---

class NodeStatus(str, Enum):
    pending = "pending"
    active = "active"
    impl_complete = "impl_complete"
    validated = "validated"
    failed = "failed"


class NodeHandler(str, Enum):
    start = "start"
    exit = "exit"
    codergen = "codergen"
    tool = "tool"
    wait_human = "wait.human"
    wait_system3 = "wait.system3"
    conditional = "conditional"
    parallel = "parallel"
    research = "research"
    acceptance_test_writer = "acceptance-test-writer"


class SignalAction(str, Enum):
    approve = "approve"
    reject = "reject"


class InitiativePhase(str, Enum):
    definition = "Definition"
    implementation = "Implementation"
    validation = "Validation"
    finalized = "Finalized"


# --- Request Models ---

class CreateInitiativeRequest(BaseModel):
    """POST /api/initiatives request body."""
    prd_id: str = Field(
        ...,
        pattern=r"^PRD-[A-Z0-9-]+$",
        description="PRD identifier, e.g. PRD-DASHBOARD-AUDIT-001",
        examples=["PRD-DASHBOARD-AUDIT-001"],
    )
    description: str = Field(
        ...,
        min_length=10,
        max_length=500,
        description="Brief description of the initiative",
    )
    target_repo: str | None = Field(
        default=None,
        description="Override target repository path. Defaults to server's PROJECT_TARGET_REPO.",
    )


class SignalRequest(BaseModel):
    """POST /api/initiatives/{id}/signal request body."""
    node_id: str = Field(
        ...,
        description="The wait.human node ID to signal",
        examples=["review_prd"],
    )
    action: SignalAction = Field(
        ...,
        description="Approve or reject the gate",
    )
    reason: str | None = Field(
        default=None,
        max_length=2000,
        description="Required when action is 'reject'. Reason for rejection.",
    )


class ExtendRequest(BaseModel):
    """POST /api/initiatives/{id}/extend request body."""
    gate_node_id: str = Field(
        ...,
        description="The wait.human node that was just approved, triggering extension",
        examples=["review_prd", "review_sds"],
    )
    epics: list[str] | None = Field(
        default=None,
        description="Epic identifiers extracted from the approved PRD (for review_prd gate)",
        examples=[["E1", "E2", "E3"]],
    )
    sd_paths: list[str] | None = Field(
        default=None,
        description="SD file paths relative to target_repo (for review_sds gate)",
    )


# --- Response Models ---

class NodeResponse(BaseModel):
    """Single node in a pipeline graph."""
    id: str
    handler: str
    status: NodeStatus
    label: str = ""
    worker_type: str | None = None
    attrs: dict[str, str] = Field(default_factory=dict)


class EdgeResponse(BaseModel):
    """Single edge in a pipeline graph."""
    src: str
    dst: str
    label: str = ""
    condition: str = ""
    attrs: dict[str, str] = Field(default_factory=dict)


class StatusDistribution(BaseModel):
    """Count of nodes by status."""
    pending: int = 0
    active: int = 0
    impl_complete: int = 0
    validated: int = 0
    failed: int = 0


class PendingReview(BaseModel):
    """A wait.human gate that needs human attention."""
    node_id: str
    label: str
    gate_type: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


class InitiativeSummary(BaseModel):
    """GET /api/initiatives list item."""
    id: str = Field(description="PRD ID extracted from DOT graph attributes")
    label: str = Field(description="Human-readable initiative name from DOT graph label")
    dot_path: str = Field(description="Absolute path to the DOT file")
    phase: InitiativePhase
    status_distribution: StatusDistribution
    node_count: int
    pending_reviews: int = Field(description="Count of active wait.human nodes")
    created_at: datetime | None = Field(
        default=None,
        description="File creation time of the DOT file",
    )


class InitiativeDetail(BaseModel):
    """GET /api/initiatives/{id} full state."""
    id: str
    label: str
    dot_path: str
    phase: InitiativePhase
    target_repo: str
    worktree_path: str | None = None
    status_distribution: StatusDistribution
    nodes: list[NodeResponse]
    edges: list[EdgeResponse]
    pending_reviews: list[PendingReview]
    graph_attrs: dict[str, str] = Field(default_factory=dict)


class ArtifactRef(BaseModel):
    """A PRD or SD file referenced in a DOT graph."""
    path: str = Field(description="Path relative to target_repo")
    absolute_path: str
    artifact_type: str = Field(description="'prd' or 'sd'")
    node_id: str = Field(description="DOT node that references this artifact")
    exists: bool = Field(description="Whether the file exists on disk")


class ArtifactListResponse(BaseModel):
    """GET /api/initiatives/{id}/artifacts response."""
    initiative_id: str
    artifacts: list[ArtifactRef]


class ArtifactContentResponse(BaseModel):
    """GET /api/artifacts/{path} response."""
    path: str
    content: str
    size_bytes: int
    last_modified: datetime | None = None


class CreateInitiativeResponse(BaseModel):
    """POST /api/initiatives response."""
    id: str
    dot_path: str
    phase: InitiativePhase
    message: str


class SignalResponse(BaseModel):
    """POST /api/initiatives/{id}/signal response."""
    signal_path: str = Field(description="Absolute path to the written signal file")
    node_id: str
    action: SignalAction
    message: str


class ExtendResponse(BaseModel):
    """POST /api/initiatives/{id}/extend response."""
    initiative_id: str
    gate_node_id: str
    nodes_added: int
    edges_added: int
    message: str


class ErrorResponse(BaseModel):
    """Standard error envelope."""
    detail: str
    error_code: str | None = None
```

### 3.2 Endpoint Specifications

#### POST /api/initiatives

Create a new initiative with a skeleton DOT graph.

```python
# cobuilder/web/api/routers/initiatives.py

@router.post(
    "",
    response_model=CreateInitiativeResponse,
    status_code=201,
    responses={
        409: {"model": ErrorResponse, "description": "Initiative with this PRD ID already exists"},
        422: {"model": ErrorResponse, "description": "Validation error"},
    },
)
async def create_initiative(
    body: CreateInitiativeRequest,
    manager: InitiativeManager = Depends(get_initiative_manager),
    settings: Settings = Depends(get_settings),
) -> CreateInitiativeResponse:
    """Create a new initiative.

    Delegates to InitiativeManager.create() which:
    1. Validates PRD ID uniqueness (no existing DOT file with same prd_id)
    2. Creates a 3-node skeleton DOT graph (start -> write_prd -> review_prd)
    3. Returns the absolute path to the new DOT file
    """
```

**Request**: `CreateInitiativeRequest` (see above)

**Response 201**:
```json
{
    "id": "PRD-DASHBOARD-AUDIT-001",
    "dot_path": "/Users/theb/.claude/attractor/pipelines/prd-dashboard-audit-001.dot",
    "phase": "Definition",
    "message": "Initiative created with skeleton DOT graph"
}
```

**Response 409**: Initiative already exists.

---

#### GET /api/initiatives

List all initiatives with phase detection.

```python
@router.get(
    "",
    response_model=list[InitiativeSummary],
)
async def list_initiatives(
    phase: InitiativePhase | None = Query(default=None, description="Filter by phase"),
    manager: InitiativeManager = Depends(get_initiative_manager),
    settings: Settings = Depends(get_settings),
) -> list[InitiativeSummary]:
    """List all initiatives by scanning the pipelines directory for DOT files.

    For each DOT file:
    1. Parse via cobuilder.pipeline.parser.parse_file()
    2. Extract prd_id from graph_attrs
    3. Run detect_phase() for current phase
    4. Compute status distribution from node statuses
    5. Count pending wait.human reviews
    """
```

**Query Parameters**:

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `phase` | `InitiativePhase` | No | Filter initiatives by phase |

**Response 200**:
```json
[
    {
        "id": "PRD-DASHBOARD-AUDIT-001",
        "label": "Dashboard Audit Trail",
        "dot_path": "/path/to/prd-dashboard-audit-001.dot",
        "phase": "Implementation",
        "status_distribution": {
            "pending": 3,
            "active": 1,
            "impl_complete": 0,
            "validated": 5,
            "failed": 0
        },
        "node_count": 9,
        "pending_reviews": 0,
        "created_at": "2026-03-12T10:00:00Z"
    }
]
```

---

#### GET /api/initiatives/{id}

Get full initiative state including parsed graph.

```python
@router.get(
    "/{initiative_id}",
    response_model=InitiativeDetail,
    responses={404: {"model": ErrorResponse}},
)
async def get_initiative(
    initiative_id: str = Path(
        ...,
        pattern=r"^PRD-[A-Z0-9-]+$",
        description="Initiative PRD ID",
    ),
    manager: InitiativeManager = Depends(get_initiative_manager),
) -> InitiativeDetail:
    """Return full initiative state by parsing the DOT graph.

    Includes all nodes with attributes, all edges, pending reviews,
    and graph-level attributes (target_repo, worktree_path, etc.).
    """
```

**Path Parameters**:

| Param | Type | Pattern | Description |
|-------|------|---------|-------------|
| `initiative_id` | `str` | `^PRD-[A-Z0-9-]+$` | The PRD ID |

**Response 200**: Full `InitiativeDetail` (see model above).

**Response 404**: No DOT file found for this PRD ID.

---

#### GET /api/initiatives/{id}/artifacts

List PRD and SD files referenced in the initiative's DOT graph.

```python
@router.get(
    "/{initiative_id}/artifacts",
    response_model=ArtifactListResponse,
    responses={404: {"model": ErrorResponse}},
)
async def list_artifacts(
    initiative_id: str = Path(..., pattern=r"^PRD-[A-Z0-9-]+$"),
    manager: InitiativeManager = Depends(get_initiative_manager),
    settings: Settings = Depends(get_settings),
) -> ArtifactListResponse:
    """List artifacts (PRDs, SDs) referenced in the DOT graph.

    Scans node attributes for:
    - output_path (from prd-writer and solution-design-architect nodes)
    - sd_path (from implementation codergen nodes)
    - prd_ref (from SD writer nodes)

    For each reference, checks whether the file exists on disk.
    """
```

**Response 200**:
```json
{
    "initiative_id": "PRD-DASHBOARD-AUDIT-001",
    "artifacts": [
        {
            "path": "docs/prds/dashboard-audit-trail/PRD-DASHBOARD-AUDIT-001.md",
            "absolute_path": "/Users/theb/target-repo/docs/prds/.../PRD-DASHBOARD-AUDIT-001.md",
            "artifact_type": "prd",
            "node_id": "write_prd",
            "exists": true
        },
        {
            "path": "docs/sds/dashboard-audit-trail/SD-DASHBOARD-AUDIT-001.md",
            "absolute_path": "/Users/theb/target-repo/docs/sds/.../SD-DASHBOARD-AUDIT-001.md",
            "artifact_type": "sd",
            "node_id": "write_sd_backend",
            "exists": true
        }
    ]
}
```

---

#### GET /api/artifacts/{path:path}

Serve raw markdown file content.

```python
# cobuilder/web/api/routers/artifacts.py

@router.get(
    "/{artifact_path:path}",
    response_model=ArtifactContentResponse,
    responses={
        404: {"model": ErrorResponse, "description": "File not found"},
        403: {"model": ErrorResponse, "description": "Path traversal blocked"},
    },
)
async def get_artifact_content(
    artifact_path: str = Path(
        ...,
        description="Relative path to the artifact from target_repo root",
        examples=["docs/prds/dashboard-audit-trail/PRD-DASHBOARD-AUDIT-001.md"],
    ),
    settings: Settings = Depends(get_settings),
) -> ArtifactContentResponse:
    """Return the raw content of a markdown artifact file.

    Security: resolves the path against target_repo and validates
    that the resolved absolute path starts with the target_repo prefix
    (prevents path traversal via ../ sequences).

    Only serves .md files. Returns 403 for non-markdown or traversal attempts.
    """
```

**Path traversal guard** (critical security logic):

```python
def _resolve_safe_path(target_repo: str, relative_path: str) -> str:
    """Resolve a relative path safely within target_repo.

    Raises:
        PermissionError: If resolved path escapes target_repo.
        ValueError: If file extension is not .md.
    """
    # Normalize to prevent ../ tricks
    resolved = os.path.normpath(os.path.join(target_repo, relative_path))
    repo_prefix = os.path.normpath(target_repo) + os.sep

    if not resolved.startswith(repo_prefix) and resolved != os.path.normpath(target_repo):
        raise PermissionError(f"Path traversal blocked: {relative_path}")

    if not resolved.endswith(".md"):
        raise ValueError(f"Only .md files can be served: {relative_path}")

    return resolved
```

**Response 200**:
```json
{
    "path": "docs/prds/dashboard-audit-trail/PRD-DASHBOARD-AUDIT-001.md",
    "content": "---\ntitle: ...\n---\n\n# PRD-DASHBOARD-AUDIT-001...",
    "size_bytes": 14320,
    "last_modified": "2026-03-12T08:30:00Z"
}
```

**Response 403**: Path traversal attempt or non-markdown file.

**Response 404**: File does not exist.

---

#### POST /api/initiatives/{id}/signal

Write a signal file for a `wait.human` gate.

```python
# cobuilder/web/api/routers/signals.py

@router.post(
    "/{initiative_id}/signal",
    response_model=SignalResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Initiative or node not found"},
        400: {"model": ErrorResponse, "description": "Node is not a wait.human gate or not active"},
        422: {"model": ErrorResponse, "description": "Reject requires reason"},
    },
)
async def write_signal(
    initiative_id: str = Path(..., pattern=r"^PRD-[A-Z0-9-]+$"),
    body: SignalRequest,
    manager: InitiativeManager = Depends(get_initiative_manager),
    settings: Settings = Depends(get_settings),
) -> SignalResponse:
    """Write a signal file that unblocks a wait.human gate.

    Validation steps:
    1. Verify initiative exists (DOT file found)
    2. Verify node_id exists in the graph
    3. Verify node handler is 'wait.human'
    4. Verify node status is 'active' (gate is dispatchable)
    5. If action is 'reject', require non-empty reason

    Signal file is written via signal_protocol.write_signal():
    - source: "web"
    - target: "runner"
    - signal_type: "INPUT_RESPONSE"
    - payload: {node_id, result: "pass"|"requeue", reason?}
    """
```

**Request**: `SignalRequest` (see model above)

**Signal file payload mapping**:

| Web Action | signal_type | payload.result | payload.reason |
|-----------|-------------|----------------|----------------|
| `approve` | `INPUT_RESPONSE` | `"pass"` | -- |
| `reject` | `INPUT_RESPONSE` | `"requeue"` | User-provided reason |

**Response 200**:
```json
{
    "signal_path": "/path/to/.claude/attractor/signals/20260312T120000Z-web-runner-INPUT_RESPONSE.json",
    "node_id": "review_prd",
    "action": "approve",
    "message": "Signal written. Pipeline runner will process the gate."
}
```

---

#### POST /api/initiatives/{id}/extend

Trigger graph extension after a `wait.human` approval.

```python
@router.post(
    "/{initiative_id}/extend",
    response_model=ExtendResponse,
    responses={
        404: {"model": ErrorResponse},
        400: {"model": ErrorResponse, "description": "Gate not approved or extension params missing"},
    },
)
async def extend_graph(
    initiative_id: str = Path(..., pattern=r"^PRD-[A-Z0-9-]+$"),
    body: ExtendRequest,
    manager: InitiativeManager = Depends(get_initiative_manager),
) -> ExtendResponse:
    """Extend the initiative DOT graph after a wait.human approval.

    Delegates to:
    - InitiativeManager.extend_after_prd_review() for review_prd gates
    - InitiativeManager.extend_after_sd_review() for review_sds gates

    The gate_node_id must be in 'validated' status (already approved via signal).
    The caller provides the data needed for extension (epics list or SD paths)
    which was extracted from the approved artifact content by the frontend.
    """
```

**Request**: `ExtendRequest` (see model above)

**Response 200**:
```json
{
    "initiative_id": "PRD-DASHBOARD-AUDIT-001",
    "gate_node_id": "review_prd",
    "nodes_added": 4,
    "edges_added": 5,
    "message": "Graph extended with 3 SD writer nodes and 1 review gate"
}
```

---

### 3.3 Endpoint Summary Table

| Method | Path | Router | Description |
|--------|------|--------|-------------|
| `POST` | `/api/initiatives` | `initiatives` | Create new initiative |
| `GET` | `/api/initiatives` | `initiatives` | List all initiatives |
| `GET` | `/api/initiatives/{id}` | `initiatives` | Get full initiative state |
| `GET` | `/api/initiatives/{id}/artifacts` | `initiatives` | List referenced PRD/SD files |
| `GET` | `/api/artifacts/{path:path}` | `artifacts` | Serve markdown file content |
| `POST` | `/api/initiatives/{id}/signal` | `signals` | Write approve/reject signal |
| `POST` | `/api/initiatives/{id}/extend` | `signals` | Trigger graph extension |

---

## 4. Files Changed

### 4.1 New Files

| File | Purpose | LOC (est.) |
|------|---------|------------|
| `cobuilder/web/__init__.py` | Package marker | 1 |
| `cobuilder/web/api/__init__.py` | Package marker | 1 |
| `cobuilder/web/api/main.py` | FastAPI app factory, CORS, lifespan, router mounting | ~60 |
| `cobuilder/web/api/config.py` | `Settings` class via pydantic-settings | ~40 |
| `cobuilder/web/api/dependencies.py` | `get_settings()`, `get_initiative_manager()` | ~25 |
| `cobuilder/web/api/models.py` | All Pydantic request/response schemas | ~200 |
| `cobuilder/web/api/routers/__init__.py` | Package marker | 1 |
| `cobuilder/web/api/routers/initiatives.py` | Initiative CRUD endpoints (create, list, get, artifacts) | ~180 |
| `cobuilder/web/api/routers/artifacts.py` | Artifact content serving with path traversal guard | ~70 |
| `cobuilder/web/api/routers/signals.py` | Signal writing + graph extension endpoints | ~130 |

**Total new**: 10 files, ~710 LOC estimated.

### 4.2 Modified Files

None. This epic introduces new files only. It depends on E1's `InitiativeManager` which is consumed as an import, not modified.

### 4.3 Integration Points (Unchanged, Consumed)

| Module | Function Used | By Which Router |
|--------|---------------|-----------------|
| `cobuilder.pipeline.parser.parse_file()` | Parse DOT files for initiative state | `initiatives.py` |
| `cobuilder.pipeline.parser.parse_dot()` | Parse DOT content in memory | `initiatives.py` |
| `cobuilder.pipeline.dashboard.determine_pipeline_stage()` | Phase detection | `initiatives.py` |
| `cobuilder.pipeline.dashboard.compute_status_distribution()` | Status counts | `initiatives.py` |
| `cobuilder.pipeline.signal_protocol.write_signal()` | Atomic signal file I/O | `signals.py` |
| `cobuilder.web.api.infra.initiative_manager.InitiativeManager` (E1) | create, detect_phase, get_pending_reviews, extend | `initiatives.py`, `signals.py` |

---

## 5. Implementation Priority

The endpoints should be implemented in this order, each building on the previous:

| Priority | Endpoint | Rationale |
|----------|----------|-----------|
| **P0** | `main.py` + `config.py` + `dependencies.py` | Foundation: app boots, settings load, CORS works |
| **P0** | `models.py` | All request/response types needed by routers |
| **P1** | `GET /api/initiatives` | List view is the first thing the frontend needs |
| **P1** | `GET /api/initiatives/{id}` | Detail view with full graph |
| **P2** | `POST /api/initiatives` | Create flow |
| **P2** | `GET /api/initiatives/{id}/artifacts` | Artifact browsing |
| **P2** | `GET /api/artifacts/{path}` | Inline content display |
| **P3** | `POST /api/initiatives/{id}/signal` | wait.human gate interaction |
| **P3** | `POST /api/initiatives/{id}/extend` | Graph extension trigger |

P0 items are blocking: nothing works without the app and models. P1 items enable read-only frontend development. P2 enables write flows. P3 enables the full review workflow.

---

## 6. Implementation Details

### 6.1 FastAPI App Factory

```python
# cobuilder/web/api/main.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .dependencies import get_settings
from .routers import initiatives, artifacts, signals


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle.

    Startup: validate that pipelines_dir exists.
    Shutdown: no cleanup needed (stateless server).
    """
    settings = get_settings()
    pipelines_dir = settings.resolved_pipelines_dir
    if not os.path.isdir(pipelines_dir):
        os.makedirs(pipelines_dir, exist_ok=True)
    yield


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="CoBuilder Web API",
        version="0.1.0",
        description="REST API for CoBuilder initiative management",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    app.include_router(initiatives.router, prefix="/api/initiatives", tags=["initiatives"])
    app.include_router(artifacts.router, prefix="/api/artifacts", tags=["artifacts"])
    app.include_router(signals.router, prefix="/api/initiatives", tags=["signals"])

    return app


app = create_app()
```

### 6.2 DOT File Discovery

The initiatives list endpoint scans the pipelines directory for `.dot` files. Each file is parsed to extract initiative metadata:

```python
# Inside initiatives.py list endpoint
import os
from cobuilder.pipeline.parser import parse_file
from cobuilder.pipeline.dashboard import determine_pipeline_stage, compute_status_distribution

def _scan_initiatives(pipelines_dir: str) -> list[dict]:
    """Scan pipelines directory for DOT files and parse each."""
    results = []
    if not os.path.isdir(pipelines_dir):
        return results

    for fname in sorted(os.listdir(pipelines_dir)):
        if not fname.endswith(".dot"):
            continue
        dot_path = os.path.join(pipelines_dir, fname)
        try:
            data = parse_file(dot_path)
        except Exception:
            continue  # Skip unparseable DOT files

        prd_id = data["graph_attrs"].get("prd_id", "")
        if not prd_id:
            continue  # Skip DOT files without prd_id attribute

        nodes = data.get("nodes", [])
        phase = determine_pipeline_stage(nodes)
        dist = compute_status_distribution(nodes)

        # Count pending reviews: wait.human nodes with status=active
        pending = sum(
            1 for n in nodes
            if n["attrs"].get("handler") == "wait.human"
            and n["attrs"].get("status") == "active"
        )

        stat = os.stat(dot_path)
        results.append({
            "prd_id": prd_id,
            "label": data["graph_attrs"].get("label", prd_id),
            "dot_path": dot_path,
            "phase": phase,
            "status_distribution": dist,
            "node_count": len(nodes),
            "pending_reviews": pending,
            "created_at": datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc),
        })

    return results
```

### 6.3 Initiative Lookup by ID

All `{id}` endpoints need to find the DOT file for a given PRD ID. The lookup scans all DOT files (same as list) and matches on `prd_id` graph attribute. This is O(n) on the number of DOT files, which is acceptable for the expected scale (<100 initiatives):

```python
def _find_initiative_dot(pipelines_dir: str, initiative_id: str) -> str | None:
    """Find the DOT file path for a given PRD ID. Returns None if not found."""
    for fname in os.listdir(pipelines_dir):
        if not fname.endswith(".dot"):
            continue
        dot_path = os.path.join(pipelines_dir, fname)
        try:
            data = parse_file(dot_path)
        except Exception:
            continue
        if data["graph_attrs"].get("prd_id") == initiative_id:
            return dot_path
    return None
```

### 6.4 Artifact Extraction from DOT Graph

Artifacts are discovered by scanning node attributes for file path references:

```python
_ARTIFACT_ATTRS = {
    "output_path": None,      # Set by prd-writer and sd-writer nodes
    "sd_path": "sd",          # Set by implementation codergen nodes
    "prd_ref": "prd",         # Set by SD writer nodes
}

def _extract_artifacts(
    nodes: list[dict], target_repo: str
) -> list[ArtifactRef]:
    """Extract artifact references from DOT node attributes."""
    artifacts = []
    for node in nodes:
        attrs = node["attrs"]
        node_id = node["id"]

        for attr_key, forced_type in _ARTIFACT_ATTRS.items():
            rel_path = attrs.get(attr_key)
            if not rel_path:
                continue

            abs_path = os.path.normpath(os.path.join(target_repo, rel_path))

            # Infer artifact type from path or attribute
            if forced_type:
                artifact_type = forced_type
            elif "/prds/" in rel_path or rel_path.upper().startswith("PRD"):
                artifact_type = "prd"
            elif "/sds/" in rel_path or rel_path.upper().startswith("SD"):
                artifact_type = "sd"
            else:
                artifact_type = "unknown"

            artifacts.append(ArtifactRef(
                path=rel_path,
                absolute_path=abs_path,
                artifact_type=artifact_type,
                node_id=node_id,
                exists=os.path.isfile(abs_path),
            ))

    return artifacts
```

### 6.5 Signal Writing

The signal endpoint wraps `signal_protocol.write_signal()` with validation:

```python
from cobuilder.pipeline.signal_protocol import write_signal, INPUT_RESPONSE

async def _write_human_signal(
    node_id: str,
    action: SignalAction,
    reason: str | None,
    signals_dir: str,
) -> str:
    """Write a signal file for a wait.human gate resolution.

    Returns the absolute path to the written signal file.
    """
    if action == SignalAction.reject and not reason:
        raise ValueError("Reject action requires a reason")

    payload: dict[str, Any] = {
        "node_id": node_id,
        "result": "pass" if action == SignalAction.approve else "requeue",
    }
    if reason:
        payload["reason"] = reason

    signal_path = write_signal(
        source="web",
        target="runner",
        signal_type=INPUT_RESPONSE,
        payload=payload,
        signals_dir=signals_dir,
    )
    return signal_path
```

The signals directory is resolved from the initiative's DOT graph. The DOT graph's `graph_attrs` may contain a signal directory override, otherwise the default resolution in `signal_protocol._default_signals_dir()` applies.

### 6.6 Concurrent Signal Write Safety

`signal_protocol.write_signal()` already uses an atomic write-then-rename pattern (write to `.tmp`, `os.fsync`, `os.rename`). The timestamp-based filename (`{timestamp}-{source}-{target}-{type}.json`) is unique per millisecond per source. Since the web server is the only source using `source="web"`, and HTTP requests are serialized per-process (single uvicorn worker for localhost), concurrent signal writes are safe without additional locking.

If multiple uvicorn workers are needed in the future, the file-level lock from `node_ops._dot_file_lock()` should be applied to the signals directory. This is not needed for the initial localhost deployment.

---

## 7. Acceptance Criteria

| ID | Criterion | Verification |
|----|-----------|-------------|
| AC-1 | `uvicorn cobuilder.web.api.main:app` starts without error when `COBUILDER_WEB_PROJECT_TARGET_REPO` is set | Manual: start server, observe no crash |
| AC-2 | `POST /api/initiatives` creates a DOT file in the pipelines directory and returns 201 with initiative ID | curl or httpie: `POST` with valid body, verify DOT file on disk |
| AC-3 | `POST /api/initiatives` returns 409 when PRD ID already exists | curl: create twice with same ID |
| AC-4 | `GET /api/initiatives` returns a list of all initiatives with correct phase and status distribution | curl: verify response matches DOT files on disk |
| AC-5 | `GET /api/initiatives/{id}` returns full node/edge graph for an existing initiative | curl: verify nodes/edges match parsed DOT |
| AC-6 | `GET /api/initiatives/{id}` returns 404 for non-existent initiative | curl: GET with bogus ID |
| AC-7 | `GET /api/initiatives/{id}/artifacts` lists all PRD/SD paths referenced in the graph | curl: verify artifact paths match DOT node attributes |
| AC-8 | `GET /api/artifacts/docs/prds/.../PRD-X.md` returns markdown content | curl: verify content matches file on disk |
| AC-9 | `GET /api/artifacts/../../etc/passwd` returns 403 (path traversal blocked) | curl: verify 403 response |
| AC-10 | `GET /api/artifacts/docs/readme.txt` returns 403 (non-.md extension blocked) | curl: verify 403 response |
| AC-11 | `POST /api/initiatives/{id}/signal` with `action=approve` writes a signal file with `result=pass` | curl: verify signal JSON on disk |
| AC-12 | `POST /api/initiatives/{id}/signal` with `action=reject` and no reason returns 422 | curl: verify validation error |
| AC-13 | `POST /api/initiatives/{id}/signal` for a non-`wait.human` node returns 400 | curl: try signaling a codergen node |
| AC-14 | `POST /api/initiatives/{id}/extend` adds new nodes/edges to the DOT graph | curl: extend after approval, verify DOT file has new nodes |
| AC-15 | CORS headers present on responses when `Origin: http://localhost:3000` is sent | curl with `-H "Origin: ..."`: verify `Access-Control-Allow-Origin` header |
| AC-16 | All endpoints return `ErrorResponse` format for 4xx/5xx errors | curl: verify JSON error bodies have `detail` field |

---

## 8. Risks

### R1: Path Traversal in Artifact Serving (Severity: High)

**Risk**: The `GET /api/artifacts/{path:path}` endpoint accepts arbitrary paths. Without validation, a request like `GET /api/artifacts/../../etc/passwd` could serve any file on the system.

**Mitigation**: The `_resolve_safe_path()` function (Section 6.2) uses `os.path.normpath()` to canonicalize the path, then validates that the resolved absolute path starts with the `target_repo` prefix. Additionally, only `.md` files are served. Both checks are mandatory and cannot be bypassed via URL encoding (FastAPI decodes path parameters before passing to the handler).

**Residual risk**: Symlinks inside `target_repo` could point outside it. Mitigation: `os.path.realpath()` should be used instead of `os.path.normpath()` to resolve symlinks. Implementation note: use `os.path.realpath()` in production.

### R2: Concurrent Signal Writes (Severity: Low)

**Risk**: If two browser tabs approve the same `wait.human` gate simultaneously, two signal files are written. The pipeline runner would process both, but only one has effect (the node is already transitioned after the first).

**Mitigation**: The signal endpoint validates that the node is in `active` status before writing. After the first signal is processed by the runner, the node transitions away from `active`, so the second signal write would be rejected at the endpoint level. There is a TOCTOU window between the status check and the signal write, but since the runner is the only consumer and processes signals sequentially, a duplicate signal is harmless (runner ignores signals for non-active nodes).

### R3: DOT File Parsing Errors (Severity: Medium)

**Risk**: Malformed DOT files in the pipelines directory could cause `parse_file()` to raise exceptions, breaking the list endpoint.

**Mitigation**: The `_scan_initiatives()` function wraps `parse_file()` in a try/except and skips unparseable files. Individual initiative GET endpoints return 500 with a descriptive error if the specific DOT file cannot be parsed.

### R4: Large DOT Files (Severity: Low)

**Risk**: An initiative with 100+ nodes produces a large `InitiativeDetail` response.

**Mitigation**: Not a concern for the expected scale. Initiatives typically have 10-30 nodes. If this becomes an issue, add pagination to the nodes/edges arrays in a future iteration.

### R5: Stale Phase Detection (Severity: Low)

**Risk**: The phase detection reads the DOT file at request time. If the pipeline runner transitions a node between the list request and the user viewing the result, the displayed phase may be stale.

**Mitigation**: Acceptable for REST polling. The SSE event bridge (E3) provides real-time updates. The REST endpoints are designed for initial page load, not live tracking.
