"""PSD conditioning: symmetrize, clip, preserve the trace, report.

Scenarios: Every covariance matrix is usable.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from sobres.core.moments import condition_covariance, is_psd


def _frame(values: list[list[float]]) -> pd.DataFrame:
    names = [f"A{i}" for i in range(len(values))]
    return pd.DataFrame(values, index=names, columns=names)


def test_already_psd_matrix_is_unchanged() -> None:
    sigma = _frame([[0.04, 0.01], [0.01, 0.09]])
    out, repair = condition_covariance(sigma)
    assert repair is None
    pd.testing.assert_frame_equal(out, sigma)


def test_repairs_non_psd_and_warns() -> None:
    # Correlation 1.2 is impossible: the matrix has a negative eigenvalue.
    sigma = _frame([[1.0, 1.2], [1.2, 1.0]])
    assert not is_psd(sigma)
    out, repair = condition_covariance(sigma)
    assert repair is not None
    assert repair.min_eigenvalue == pytest_approx(-0.2)
    assert repair.clipped == 1
    assert is_psd(out)
    assert np.trace(out.to_numpy()) == pytest_approx(np.trace(sigma.to_numpy()))


def test_repaired_matrix_is_psd_and_symmetric() -> None:
    rng = np.random.default_rng(0)
    raw = rng.normal(size=(4, 4))
    sigma = _frame((raw @ raw.T - 3 * np.eye(4)).tolist())  # push eigenvalues negative
    out, repair = condition_covariance(sigma)
    assert repair is not None and is_psd(out)
    values = out.to_numpy()
    assert np.allclose(values, values.T, atol=1e-12)


def test_float_asymmetry_is_symmetrized() -> None:
    sigma = _frame([[0.04, 0.01 + 1e-13], [0.01, 0.09]])
    out, repair = condition_covariance(sigma)
    assert repair is None and out.loc["A0", "A1"] == out.loc["A1", "A0"]
    assert not is_psd(_frame([[0.04, 0.02], [0.01, 0.09]]))  # asymmetric beyond tolerance


def pytest_approx(value: float) -> object:
    import pytest

    return pytest.approx(value)
