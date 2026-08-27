"""Runtime monkey-patch for mcp-atlassian to support per-user Jira URL override.

Root cause: mcp_atlassian/servers/dependencies.py:697 always uses
base_config.url (the global JIRA_URL env var) when creating user-specific
JiraFetcher configs, ignoring the X-Atlassian-Jira-Url header.

Fix: Override _create_user_config_for_fetcher to check credentials.get("url")
first, falling back to base_config.url. This is applied once at process
startup — no third-party files are modified on disk.
"""

import dataclasses
import logging

logger = logging.getLogger(__name__)

_patched = False


def apply_patches() -> None:
    """Apply the Jira URL override patch to mcp-atlassian.

    Safe to call multiple times — only applies once.
    """
    global _patched
    if _patched:
        return

    try:
        import mcp_atlassian.servers.dependencies as deps
    except ImportError:
        logger.warning("mcp_atlassian not installed — Jira URL patch skipped")
        return

    original_fn = deps._create_user_config_for_fetcher

    def _patched_create_user_config(base_config, auth_type, credentials, cloud_id=None):
        """Use URL from credentials if present, otherwise fall back to base_config.url."""
        url_override = credentials.get("url")
        if url_override:
            logger.debug(
                "Jira URL override: using %s instead of %s",
                url_override,
                base_config.url,
            )
            base_config = dataclasses.replace(base_config, url=url_override)
        return original_fn(base_config, auth_type, credentials, cloud_id)

    deps._create_user_config_for_fetcher = _patched_create_user_config
    _patched = True
    logger.info("Applied mcp-atlassian Jira URL override patch")
