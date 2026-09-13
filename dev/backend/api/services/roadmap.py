"""Turn the missing-skill list into an ordered learning roadmap.

Templated descriptions are the deterministic fallback. When
api/ai/gemini_client.py successfully narrates the gap, its per-skill
descriptions (keyed by lowercased skill name) take priority; any skill it
didn't cover still gets a templated description here, so the roadmap never
has a blank entry (BACKEND_SPEC §4.2.2/3).
"""
from __future__ import annotations

_PHASE_HINT = {
    0: "Start here — it unlocks most of the rest of the stack.",
    1: "Build on the fundamentals with a small end-to-end project.",
}
_LATER_HINT = "Deepen it with a portfolio-quality project once the basics are solid."


def build(missing_skills: list[str], descriptions: dict[str, str] | None = None) -> list[dict]:
    descriptions = descriptions or {}
    steps: list[dict] = []
    for i, skill in enumerate(missing_skills):
        hint = _PHASE_HINT.get(i, _LATER_HINT)
        description = descriptions.get(skill.strip().lower()) or (
            f"Build working proficiency in {skill} through a focused "
            f"project or course. {hint}"
        )
        steps.append({"phase": f"Phase {i + 1}", "skill": skill, "description": description})
    return steps
