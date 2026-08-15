"""Agent-neutral planning, execution, and run-inspection interfaces."""

from __future__ import annotations

import os
from typing import Any

from .agent_contracts import AGENT_SCHEMA_VERSION, AgentInterfaceError, canonical_json as _canonical_json
from .services.agent_inputs import (
    inspect_input,
    load_inspection,
    propose_samples,
    propose_samples_from_inspection,
    write_sample_table,
)
from .services.agent_execution import dry_run_plan, execute_existing_run, execute_plan
from .services.agent_planning import create_plan, load_plan, validate_plan_payload
from .services.post_analysis import init_post_analysis
from .services.run_inspection import (
    _pid_alive,
    _pid_alive_posix,
    _pid_alive_windows,
    artifact_inventory,
    build_agent_context,
    run_status,
)


SCHEMA_VERSION = AGENT_SCHEMA_VERSION


def canonical_json(payload: Any) -> str:
    return _canonical_json(payload)
