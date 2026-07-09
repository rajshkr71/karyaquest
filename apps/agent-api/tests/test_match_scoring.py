from uuid import UUID

import pytest

from agent_api.job_scores import (
    MatchScoreCreate,
    calculate_match_score,
    recommendation_for,
    score_job,
)

JOB_ID = UUID("e56ee8f6-9e6d-4d12-b826-bf69f4d545bf")
RESUME_ID = UUID("419f8064-dce7-4e2e-8062-0d93c56026fd")


def test_required_matches_are_weighted_higher_than_preferred_matches() -> None:
    required_score, _, _ = calculate_match_score(["Python"], [], "Python")
    preferred_score, _, _ = calculate_match_score([], ["Python"], "Python")

    assert required_score == 70
    assert preferred_score == 30


def test_match_score_tracks_strengths_and_gaps_without_partial_matches() -> None:
    score, strengths, gaps = calculate_match_score(
        ["Python", "Go"],
        ["Kubernetes", "PostgreSQL"],
        "Built Python APIs with PostgreSQL and Django.",
    )

    assert score == 50
    assert strengths == ["Python", "PostgreSQL"]
    assert gaps == ["Go", "Kubernetes"]


@pytest.mark.parametrize(
    ("score", "recommendation"),
    [
        (100, "prepare_application"),
        (80, "prepare_application"),
        (79, "review_required"),
        (60, "review_required"),
        (59, "reject"),
        (0, "reject"),
    ],
)
def test_recommendation_thresholds(score: int, recommendation: str) -> None:
    assert recommendation_for(score) == recommendation


def test_score_job_stores_deterministic_result(monkeypatch) -> None:
    stored = []
    monkeypatch.setattr(
        "agent_api.job_scores.get_job",
        lambda settings, job_id: {
            "required_skills": ["Python", "Go"],
            "preferred_skills": ["PostgreSQL"],
        },
    )
    monkeypatch.setattr(
        "agent_api.job_scores.get_resume",
        lambda settings, resume_id: {
            "content": "Python and PostgreSQL",
        },
    )
    monkeypatch.setattr(
        "agent_api.job_scores.create_job_score",
        lambda settings, values: stored.append(values) or values,
    )

    result = score_job(JOB_ID, MatchScoreCreate(resume_id=RESUME_ID), object())

    assert result == stored[0]
    assert stored == [
        {
            "job_id": JOB_ID,
            "resume_id": RESUME_ID,
            "score": 65,
            "strengths": ["Python", "PostgreSQL"],
            "gaps": ["Go"],
            "recommendation": "review_required",
            "model_used": None,
        }
    ]
