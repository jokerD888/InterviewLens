from pathlib import Path

import pytest


def test_profile_eval_counts_errors_instead_of_using_predictions_as_labels(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'scripts'))
    from evaluate_profiles import compare
    labels=[dict(post_id=1,category='后端',specializations=[],domains=[],skills=['Java']),
            dict(post_id=2,category='前端',specializations=[],domains=[],skills=['TypeScript'])]
    profiles={(1,0):dict(category='后端',skills=['Java']),
              (2,0):dict(category='后端',skills=['Java'])}
    result=compare(labels,profiles)
    assert result['labelled_profiles']==2 and result['category_accuracy']==.5
    assert result['facets']['skills']['micro_f1']==.5


def test_profile_eval_does_not_silently_drop_missing_annotations(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'scripts'))
    from evaluate_profiles import compare
    with pytest.raises(ValueError,match='missing'):
        compare([dict(post_id=1,category=None,specializations=[],domains=[],skills=[])],{})
