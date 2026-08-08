"""Tests for stats.py. One of these is seeded to fail against the shipped code."""

from __future__ import annotations

import pytest

from stats import mean, median, value_range


def test_mean_of_simple_list() -> None:
    assert mean([1.0, 2.0, 3.0]) == 2.0


def test_mean_of_empty_list_raises() -> None:
    with pytest.raises(ValueError):
        mean([])


def test_median_of_odd_length_list() -> None:
    assert median([5.0, 1.0, 3.0]) == 3.0


def test_median_of_even_length_list() -> None:
    # The seeded failure: the shipped median() returns 4.0 (the upper-middle
    # element) instead of the mean of the two middle values.
    assert median([1.0, 2.0, 4.0, 8.0]) == 3.0


def test_value_range() -> None:
    assert value_range([2.0, 9.0, 4.0]) == 7.0
