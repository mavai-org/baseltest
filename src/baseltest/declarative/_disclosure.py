"""Sizing-transparency computation for the test report.

The report renderer formats and never computes, so the numbers behind the
sizing disclosures — the drop a downsized run can actually catch, and the
estimated saving of running below the baseline's own size — are computed
here, from the parsed verdict record, through the same oracle-locked
statistics the sizing itself uses. The inline report and a post-hoc
``basel report test`` call the same function over the same record, so
their disclosures are identical by construction.
"""

from baseltest.reporting import SizingDisclosure, VerdictRecord
from baseltest.statistics import DEFAULT_POWER, detectable_rate


def sizing_disclosure(record: VerdictRecord) -> SizingDisclosure | None:
    """Compute one record's sizing disclosures, or ``None`` when the record
    carries no recorded design (records predating the disclosures).

    The downsizing and efficiency values are present iff the executed
    sample count sits below the resolved baseline's own sampling size;
    a baseline-less or baseline-sized run disclosed only its approach.
    """
    design = record.design
    if design is None:
        return None
    target_power = design.claims[0].target_power if design.claims else DEFAULT_POWER

    baseline = design.baseline
    downsized = (
        baseline is not None
        and record.planned_samples < baseline.samples
        and 0.0 < baseline.baseline_rate < 1.0
    )
    if not downsized:
        return SizingDisclosure(
            design=design,
            executed_samples=record.planned_samples,
            target_power=target_power,
        )

    assert baseline is not None
    catchable = detectable_rate(
        record.planned_samples, baseline.baseline_rate, record.confidence, target_power
    )
    per_sample_ms = record.elapsed_ms / record.planned_samples
    saved_samples = baseline.samples - record.planned_samples
    return SizingDisclosure(
        design=design,
        executed_samples=record.planned_samples,
        target_power=target_power,
        detectable_rate=catchable,
        baseline_samples=baseline.samples,
        time_saved_fraction=saved_samples / baseline.samples,
        time_saved_ms=round(per_sample_ms * saved_samples),
    )
