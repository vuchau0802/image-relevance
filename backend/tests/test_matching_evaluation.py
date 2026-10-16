import pytest

from scripts.evaluate_matching import evaluate_group


def ranking_result(status, image_id=None):
    return {
        "status": status,
        "reason": "Test decision",
        "results": (
            [{"image_id": image_id, "similarity": 0.9}]
            if image_id is not None else []
        ),
    }


def test_report_counts_rejections_and_wrong_acceptances():
    cases = [
        {"post_id": "good", "acceptable_image_ids": ["img_a"]},
        {"post_id": "wrong", "acceptable_image_ids": ["img_b"]},
        {"post_id": "rejected", "acceptable_image_ids": ["img_c"]},
        {"post_id": "absent", "acceptable_image_ids": []},
        {"post_id": "false_accept", "acceptable_image_ids": []},
    ]
    responses = {
        "good": ranking_result("matched", "img_a"),
        "wrong": ranking_result("matched", "img_other"),
        "rejected": ranking_result("no_confident_match"),
        "absent": ranking_result("no_confident_match"),
        "false_accept": ranking_result("matched", "img_a"),
    }

    def ranker(*, tenant_id, post_id, top):
        assert tenant_id == "test"
        assert top == 1
        return responses[post_id]

    report = evaluate_group(cases, "test", ranker)
    assert report["total"] == 5
    assert report["passed"] == 2
    assert report["correct_top_matches"] == 1
    assert report["correct_rejections"] == 1
    assert report["incorrect_acceptances"] == 2
    assert report["false_rejections"] == 1
    assert report["accepted_top_precision"] == pytest.approx(1 / 3)


def test_precision_is_unknown_when_nothing_is_accepted():
    report = evaluate_group(
        [{"post_id": "p", "acceptable_image_ids": []}],
        "test",
        lambda **kwargs: ranking_result("no_confident_match"),
    )
    assert report["passed"] == 1
    assert report["accepted_top_precision"] is None


@pytest.mark.parametrize("status", ["incomplete", "unsupported_subject"])
def test_unfinished_or_unsupported_ranking_is_not_a_valid_rejection(status):
    with pytest.raises(ValueError, match="Cannot evaluate"):
        evaluate_group(
            [{"post_id": "p", "acceptable_image_ids": []}],
            "test",
            lambda **kwargs: ranking_result(status),
        )


def test_inconsistent_matched_result_is_rejected():
    with pytest.raises(ValueError, match="Inconsistent"):
        evaluate_group(
            [{"post_id": "p", "acceptable_image_ids": []}],
            "test",
            lambda **kwargs: ranking_result("matched"),
        )
