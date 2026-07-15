"""The exploration comparison report: variants of each contract, side by side.

Reads the exploration artefacts (one YAML per configuration, the family's
``mavai-explore-1`` interchange schema) and renders a single self-contained page: an overview,
a per-contract leaderboard ranked by overall pass rate then median latency
then average cost, a per-criterion matrix over the union of criteria, and
per-variant latency-distribution strips as dependency-free inline SVG.

The report re-presents artefact values only: percentiles come from the
artefact's own gated latency block (a percentile below its minimum-sample
threshold renders as a dash), the strips are pure geometry over the sorted
passing latencies, and the too-close-to-call marker is a fixed 5%
presentational margin on the ordering — never a significance test.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .report_html import CHART_CSS, document_head, escape, footer, timestamp

# The 5% relative-median margin below which two equally-reliable adjacent
# variants share a rank. Presentational only.
_NEAR_TIE_RELATIVE = 0.05

_STRIP_WIDTH = 360
_STRIP_HEIGHT = 24
_STRIP_MARGIN = 6


@dataclass(frozen=True, slots=True)
class Variant:
    """One explored configuration, as its artefact records it."""

    label: str
    factors: tuple[tuple[str, Any], ...]
    observed_rate: float
    successes: int
    sample_count: int
    termination_reason: str
    avg_time_per_sample_ms: int
    criteria: tuple[tuple[str, float], ...]
    p50_ms: int | None
    p95_ms: int | None
    sorted_latencies_ms: tuple[int, ...]

    @property
    def has_no_samples(self) -> bool:
        return self.sample_count == 0


@dataclass(frozen=True, slots=True)
class ContractComparison:
    """One contract's variants, in artefact order."""

    contract_id: str
    variants: tuple[Variant, ...]


@dataclass(frozen=True, slots=True)
class ExplorationSweep:
    """Every parseable exploration artefact under a directory."""

    contracts: tuple[ContractComparison, ...]
    skipped: tuple[str, ...] = field(default=())


def read_exploration_directory(root: Path) -> ExplorationSweep:
    """Parse ``<root>/<contract-id>/*.yaml``; unparseable files are skipped
    by name, never silently."""
    from ruamel.yaml import YAML  # the declarative extra; present wherever the CLI runs
    from ruamel.yaml.error import YAMLError

    yaml = YAML(typ="safe", pure=True)
    contracts = []
    skipped = []
    for contract_dir in sorted(p for p in root.iterdir() if p.is_dir()) if root.is_dir() else []:
        parsed: list[tuple[dict[str, Any], str]] = []
        for path in sorted(contract_dir.glob("*.yaml")):
            try:
                data = yaml.load(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict) or "statistics" not in data:
                    raise KeyError("statistics")
                parsed.append((data, path.stem))
            except (YAMLError, KeyError, TypeError, ValueError):
                skipped.append(f"{contract_dir.name}/{path.name}")
        if parsed:
            variants = tuple(_variant(data, stem, _differing_keys(parsed)) for data, stem in parsed)
            contracts.append(ContractComparison(contract_id=contract_dir.name, variants=variants))
    return ExplorationSweep(contracts=tuple(contracts), skipped=tuple(skipped))


def _differing_keys(parsed: list[tuple[dict[str, Any], str]]) -> list[str]:
    """The factor keys that distinguish this contract's variants.

    Artefacts carry the full resolved configuration; the label carries
    only the keys whose values vary across the variants (or that some
    variants lack) — the full map sits in each variant's collapsed
    factor list.
    """
    factor_maps = [dict(data.get("factors") or {}) for data, _ in parsed]
    keys = list(dict.fromkeys(key for factors in factor_maps for key in factors))
    return [key for key in keys if len({repr(factors.get(key)) for factors in factor_maps}) > 1]


def _variant(data: dict[str, Any], stem: str, differing: list[str]) -> Variant:
    execution = data.get("execution", {})
    statistics = data.get("statistics", {})
    cost = data.get("cost", {})
    latency = data.get("latency") or {}
    factor_map = dict(data.get("factors") or {})
    factors = tuple(factor_map.items())
    labelled = [(k, factor_map[k]) for k in differing if k in factor_map]
    # The artefact body names its configuration; the filename stem is only
    # a legacy fallback — consumers never parse filenames.
    fallback = str(data.get("configuration") or stem)
    label = ", ".join(f"{k}={v}" for k, v in labelled) if labelled else fallback
    criteria = tuple(
        (name, float(body.get("observedPassRate", 0.0)))
        for name, body in (statistics.get("criteria") or {}).items()
    )
    executed = int(execution.get("samplesExecuted", 0))
    return Variant(
        label=label,
        factors=factors,
        observed_rate=float(statistics.get("observed", 0.0)),
        successes=int(statistics.get("successes", 0)),
        sample_count=executed,
        termination_reason=str(execution.get("terminationReason", "")),
        avg_time_per_sample_ms=int(cost.get("avgTimePerSampleMs", 0)),
        criteria=criteria,
        p50_ms=int(latency["p50Ms"]) if "p50Ms" in latency else None,
        p95_ms=int(latency["p95Ms"]) if "p95Ms" in latency else None,
        sorted_latencies_ms=tuple(int(v) for v in latency.get("sortedPassingLatenciesMs", [])),
    )


def render_exploration_report(contracts: list[ContractComparison]) -> str:
    """Render the comparison page over every contract's variants."""
    generated = timestamp()
    html = [document_head("basel Exploration Comparison", extra_css=CHART_CSS)]
    html.append("<header>\n<h1>basel Exploration Comparison</h1>\n")
    html.append(f'<p class="timestamp">Generated: {escape(generated)}</p>\n</header>\n')
    html.append("<main>\n")
    if not contracts:
        html.append(
            '<p class="empty">No explorations found. Run <code>basel explore</code> '
            "to produce variant data, then regenerate this report.</p>\n"
        )
    else:
        ranked_by_contract = {c.contract_id: _ranked(c.variants) for c in contracts}
        _append_overview(html, contracts, ranked_by_contract)
        if any(_has_near_tie(ranked) for ranked in ranked_by_contract.values()):
            _append_tie_legend(html)
        for contract in contracts:
            _append_contract(html, contract, ranked_by_contract[contract.contract_id])
    html.append("</main>\n")
    html.append(footer(generated))
    return "".join(html)


def _rank_key(variant: Variant) -> tuple[float, int, int]:
    p50 = variant.p50_ms if variant.p50_ms is not None else 2**62
    return (-variant.observed_rate, p50, variant.avg_time_per_sample_ms)


def _ranked(variants: tuple[Variant, ...]) -> list[Variant]:
    return sorted(variants, key=_rank_key)


def _near_tie(a: Variant, b: Variant) -> bool:
    if a.observed_rate != b.observed_rate:
        return False
    if a.p50_ms is None or b.p50_ms is None:
        return False
    larger = max(a.p50_ms, b.p50_ms)
    if larger == 0:
        return True
    return abs(a.p50_ms - b.p50_ms) / larger < _NEAR_TIE_RELATIVE


def _has_near_tie(ranked: list[Variant]) -> bool:
    return any(_near_tie(ranked[i], ranked[i - 1]) for i in range(1, len(ranked)))


def _competition_ranks(ranked: list[Variant]) -> list[int]:
    ranks: list[int] = []
    for i in range(len(ranked)):
        if i > 0 and _near_tie(ranked[i], ranked[i - 1]):
            ranks.append(ranks[i - 1])
        else:
            ranks.append(i + 1)
    return ranks


def _append_overview(
    html: list[str],
    contracts: list[ContractComparison],
    ranked_by_contract: dict[str, list[Variant]],
) -> None:
    html.append('<section class="overview">\n<h2>Overview</h2>\n')
    html.append("<table>\n<thead>\n<tr>")
    html.append("<th>Contract</th><th>Variants</th><th>Best overall</th>")
    html.append("</tr>\n</thead>\n<tbody>\n")
    for contract in contracts:
        ranked = ranked_by_contract[contract.contract_id]
        html.append("<tr>\n")
        html.append(f"<td>{escape(contract.contract_id)}</td>\n")
        html.append(f"<td>{len(contract.variants)}</td>\n")
        html.append(f"<td>{_best_overall(ranked)}</td>\n")
        html.append("</tr>\n")
    html.append("</tbody>\n</table>\n</section>\n")


def _best_overall(ranked: list[Variant]) -> str:
    if not ranked:
        return "&mdash;"
    cell = [escape(ranked[0].label)]
    for i in range(1, len(ranked)):
        if not _near_tie(ranked[i], ranked[i - 1]):
            break
        cell.append(f' <span class="tie-mark">&asymp;</span> {escape(ranked[i].label)}')
    return "".join(cell)


def _append_tie_legend(html: list[str]) -> None:
    html.append(
        '<p class="tie-legend"><span class="tie-mark">&asymp;</span> '
        "Variants sharing a rank are <strong>too close to call</strong>: their pass "
        "rates are equal and their median latencies differ by less than 5%. This flags "
        "a narrow ordering margin for the reader's eye &mdash; it is not a significance "
        "test, and the report makes no claim that one variant is statistically better "
        "than another.</p>\n"
    )


def _append_contract(html: list[str], contract: ContractComparison, ranked: list[Variant]) -> None:
    html.append('<section class="service">\n')
    html.append(f"<h2>{escape(contract.contract_id)}</h2>\n")
    _append_leaderboard(html, ranked)
    _append_criterion_matrix(html, ranked)
    _append_latency_strips(html, ranked)
    html.append("</section>\n")


def _append_leaderboard(html: list[str], ranked: list[Variant]) -> None:
    latencies = [v for variant in ranked for v in (variant.p50_ms, variant.p95_ms) if v is not None]
    max_latency = max(latencies, default=1) or 1
    max_avg = max((v.avg_time_per_sample_ms for v in ranked), default=1) or 1

    html.append("<h3>Leaderboard</h3>\n")
    html.append('<table class="leaderboard">\n<thead>\n<tr>')
    html.append(
        "<th>#</th><th>Variant</th><th>Pass rate</th><th>p50</th><th>p95</th>"
        "<th>Avg cost</th><th>Samples</th><th>Termination</th>"
    )
    html.append("</tr>\n</thead>\n<tbody>\n")
    ranks = _competition_ranks(ranked)
    for i, variant in enumerate(ranked):
        html.append("<tr>\n")
        _append_rank_cell(html, ranked, ranks, i)
        _append_variant_cell(html, variant)
        _append_pass_rate_cell(html, variant)
        _append_latency_cell(html, variant.p50_ms, max_latency)
        _append_latency_cell(html, variant.p95_ms, max_latency)
        _append_cost_cell(html, variant, max_avg)
        html.append(f'<td class="num">{variant.sample_count}</td>\n')
        _append_termination_cell(html, variant.termination_reason)
        html.append("</tr>\n")
    html.append("</tbody>\n</table>\n")


def _append_rank_cell(html: list[str], ranked: list[Variant], ranks: list[int], i: int) -> None:
    tied_previous = i > 0 and _near_tie(ranked[i], ranked[i - 1])
    tied_next = i + 1 < len(ranked) and _near_tie(ranked[i + 1], ranked[i])
    html.append(f'<td class="rank">{ranks[i]}')
    if tied_previous or tied_next:
        html.append(
            '<span class="tie-mark" title="Too close to call: equal pass rate and '
            "median latency within 5% of the adjacent variant — a presentational "
            'margin, not a significance test.">&asymp;</span>'
        )
    html.append("</td>\n")


def _variant_class(variant: Variant) -> str:
    if variant.has_no_samples:
        return "basel-inconclusive"
    return "basel-pass" if variant.observed_rate >= 1.0 else "basel-fail"


def _append_variant_cell(html: list[str], variant: Variant) -> None:
    html.append(
        f'<td>\n<details>\n<summary class="{_variant_class(variant)}">'
        f"{escape(variant.label)}</summary>\n"
    )
    html.append('<dl class="factor-list">\n')
    for key, value in variant.factors:
        html.append(f"<dt>{escape(key)}</dt><dd><pre>{escape(str(value))}</pre></dd>\n")
    html.append("</dl>\n</details>\n</td>\n")


def _percent(fraction: float) -> str:
    clamped = max(0.0, min(1.0, fraction))
    return f"{clamped * 100.0:.2f}%"


def _rate(rate: float) -> str:
    return f"{rate * 100.0:.1f}%"


def _append_pass_rate_cell(html: list[str], variant: Variant) -> None:
    html.append('<td class="passrate">\n')
    if variant.has_no_samples:
        html.append('<div class="bar-track"></div>\n')
        html.append('<span class="basel-inconclusive">0/0</span>\n')
    else:
        html.append('<div class="bar-track">')
        html.append('<div class="bar-fill fail" style="width:100%"></div>')
        html.append(
            f'<div class="bar-fill pass" style="width:{_percent(variant.observed_rate)}"></div>'
        )
        html.append("</div>\n")
        html.append(
            f'<span class="{_variant_class(variant)}">{variant.successes}/'
            f"{variant.sample_count} ({_rate(variant.observed_rate)})</span>\n"
        )
    html.append("</td>\n")


def _append_latency_cell(html: list[str], value_ms: int | None, max_latency: int) -> None:
    html.append('<td class="latency">')
    if value_ms is None:
        html.append('<span class="muted">-</span>')
    else:
        html.append(
            f'<div class="bar-track narrow"><div class="bar-fill muted" '
            f'style="width:{_percent(value_ms / max_latency)}"></div></div>'
        )
        html.append(f"<span>{value_ms}ms</span>")
    html.append("</td>\n")


def _append_cost_cell(html: list[str], variant: Variant, max_avg: int) -> None:
    html.append('<td class="cost">')
    html.append(
        f'<div class="bar-track narrow"><div class="bar-fill muted" '
        f'style="width:{_percent(variant.avg_time_per_sample_ms / max_avg)}"></div></div>'
    )
    html.append(f"<span>{variant.avg_time_per_sample_ms}ms</span></td>\n")


def _append_termination_cell(html: list[str], reason: str) -> None:
    badge = "ok" if reason == "COMPLETED" else "warn"
    text = escape(reason) if reason else "&mdash;"
    html.append(f'<td><span class="badge {badge}">{text}</span></td>\n')


def _append_criterion_matrix(html: list[str], ranked: list[Variant]) -> None:
    criteria = list(dict.fromkeys(name for v in ranked for name, _ in v.criteria))
    if not criteria:
        return
    html.append("<h3>Per-criterion comparison</h3>\n")
    html.append('<table class="criterion-matrix">\n<thead>\n<tr><th>Variant</th>')
    for criterion in criteria:
        html.append(f"<th>{escape(criterion)}</th>")
    html.append("</tr>\n</thead>\n<tbody>\n")
    for variant in ranked:
        html.append(f'<tr>\n<td class="criterion-name">{escape(variant.label)}</td>\n')
        rates = dict(variant.criteria)
        for criterion in criteria:
            _append_criterion_cell(html, rates.get(criterion))
        html.append("</tr>\n")
    html.append("</tbody>\n</table>\n")


def _append_criterion_cell(html: list[str], rate: float | None) -> None:
    if rate is None:
        html.append('<td class="cell-na"><span class="muted">n/a</span></td>\n')
        return
    rate_class = "basel-pass" if rate >= 1.0 else "basel-fail" if rate <= 0.0 else ""
    html.append('<td class="cell">')
    html.append(
        f'<div class="bar-track narrow"><div class="bar-fill pass" '
        f'style="width:{_percent(rate)}"></div></div>'
    )
    html.append(f'<span class="{rate_class}">{_rate(rate)}</span></td>\n')


def _append_latency_strips(html: list[str], ranked: list[Variant]) -> None:
    max_raw = max((v for variant in ranked for v in variant.sorted_latencies_ms), default=0)
    if max_raw == 0:
        return
    html.append("<h3>Latency distribution</h3>\n")
    html.append('<table class="latency-strips">\n<tbody>\n')
    for variant in ranked:
        html.append(f'<tr>\n<td class="strip-label">{escape(variant.label)}</td>\n<td>')
        _append_strip(html, variant, max_raw)
        html.append("</td>\n</tr>\n")
    html.append("</tbody>\n</table>\n")


def _strip_x(value_ms: int, max_raw: int) -> float:
    return _STRIP_MARGIN + (value_ms / max_raw) * (_STRIP_WIDTH - 2 * _STRIP_MARGIN)


def _append_strip(html: list[str], variant: Variant, max_raw: int) -> None:
    sorted_ms = variant.sorted_latencies_ms
    if not sorted_ms:
        html.append('<span class="muted">no passing samples</span>')
        return
    html.append(
        f'<svg class="latency-strip-svg" viewBox="0 0 {_STRIP_WIDTH} {_STRIP_HEIGHT}" '
        f'width="{_STRIP_WIDTH}" height="{_STRIP_HEIGHT}" role="img">'
    )
    x0, x1 = _strip_x(sorted_ms[0], max_raw), _strip_x(sorted_ms[-1], max_raw)
    html.append(f'<line x1="{x0:.1f}" y1="12" x2="{x1:.1f}" y2="12" class="strip-axis"/>')
    for ms in sorted_ms:
        html.append(f'<circle cx="{_strip_x(ms, max_raw):.1f}" cy="12" r="2" class="strip-dot"/>')
    if variant.p50_ms is not None:
        xp = _strip_x(variant.p50_ms, max_raw)
        html.append(f'<line x1="{xp:.1f}" y1="4" x2="{xp:.1f}" y2="20" class="strip-p50"/>')
    html.append("</svg>")
    html.append(f'<span class="strip-range">{sorted_ms[0]}&ndash;{sorted_ms[-1]}ms</span>')
