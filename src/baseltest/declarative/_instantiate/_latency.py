"""The latency bar: the contract's latency spec resolved to concrete bounds.

Every refusal here is a configuration fact knowable up front, so it fires
before any service invocation: an asserted percentile the planned sample
count can never estimate, an empirical declaration with no usable baseline,
and a requested confidence a baseline's size cannot support.
"""

from baseltest.baseline import BaselineResolution
from baseltest.contract import (
    PERCENTILE_LEVELS,
    LatencyBar,
    LatencyBound,
    ThresholdProvenance,
)
from baseltest.engine import minimum_contributing_samples
from baseltest.statistics import bound_existence_minimum, derive_latency_threshold

from .._errors import ContractConfigurationError
from .._parser import ContractDeclaration


def _latency_bar(
    declaration: ContractDeclaration,
    samples: int,
    resolution: BaselineResolution | None,
) -> LatencyBar | None:
    """The contract's latency bar, resolved to concrete bounds — or a refusal.

    Every refusal here fires before any service invocation: an asserted
    percentile the planned sample count can never estimate, an empirical
    declaration with no usable baseline, and a requested confidence the
    baseline's size cannot support a non-saturated bound at (the
    distribution-free existence condition) are all configuration facts,
    knowable up front.
    """
    spec = declaration.latency
    if spec is None:
        return None
    confidence = spec.confidence if spec.confidence is not None else declaration.confidence
    asserted = [percentile for percentile, _ in spec.ceilings] or list(spec.empirical)
    for percentile in asserted:
        minimum = minimum_contributing_samples(percentile)
        if minimum > samples:
            raise ContractConfigurationError(
                f"the latency bound on {percentile} needs at least {minimum} passing "
                f"samples to estimate, and the run is planned at {samples} — run with "
                f"`--samples {minimum}` or more (only passing samples contribute)"
            )

    if spec.ceilings:
        return LatencyBar(
            bounds=tuple(
                LatencyBound(percentile=percentile, threshold_ms=ms)
                for percentile, ms in spec.ceilings
            ),
            origin="explicit",
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
            "latency recording) — re-run `basel measure`"
        )
    vector = list(stored.latency.sorted_passing_latencies_ms)
    bounds = []
    for percentile in spec.empirical:
        derived = derive_latency_threshold(vector, PERCENTILE_LEVELS[percentile], confidence)
        if derived.saturated:
            required = bound_existence_minimum(PERCENTILE_LEVELS[percentile], confidence)
            raise ContractConfigurationError(
                f"no {confidence:.0%}-confident upper bound on {percentile} exists "
                f"from a baseline of {derived.n} passing samples — at least "
                f"{required} are needed. Re-measure with a larger budget, or declare "
                "a lower `latency: confidence:`"
            )
        bounds.append(
            LatencyBound(
                percentile=percentile,
                threshold_ms=round(derived.threshold),
                rank=derived.rank,
                baseline_percentile_ms=round(derived.baseline_percentile),
                baseline_samples=derived.n,
            )
        )
    return LatencyBar(
        bounds=tuple(bounds),
        origin="baseline-derived",
        confidence=confidence,
        provenance=ThresholdProvenance(origin="empirical", contract_ref=stored.path.name),
    )
