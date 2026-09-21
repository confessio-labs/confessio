"""Dependencies passed to every copilot agent run.

Kept out of agent.py so skills.py can build capabilities against it without importing the agent
(which would be circular) and without pulling Django in.
"""
from dataclasses import dataclass


@dataclass
class CopilotDeps:
    discussion_uuid: str
