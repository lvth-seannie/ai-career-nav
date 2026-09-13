"""Career analysis: skill gap + roadmap + recommendation.

Required skills come from the curated role map (api/data/role_skill_map.py);
the gap and roadmap skeleton are pure Python (api/services/). The
`recommendation` sentence and roadmap `description` strings come from
api/ai/gemini_client.py when GEMINI_API_KEY is set; otherwise (no key,
timeout, malformed response) this falls back to the deterministic templates
in api/services/recommendation.py and api/services/roadmap.py, so the
endpoint never fails because of the AI call.
"""
from ninja import Router
from ninja.errors import HttpError

from api.ai.gemini_client import narrate
from api.data.role_skill_map import known_roles
from api.schemas import AnalyzeIn, AnalyzeOut
from api.services import roadmap
from api.services.recommendation import fallback as fallback_recommendation
from api.services.skill_matching import analyse

router = Router()

# `currentSkills` is user input that will reach an LLM prompt in Phase 3 —
# bound it now. See BACKEND_SPEC §4.2.5.
_MAX_SKILLS = 50
_MAX_SKILL_LEN = 60


def _clean_skills(raw: list[str]) -> list[str]:
    cleaned: list[str] = []
    for item in raw[:_MAX_SKILLS]:
        text = "".join(ch for ch in item if ch.isprintable()).strip()[:_MAX_SKILL_LEN]
        if text:
            cleaned.append(text)
    return cleaned


@router.post("/analyze", response=AnalyzeOut)
def analyze(request, payload: AnalyzeIn):
    target_role = payload.targetRole.strip()
    skills = _clean_skills(payload.currentSkills)

    if not target_role or not skills:
        raise HttpError(422, "targetRole and at least one skill are required.")

    if target_role not in known_roles():
        known = ", ".join(known_roles())
        raise HttpError(400, f"Unknown targetRole '{target_role}'. Known roles: {known}")

    gap = analyse(target_role, skills)
    ai = narrate(target_role, gap)
    recommendation = ai["recommendation"] if ai else fallback_recommendation(target_role, gap)
    descriptions = ai["descriptions"] if ai else None
    return {
        "matchScore": gap.match_score,
        "strengths": gap.strengths,
        "missingSkills": gap.missing,
        "roadmap": roadmap.build(gap.missing, descriptions),
        "recommendation": recommendation,
    }
