"""SignalPulse offline evaluation harness (M3-A0).

This package provides a deterministic, offline corpus and the metrics to
measure retrieval intelligence (ranking, deduplication, freshness) BEFORE the
production algorithms exist. See ``eval/README.md`` for labeling rules,
metric definitions, and target thresholds.

Note: this package is named ``eval`` after the project folder, not the Python
builtin. It contains no code that shadows the builtin function.
"""

__all__ = ["baseline", "corpus", "metrics", "runner", "schema"]
