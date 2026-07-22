"""Descriptive statistics of an observed proportion.

The sample variance and standard error of an observed pass rate — the
dispersion measures a report displays beside the rate itself. These are
descriptive summaries of what was observed, not inferential claims about
the underlying rate (that is the Wilson interval's job); they live here so
the artefact and console renderers can read a precomputed value rather than
doing arithmetic over rates themselves.
"""

import math


def proportion_variance(successes: int, trials: int) -> float:
    """Sample variance of the observed Bernoulli rate: ``p(1 - p)``.

    Zero for an empty tally — there is no observed rate to disperse.
    """
    if trials == 0:
        return 0.0
    rate = successes / trials
    return rate * (1.0 - rate)


def proportion_standard_error(successes: int, trials: int) -> float:
    """Standard error of the observed proportion: ``sqrt(p(1 - p) / n)``.

    Zero for an empty tally.
    """
    if trials == 0:
        return 0.0
    rate = successes / trials
    return math.sqrt(rate * (1.0 - rate) / trials)
