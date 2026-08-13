"""Shared base prompts & personas."""

from shared.prompts.profiles import PROFILE_VERSION, PROMPT_PROFILES, build_prompt

__all__ = [
    "build_prompt",
    "PROFILE_VERSION",
    "PROMPT_PROFILES",
]
