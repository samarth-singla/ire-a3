"""Unit tests for tie-aware recall@10 (annbench.metrics). Tiny hand-made data only, no datasets.

Layout used by most tests: 2-D points on the x-axis at x = 0, 1, ..., 19 (id = x) and one
query at the origin, so the squared distance of id i is i*i. The 10 exact neighbours are
ids 0..9 and d10 = 81. All coordinates are small integers, so every distance is exact.
"""
import numpy as np
import pytest

from annbench.metrics import recall_at_k, recall_per_query, true_sq_dist

K = 10


def line_points(xs):
    """Base vectors (x, 0) for each x in xs; id = position in xs."""
    return np.array([[x, 0.0] for x in xs], dtype=np.float32)


def exact_gt_dist(xq, xb, k=K):
    """Brute-force sorted squared distances (top k) for the tests."""
    d = ((xb[None, :, :].astype(np.float64) - xq[:, None, :]) ** 2).sum(-1)
    return np.sort(d, axis=1)[:, :k]


XB = line_points(range(20))
XQ = np.zeros((1, 2), dtype=np.float32)
GT = exact_gt_dist(XQ, XB)                       # [[0, 1, 4, ..., 81]]


def test_perfect_retrieval_is_one():
    assert recall_at_k(XQ, XB, np.array([list(range(10))]), GT) == 1.0


def test_completely_wrong_retrieval_is_zero():
    assert recall_at_k(XQ, XB, np.array([list(range(10, 20))]), GT) == 0.0


def test_tie_at_10th_neighbour_counts_as_correct():
    # id 20 sits at x = -9, exactly as far as id 9 (squared distance 81 = d10).
    xb = line_points(list(range(20)) + [-9])
    gt = exact_gt_dist(XQ, xb)
    assert gt[0, K - 1] == 81.0
    # return the "other" tied point instead of id 9
    other = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 20]])
    assert recall_at_k(XQ, xb, other, gt) == 1.0
    assert recall_at_k(XQ, xb, np.array([list(range(10))]), gt) == 1.0


def test_point_just_beyond_tolerance_is_wrong():
    # id 20 at x = 9.001: squared distance 81.018 > 81 * (1 + 1e-5) + 1e-6
    xb = line_points(list(range(20)) + [9.001])
    gt = exact_gt_dist(XQ, xb)
    ret = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 20]])
    assert recall_at_k(XQ, xb, ret, gt) == pytest.approx(0.9)


def test_point_within_tolerance_counts():
    # squared distance 81 + 5e-4 is inside 81 * (1 + 1e-5) + 1e-6 = 81.000811
    x = np.sqrt(81.0005)
    xb = np.vstack([XB, np.array([[x, 0.0]])]).astype(np.float64)
    gt = exact_gt_dist(XQ, xb)
    ret = np.array([[0, 1, 2, 3, 4, 5, 6, 7, 8, 20]])
    assert recall_at_k(XQ, xb, ret, gt) == 1.0


def test_minus_one_padding_and_duplicates_not_counted():
    # 5 distinct correct ids, then a repeat of each one: only 5 count
    dup = np.array([[0, 1, 2, 3, 4, 0, 1, 2, 3, 4]])
    assert recall_at_k(XQ, XB, dup, GT) == pytest.approx(0.5)
    # 6 correct ids, padded with -1
    pad = np.array([[0, 1, 2, 3, 4, 5, -1, -1, -1, -1]])
    assert recall_at_k(XQ, XB, pad, GT) == pytest.approx(0.6)
    # all -1
    assert recall_at_k(XQ, XB, np.full((1, 10), -1), GT) == 0.0


def test_order_of_returned_ids_does_not_matter():
    ids = [9, 3, 15, 0, 7, 1, 12, 5, 2, 8]                  # 8 correct, 2 wrong
    rng = np.random.default_rng(0)
    base = recall_at_k(XQ, XB, np.array([ids]), GT)
    assert base == pytest.approx(0.8)
    for _ in range(5):
        assert recall_at_k(XQ, XB, np.array([rng.permutation(ids)]), GT) == base


def test_fewer_than_k_returned_caps_recall():
    seven = np.array([[0, 1, 2, 3, 4, 5, 6]])               # only 7 columns returned
    assert recall_at_k(XQ, XB, seven, GT) == pytest.approx(0.7)


def test_only_first_k_returned_ids_are_used():
    # 10 wrong ids first, then the 10 correct ones: recall@10 looks at the first 10 only
    ret = np.array([list(range(10, 20)) + list(range(10))])
    assert recall_at_k(XQ, XB, ret, GT) == 0.0


def test_mean_over_multiple_queries():
    # query 1 at the origin, query 2 at x = 19 (its neighbours are ids 10..19)
    xq = np.array([[0.0, 0.0], [19.0, 0.0]], dtype=np.float32)
    gt = exact_gt_dist(xq, XB)
    ret = np.array([list(range(10)),                       # q1: 1.0
                    [19, 18, 17, 16, 0, 1, 2, 3, -1, -1]])  # q2: 4 correct -> 0.4
    np.testing.assert_allclose(recall_per_query(xq, XB, ret, gt), [1.0, 0.4])
    assert recall_at_k(xq, XB, ret, gt) == pytest.approx(0.7)


def test_true_distance_comes_from_vectors_in_float64():
    d = true_sq_dist(XQ, XB, np.array([[3, -1, 19]]))
    assert d.dtype == np.float64
    np.testing.assert_array_equal(d, [[9.0, np.inf, 361.0]])
