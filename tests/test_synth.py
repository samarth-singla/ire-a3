"""Tests for the Part 4 drift generator (annbench.synth). Small Gaussian data only, no datasets."""
import numpy as np

from annbench.synth import apply_drift, base_radius, drift_direction


def fake(seed=0, n=2000, d=16):
    rng = np.random.default_rng(seed)
    return (rng.normal(size=(n, d)).astype(np.float32),
            rng.normal(size=(n, d)).astype(np.float32),
            rng.normal(size=(100, d)).astype(np.float32))


def test_same_seed_gives_bit_identical_arrays():
    base, added, q = fake()
    a = apply_drift(base, added, q, shift=0.5, seed=42)
    b = apply_drift(base, added, q, shift=0.5, seed=42)
    for key in ("base", "added", "queries"):
        assert a[key].dtype == np.float32 and a[key].flags["C_CONTIGUOUS"]
        assert a[key].tobytes() == b[key].tobytes()          # bit-identical
    assert a["u"].tobytes() == b["u"].tobytes()


def test_different_seed_gives_different_arrays():
    base, added, q = fake()
    a = apply_drift(base, added, q, shift=0.5, seed=42)
    b = apply_drift(base, added, q, shift=0.5, seed=43)
    assert not np.array_equal(a["added"], b["added"])
    assert not np.array_equal(a["queries"], b["queries"])
    np.testing.assert_array_equal(a["base"], b["base"])       # base never moves


def test_only_the_shift_changes_between_settings():
    base, added, q = fake()
    runs = {s: apply_drift(base, added, q, shift=s, seed=42) for s in (0.0, 0.25, 0.5, 1.0)}
    u, R = drift_direction(base.shape[1], 42), base_radius(base)
    for s, r in runs.items():
        assert r["R"] == R and np.array_equal(r["u"], u)     # same direction and radius
        np.testing.assert_array_equal(r["base"], base)
        moved = r["added"].astype(np.float64) - added
        np.testing.assert_allclose(moved, np.broadcast_to(s * R * u, moved.shape), atol=1e-5)
    # control: nothing moves
    np.testing.assert_array_equal(runs[0.0]["added"], added)
    np.testing.assert_array_equal(runs[0.0]["queries"], q)


def test_direction_is_unit_and_radius_is_mean_distance():
    u = drift_direction(128, 7)
    assert abs(np.linalg.norm(u) - 1.0) < 1e-12
    pts = np.array([[1.0, 0.0], [-1.0, 0.0], [0.0, 3.0], [0.0, -3.0]])
    assert base_radius(pts) == 2.0
