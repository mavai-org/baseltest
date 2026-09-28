"""The latency bar: the contract's latency spec resolved to enforced constraints.

The refusals here are configuration facts knowable up front, so they fire
before any service invocation: an empirical declaration with no usable
baseline, or a baseline that recorded no latency profile. Everything that
depends on how many successful latencies the run returns — the
non-degeneracy gate and the precedence rank — is decided after the run; the
engine's planning checks warn about it beforehand (``engine.plan_latency``).
"""

from baseltest.baseline import BaselineResolution
from baseltest.contract import (
    LatencyBar,
    LatencyBaseline,
    LatencyBound,
    ThresholdProvenance,
)
from baseltest.statistics import ThresholdSource

from .._errors import ContractConfigurationError
from .._parser import ContractDeclaration


def _latency_bar(
    declaration: ContractDeclaration, resolution: BaselineResolution | None
) -> LatencyBar | None:
    """The contract's latency bar — explicit ceilings, or baseline-derived
    constraints carrying the baseline they are derived from — or a refusal."""
    spec = declaration.latency
    if spec is None:
        return None
    confidence = spec.confidence if spec.confidence is not None else declaration.confidence
    if spec.ceilings:
        return LatencyBar(
            bounds=tuple(
                LatencyBound(percentile=percentile, threshold_ms=ms)
                for percentile, ms in spec.ceilings
            ),
            origin=ThresholdSource.EXPLICIT,
            confidence=confidence,
            provenance=ThresholdProvenance(
                origin=spec.threshold_origin or "unspecified",
                contract_ref=spec.contract_ref,
            ),
        )

    if resolution is None or not resolution.matched:
        reason = (
            resolution.reason
            if resolution is not None and resolution.reason
            else "no baseline was found"
        )
        raise ContractConfigurationError(
            f"empirical latency bounds derive from a measured baseline: {reason} — "
            "run `basel measure` first"
        )
    stored = resolution.baseline
    assert stored is not None
    if stored.latency is None or not stored.latency.sorted_passing_latencies_ms:
        raise ContractConfigurationError(
            f"baseline {stored.path.name} records no latency profile (it predates "
            "latency recording, or no sample passed) — re-run `basel measure`"
        )
    return LatencyBar(
        bounds=tuple(LatencyBound(percentile=percentile) for percentile in spec.empirical),
        origin=ThresholdSource.BASELINE_DERIVED,
        confidence=confidence,
        baseline=LatencyBaseline(
            sorted_latencies_ms=tuple(stored.latency.sorted_passing_latencies_ms),
            samples=stored.sample_count,
        ),
        provenance=ThresholdProvenance(origin="empirical", contract_ref=stored.path.name),
    )
