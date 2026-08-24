"""Security subagent runtime: builds the deepagents SubAgent dict."""

from functools import partial

from infrastructure.agents_runtime.subagents.factory import build_subagent_spec

build_security_spec = partial(build_subagent_spec, "security")
