"""Tests — response-shape contracts + skill-matching unit tests.

See docs/BACKEND_SPEC.md §3 / §4.3. Run with:  python manage.py test api

The test DB has no `jobs` / `job_skill` tables, so market-insights exercises
the stub fallback path here.
"""
from unittest.mock import MagicMock, patch

import httpx
from django.test import SimpleTestCase, TestCase

from api.ai import gemini_client
from api.data.role_skill_map import classify_title
from api.repositories import jobs_repo
from api.services import market_insights
from api.services.roadmap import build as build_roadmap
from api.services.skill_matching import diff
from api.services.skill_matching import SkillGap
from api.services.skills import display, normalize


class HealthTests(TestCase):
    def test_health_ok(self):
        r = self.client.get("/api/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"status": "ok"})


class MarketInsightsTests(TestCase):
    def test_shape(self):
        r = self.client.get("/api/market-insights")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(
            set(body),
            {"updatedAt", "topSkills", "topRoles", "topLocations", "trends"},
        )
        self.assertEqual(set(body["topSkills"][0]), {"name", "percentage"})
        for stat in body["trends"]:
            self.assertEqual(set(stat), {"label", "percentage", "caption"})


class RolesTests(TestCase):
    def test_shape(self):
        r = self.client.get("/api/roles")
        self.assertEqual(r.status_code, 200)
        role = r.json()["roles"][0]
        self.assertEqual(set(role), {"id", "label", "requiredSkills"})


class AnalyzeTests(TestCase):
    def _post(self, **body):
        return self.client.post(
            "/api/analyze", data=body, content_type="application/json"
        )

    def test_gap_and_score(self):
        r = self._post(targetRole="Data Engineer", currentSkills=["SQL", "Docker"])
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(
            set(body),
            {"matchScore", "strengths", "missingSkills", "roadmap", "recommendation"},
        )
        self.assertEqual(sorted(body["strengths"]), ["Docker", "SQL"])
        self.assertIn("Python", body["missingSkills"])
        self.assertEqual(body["matchScore"], 33)
        self.assertEqual(set(body["roadmap"][0]), {"phase", "skill", "description"})

    def test_skill_matching_is_case_insensitive(self):
        r = self._post(targetRole="Data Engineer", currentSkills=["sql", "PYTHON"])
        self.assertEqual(sorted(r.json()["strengths"]), ["Python", "SQL"])

    def test_unknown_role_is_400(self):
        self.assertEqual(self._post(targetRole="Wizard", currentSkills=["SQL"]).status_code, 400)

    def test_empty_skills_is_422(self):
        self.assertEqual(self._post(targetRole="Data Engineer", currentSkills=[]).status_code, 422)

    def test_aliased_skill_counts_as_a_match(self):
        # "postgres" -> sql, "py" -> python, "reactjs" -> react
        r = self._post(targetRole="Software Engineer", currentSkills=["postgres", "reactjs"])
        strengths = r.json()["strengths"]
        self.assertIn("SQL", strengths)
        self.assertIn("React", strengths)


class NormalizeTests(SimpleTestCase):
    def test_aliases_and_whitespace(self):
        self.assertEqual(normalize("  JavaScript "), "javascript")
        self.assertEqual(normalize("JS"), "javascript")
        self.assertEqual(normalize("PostgreSQL"), "sql")
        self.assertEqual(normalize("node js"), "node.js")
        self.assertEqual(normalize("React.js"), "react")

    def test_display_round_trips_known_and_unknown(self):
        self.assertEqual(display(normalize("js")), "JavaScript")
        self.assertEqual(display(normalize("aws")), "AWS")
        self.assertEqual(display(normalize("kafka")), "Kafka")


class SkillDiffTests(SimpleTestCase):
    def test_diff_is_case_and_alias_insensitive_and_scored(self):
        gap = diff(["Python", "SQL", "Spark"], ["python", "postgres"])
        self.assertEqual(gap.strengths, ["Python", "SQL"])
        self.assertEqual(gap.missing, ["Spark"])
        self.assertEqual(gap.match_score, 67)

    def test_empty_required_scores_zero(self):
        self.assertEqual(diff([], ["Python"]).match_score, 0)


class RoadmapTests(SimpleTestCase):
    def test_one_ordered_step_per_missing_skill(self):
        steps = build_roadmap(["Python", "Spark", "Airflow"])
        self.assertEqual([s["phase"] for s in steps], ["Phase 1", "Phase 2", "Phase 3"])
        self.assertEqual([s["skill"] for s in steps], ["Python", "Spark", "Airflow"])
        self.assertTrue(all(s["description"] for s in steps))

    def test_ai_description_used_when_present_templated_otherwise(self):
        steps = build_roadmap(["Python", "Spark"], descriptions={"python": "Learn Python via X."})
        self.assertEqual(steps[0]["description"], "Learn Python via X.")
        self.assertIn("Spark", steps[1]["description"])


class GeminiClientTests(SimpleTestCase):
    def setUp(self):
        gemini_client.clear_cache()
        self.addCleanup(gemini_client.clear_cache)
        self.gap = SkillGap(
            required=["Python", "Spark"], strengths=["Python"], missing=["Spark"], match_score=50,
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_no_api_key_returns_none(self):
        self.assertIsNone(gemini_client.narrate("Data Engineer", self.gap))

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake"})
    @patch("api.ai.gemini_client.httpx.post", side_effect=gemini_client.httpx.TimeoutException("boom"))
    def test_transport_error_returns_none(self, _mock_post):
        self.assertIsNone(gemini_client.narrate("Data Engineer", self.gap))

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake"})
    @patch("api.ai.gemini_client.httpx.post")
    def test_parses_response_and_caches(self, mock_post):
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": (
                    '{"recommendation": "Go learn Spark.", '
                    '"roadmap": [{"skill": "Spark", "description": "Do a Spark project."}]}'
                )}]},
            }],
        }

        result = gemini_client.narrate("Data Engineer", self.gap)
        self.assertEqual(result["recommendation"], "Go learn Spark.")
        self.assertEqual(result["descriptions"]["spark"], "Do a Spark project.")

        gemini_client.narrate("Data Engineer", self.gap)
        mock_post.assert_called_once()  # second call served from cache

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake"})
    @patch("api.ai.gemini_client.httpx.post")
    def test_malformed_response_returns_none(self, mock_post):
        mock_post.return_value.raise_for_status.return_value = None
        mock_post.return_value.json.return_value = {"candidates": []}
        self.assertIsNone(gemini_client.narrate("Data Engineer", self.gap))

    def _overloaded_response(self, status_code):
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom", request=MagicMock(), response=MagicMock(status_code=status_code)
        )
        return resp

    def _ok_response(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "candidates": [{
                "content": {"parts": [{"text": (
                    '{"recommendation": "Retried ok.", '
                    '"roadmap": [{"skill": "Spark", "description": "Do it."}]}'
                )}]},
            }],
        }
        return resp

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake"})
    @patch("api.ai.gemini_client.time.sleep")
    @patch("api.ai.gemini_client.httpx.post")
    def test_retries_on_503_then_succeeds(self, mock_post, mock_sleep):
        mock_post.side_effect = [self._overloaded_response(503), self._ok_response()]

        result = gemini_client.narrate("Data Engineer", self.gap)

        self.assertEqual(result["recommendation"], "Retried ok.")
        self.assertEqual(mock_post.call_count, 2)
        mock_sleep.assert_called_once()

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake"})
    @patch("api.ai.gemini_client.time.sleep")
    @patch("api.ai.gemini_client.httpx.post")
    def test_exhausts_retries_then_falls_back(self, mock_post, mock_sleep):
        mock_post.return_value = self._overloaded_response(503)

        self.assertIsNone(gemini_client.narrate("Data Engineer", self.gap))
        self.assertEqual(mock_post.call_count, 3)  # initial attempt + 2 retries
        self.assertEqual(mock_sleep.call_count, 2)

    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake"})
    @patch("api.ai.gemini_client.time.sleep")
    @patch("api.ai.gemini_client.httpx.post")
    def test_non_retryable_status_fails_immediately(self, mock_post, mock_sleep):
        mock_post.return_value = self._overloaded_response(400)

        self.assertIsNone(gemini_client.narrate("Data Engineer", self.gap))
        self.assertEqual(mock_post.call_count, 1)
        mock_sleep.assert_not_called()


class AnalyzeWithAiTests(TestCase):
    @patch.dict("os.environ", {"GEMINI_API_KEY": "fake"})
    @patch("api.routers.analysis.narrate")
    def test_uses_ai_narration_when_available(self, mock_narrate):
        mock_narrate.return_value = {
            "recommendation": "AI says: focus on Spark.",
            "descriptions": {"spark": "AI: build a Spark ETL job."},
        }
        r = self.client.post(
            "/api/analyze",
            data={"targetRole": "Data Engineer", "currentSkills": ["Python", "SQL", "Docker"]},
            content_type="application/json",
        )
        body = r.json()
        self.assertEqual(body["recommendation"], "AI says: focus on Spark.")
        spark_step = next(s for s in body["roadmap"] if s["skill"] == "Spark")
        self.assertEqual(spark_step["description"], "AI: build a Spark ETL job.")

    @patch("api.routers.analysis.narrate", return_value=None)
    def test_falls_back_to_templates_when_ai_unavailable(self, _mock_narrate):
        r = self.client.post(
            "/api/analyze",
            data={"targetRole": "Data Engineer", "currentSkills": ["SQL", "Docker"]},
            content_type="application/json",
        )
        self.assertIn("Focus next on", r.json()["recommendation"])


class MarketSnapshotTests(SimpleTestCase):
    """`trends` is computed from the single snapshot: level mix, remote share,
    AI/ML and cloud skill mentions."""

    def setUp(self):
        self._orig = {
            name: getattr(jobs_repo, name)
            for name in ("total_jobs", "skill_counts", "title_counts",
                         "location_counts", "level_counts", "type_counts",
                         "job_skill_pairs")
        }
        market_insights.clear_cache()
        self.addCleanup(self._restore)

    def _restore(self):
        for name, fn in self._orig.items():
            setattr(jobs_repo, name, fn)
        market_insights.clear_cache()

    def test_snapshot_from_fake_dataset(self):
        jobs_repo.total_jobs = lambda: 100
        jobs_repo.skill_counts = lambda: [("Python", 40), ("AWS", 30)]
        jobs_repo.title_counts = lambda: [("Senior Data Engineer", 60), ("Data Analyst", 40)]
        jobs_repo.location_counts = lambda: [("Berlin, Germany", 100)]
        jobs_repo.level_counts = lambda: [("mid senior", 70), ("associate", 25), ("intern", 5)]
        jobs_repo.type_counts = lambda: [("onsite", 82), ("hybrid", 12), ("remote", 6)]
        jobs_repo.job_skill_pairs = lambda: (
            [(i, "pytorch") for i in range(23)]
            + [(i, "aws") for i in range(29)]
        )

        stats = {s["label"]: s["percentage"] for s in market_insights.get_insights(force=True)["trends"]}
        self.assertEqual(stats["Remote or hybrid roles"], 18)  # hybrid + remote
        self.assertEqual(stats["Mid Senior roles"], 70)
        self.assertEqual(stats["Associate roles"], 25)
        self.assertEqual(stats["Roles requiring AI / ML skills"], 23)
        self.assertEqual(stats["Roles requiring cloud skills"], 29)

    def test_falls_back_to_stub_when_empty(self):
        jobs_repo.total_jobs = lambda: 0
        body = market_insights.get_insights(force=True)
        self.assertTrue(body["trends"])
        self.assertEqual(set(body["trends"][0]), {"label", "percentage", "caption"})


class TitleClassifyTests(SimpleTestCase):
    def test_free_text_titles_bucket_into_ui_roles(self):
        self.assertEqual(classify_title("Senior Data Engineer (m/f/d)"), "Data Engineer")
        self.assertEqual(classify_title("Working Student - Data Analytics"), "Data Analyst")
        self.assertEqual(classify_title("Full Stack Developer"), "Software Engineer")
        self.assertEqual(classify_title("Technical Product Owner"), "Product Manager")
        self.assertIsNone(classify_title("Warehouse Operative"))
