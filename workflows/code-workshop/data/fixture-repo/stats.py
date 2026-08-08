"""Small descriptive-statistics helpers."""

from __future__ import annotations


def mean(values: list[float]) -> float:
    """Arithmetic mean of a non-empty list."""
    if not values:
        raise ValueError("mean() of empty list")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    """Middle value of a non-empty list.

    For an even number of values this must be the mean of the two middle
    values.
    """
    if not values:
        raise ValueError("median() of empty list")
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def value_range(values: list[float]) -> float:
    """Difference between the largest and smallest value."""
    if not values:
        raise ValueError("value_range() of empty list")
    return max(values) - min(values)
