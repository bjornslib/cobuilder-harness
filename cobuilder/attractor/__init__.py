"""cobuilder.attractor — DOT-based pipeline orchestration package.

Key sub-modules
---------------
parser          : DOT file lexer/parser
transition      : State-transition table and apply_transition()
checkpoint      : Atomic checkpoint read/write
signal_protocol : Signal read/write/wait helpers
runner_models   : Pydantic models (PipelineConfig, RunnerState, etc.)
session_runner  : RunnerStateMachine (was runner.py)
pipeline_runner : PipelineRunner top-level orchestrator
guardian        : Guardian agent entry-point
guardian_hooks  : RunnerGuardian / PipelineHealth (was runner_guardian.py)
runner_hooks    : RunnerHooks / anti-gaming enforcement
runner_tools    : Low-level tool dispatch helpers
dispatch_worker : Worker dispatch + load_attractor_env()
spawn_orchestrator: Orchestrator spawn/respawn helpers
cli             : Typer-based CLI entry-point
"""
