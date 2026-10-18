import hashlib
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app.schemas.post import PostInput
from scripts import evaluate_heldout as evaluator
from scripts import seed_heldout as seeder


def summary():
    return {
        "total": 12,
        "passed": 9,
        "matchable_cases": 8,
        "correct_top_matches": 6,
        "no_match_cases": 4,
        "correct_rejections": 3,
        "accepted_predictions": 7,
        "incorrect_acceptances": 1,
        "false_rejections": 2,
        "accepted_top_precision": 6 / 7,
        "rows": [],
    }


def test_metric_rates_use_separate_denominators():
    result = evaluator.add_rates(summary())

    assert result["top1_match_rate"] == pytest.approx(6 / 8)
    assert result["coverage"] == pytest.approx(7 / 12)
    assert result["correct_no_match_rejection_rate"] == (
        pytest.approx(3 / 4)
    )
    assert result["accepted_top_precision"] == pytest.approx(
        6 / 7
    )


def test_empty_denominators_produce_unknown_rates():
    group = summary()
    for key in (
        "total",
        "matchable_cases",
        "correct_top_matches",
        "no_match_cases",
        "correct_rejections",
        "accepted_predictions",
    ):
        group[key] = 0

    result = evaluator.add_rates(group)

    assert result["top1_match_rate"] is None
    assert result["coverage"] is None
    assert result["correct_no_match_rejection_rate"] is None


def test_unchanged_baseline_is_accepted(monkeypatch):
    run = Mock(side_effect=[
        SimpleNamespace(returncode=0),
        SimpleNamespace(returncode=0, stdout=""),
    ])
    monkeypatch.setattr(evaluator.subprocess, "run", run)

    evaluator.verify_baseline_code({
        "code_commit": "a" * 40,
    })

    assert run.call_count == 2


@pytest.mark.parametrize(
    "diff_code,untracked",
    [
        (1, ""),
        (0, "backend/app/untracked.py\n"),
    ],
)
def test_changed_or_untracked_implementation_is_rejected(
    monkeypatch, diff_code, untracked
):
    run = Mock(side_effect=[
        SimpleNamespace(returncode=diff_code),
        SimpleNamespace(returncode=0, stdout=untracked),
    ])
    monkeypatch.setattr(evaluator.subprocess, "run", run)

    with pytest.raises(ValueError):
        evaluator.verify_baseline_code({
            "code_commit": "a" * 40,
        })


def test_invalid_baseline_commit_is_rejected(monkeypatch):
    run = Mock()
    monkeypatch.setattr(evaluator.subprocess, "run", run)

    with pytest.raises(ValueError, match="Invalid baseline"):
        evaluator.verify_baseline_code({
            "code_commit": "not-a-commit",
        })

    run.assert_not_called()


def test_stored_post_drift_is_rejected(monkeypatch):
    expected = PostInput(
        id="eval_001",
        title="Foxes",
        content="Original frozen text.",
        required_subject="red fox",
    )

    session = MagicMock()
    session.get.return_value = SimpleNamespace(
        id=expected.id,
        title=expected.title,
        content="Changed database text.",
        required_subject=expected.required_subject,
    )
    factory = MagicMock()
    factory.return_value.__enter__.return_value = session
    monkeypatch.setattr(evaluator, "SessionLocal", factory)

    with pytest.raises(ValueError, match="differs from frozen"):
        evaluator.verify_stored_posts([expected])


def test_existing_first_report_is_preserved(
    monkeypatch, tmp_path
):
    output = tmp_path / "data" / "processed"
    output.mkdir(parents=True)
    report = output / "heldout_evaluation.json"
    report.write_text('{"original": true}', encoding="utf-8")

    load = Mock()
    monkeypatch.setattr(evaluator, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(evaluator, "load_frozen_cases", load)

    with pytest.raises(FileExistsError):
        evaluator.main()

    assert report.read_text(encoding="utf-8") == (
        '{"original": true}'
    )
    load.assert_not_called()


def test_report_records_baseline_inputs_and_rates(
    monkeypatch, tmp_path
):
    baseline = {
        "code_commit": "a" * 40,
        "min_match_similarity": 0.85,
    }
    cases = [{
        "id": "eval_001",
        "acceptable_image_ids": ["img_test"],
    }]
    snapshots = [{
        "source_type": "image",
        "source_id": "img_test",
        "input_hash": "b" * 64,
    }]
    group = {
        **summary(),
        "total": 1,
        "passed": 1,
        "matchable_cases": 1,
        "correct_top_matches": 1,
        "no_match_cases": 0,
        "correct_rejections": 0,
        "accepted_predictions": 1,
        "incorrect_acceptances": 0,
        "false_rejections": 0,
        "accepted_top_precision": 1.0,
    }

    monkeypatch.setattr(evaluator, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        evaluator,
        "load_frozen_cases",
        Mock(return_value=(cases, baseline, [])),
    )
    verify = Mock()
    monkeypatch.setattr(
        evaluator, "verify_baseline_code", verify
    )
    monkeypatch.setattr(
        evaluator,
        "verify_stored_posts",
        Mock(return_value=snapshots),
    )
    rank = Mock(return_value=group)
    monkeypatch.setattr(evaluator, "evaluate_group", rank)

    evaluator.main()

    output = (
        tmp_path / "data" / "processed"
        / "heldout_evaluation.json"
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert report["baseline"] == baseline
    assert report["source_snapshots"] == snapshots
    assert len(report["source_snapshot_sha256"]) == 64
    assert report["evaluation"]["top1_match_rate"] == 1.0
    assert report["evaluation"]["coverage"] == 1.0
    assert report["evaluation"][
        "correct_no_match_rejection_rate"
    ] is None

    verify.assert_called_once_with(baseline)
    rank.assert_called_once_with(
        [{
            "post_id": "eval_001",
            "acceptable_image_ids": ["img_test"],
        }],
        tenant_id="demo",
    )


@pytest.fixture
def frozen_files(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "docs").mkdir()

    raw = b"[]"
    (tmp_path / "data" / "heldout.json").write_bytes(raw)

    baseline = {
        "label_file": "data/heldout.json",
        "label_sha256": hashlib.sha256(raw).hexdigest(),
        "embedding_model": "test-model",
        "dimensions": 768,
        "min_match_similarity": 0.85,
        "task_type": "SEMANTIC_SIMILARITY",
    }

    (tmp_path / "docs" / "heldout-baseline.json").write_text(
        json.dumps(baseline),
        encoding="utf-8",
    )
    monkeypatch.setattr(seeder, "PROJECT_ROOT", tmp_path)
    return tmp_path


def test_changed_label_file_is_rejected(frozen_files):
    (frozen_files / "data" / "heldout.json").write_text(
        '[{"changed": true}]',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="frozen baseline"):
        seeder.load_frozen_cases()


def test_changed_settings_are_rejected(
    frozen_files, monkeypatch
):
    monkeypatch.setattr(
        seeder,
        "get_settings",
        lambda: SimpleNamespace(
            embedding_model="different-model",
            embedding_dimensions=768,
            min_match_similarity=0.85,
        ),
    )

    with pytest.raises(ValueError, match="settings differ"):
        seeder.load_frozen_cases()