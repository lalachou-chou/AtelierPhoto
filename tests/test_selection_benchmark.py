"""Verify evaluation isolation and ranking invariants, without external models."""
import numpy as np
import pytest
from PIL import Image
from scripts.compare_selection_models import (
    chronological_folds, split_fold, dataset, pair_data,
    rerank_within_scenes, variant_results,
)


def test_scene_isolation_and_boundary_purge():
    labels = np.repeat(np.arange(30), [2, 3, 5]*10)
    folds = chronological_folds(labels)
    for label in np.unique(labels):
        assert len(set(folds[labels == label])) == 1
    for fold in range(5):
        train, test = split_fold(labels, folds, fold)
        assert not (train & test).any()
        assert not set(labels[train]) & set(labels[test])
        assert not set(labels[train]) & {labels[test].min()-1, labels[test].max()+1}


def test_pair_training_uses_only_within_scene_comparisons():
    x = np.array([[1., 5], [4., 7], [100., 20], [104., 28]])
    px, py = pair_data(x, np.array([True, False, False, True]), np.array([0, 0, 1, 1]), np.random.default_rng(0))
    np.testing.assert_array_equal(px[py == 1], [[-3, -2], [4, 8]])
    np.testing.assert_array_equal(px[py == 0], -px[py == 1])


def test_reranking_preserves_scene_importance():
    labels = np.array([0, 0, 1, 1])
    scores = np.array([10., 9., 2., -1.])
    reranked = rerank_within_scenes(scores, np.array([-2., 3., -2., 3.]), labels)
    np.testing.assert_array_equal(reranked, [9., 10., -1., 2.])
    for label in [0, 1]:
        np.testing.assert_array_equal(np.sort(scores[labels == label]), np.sort(reranked[labels == label]))


def test_truth_counts_original_once_for_colour_and_bw(tmp_path):
    rush, kept = tmp_path/'rush', tmp_path/'kept'
    rush.mkdir(); kept.mkdir()
    for folder, names in [(rush, ['DSC0001.jpg','DSC0002.jpg']), (kept, ['DSC0001.jpg','DSC0001NB.jpg','unmatched.jpg'])]:
        for name in names:
            Image.new('RGB', (10, 10)).save(folder/name)
    paths, truth, unmatched, pairs = dataset(rush, kept)
    assert len(paths) == 2 and truth == {0} and len(pairs) == 2 and len(unmatched) == 1


def test_variant_metric_excludes_uninformative_scenes():
    truth = np.array([True, False, True, True, False, False])
    rows = variant_results(np.array([2., 1., 5., 4., 7., 6.]), truth, np.array([0, 0, 1, 1, 2, 2]))
    assert len(rows) == 1 and rows[0]['top1'] and rows[0]['pair_accuracy'] == 1.


def test_benchmark_classifier_matches_application_objective():
    sklearn = pytest.importorskip('sklearn.linear_model')
    scaling = pytest.importorskip('sklearn.preprocessing')
    from atelier.selection import fit_logistic, score
    rng = np.random.default_rng(5)
    x = rng.normal(size=(120, 8))
    y = x[:,0] + x[:,1]*.4 > .2
    model = fit_logistic(x,y)
    scaler = scaling.StandardScaler().fit(x)
    fitted = sklearn.LogisticRegression(C=.02,solver='lbfgs',max_iter=500,tol=1e-9).fit(scaler.transform(x),y)
    np.testing.assert_allclose(score(model,x),fitted.decision_function(scaler.transform(x)),atol=1e-5)
