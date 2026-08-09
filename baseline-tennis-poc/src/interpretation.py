"""Attaches semantics to raw metric results.

The point of the semantic layer is that meaning travels with data. A number in a
tool result that says only "440146.32" invites the agent to invent a judgment;
the same number with a band comparison, a direction of goodness, the required
caveats, and a computed confidence block does not.

Everything here is read from the metric descriptors and benchmarks. This module
decides nothing on its own; it assembles what the content declares.
"""

from __future__ import annotations

from catalog import get_catalog

# Months where the domain declares a known seasonal pattern.
SPRING_MONTHS = {3, 4, 5}
DECEMBER = 12


def _month_of(period_end: str) -> int:
    try:
        return int(period_end.split("-")[1])
    except (IndexError, ValueError):
        return 0


def _band_verdict(value: float, low: float | None, high: float | None,
                  direction: str) -> dict:
    """Where the value sits relative to the internal band, in plain language."""
    if value is None or low is None or high is None:
        return {"position": "no_band", "reading": "No benchmark band is defined "
                "for this metric, so no band judgment is available."}
    if low <= value <= high:
        return {"position": "within_band", "band": [low, high],
                "reading": f"Within the normal internal band of {low} to {high}."}
    if value > high:
        good = direction == "higher_better"
        return {"position": "above_band", "band": [low, high],
                "is_favorable": good,
                "reading": (f"Above the normal band of {low} to {high}. "
                            + ("This is favorable for this metric."
                               if good else
                               "For this metric LOWER is better, so being above "
                               "the band is UNFAVORABLE."))}
    good = direction == "lower_better"
    return {"position": "below_band", "band": [low, high],
            "is_favorable": good,
            "reading": (f"Below the normal band of {low} to {high}. "
                        + ("For this metric LOWER is better, so being below the "
                           "band is favorable."
                           if good else
                           "This is unfavorable for this metric."))}


def _seasonal_notes(spec: dict, period_end: str, period_label: str) -> list[str]:
    notes: list[str] = []
    ev = spec.get("evaluation", {})
    m = _month_of(period_end)
    declared = ev.get("seasonal_pattern") or []
    if m in SPRING_MONTHS:
        notes.append(
            f"The period {period_label} falls in spring league season (March "
            "through May), when this business runs above its annual band by "
            "design. Elevated values here are expected seasonality.")
    if m == DECEMBER:
        notes.append(
            f"The period {period_label} is December, which is intentionally "
            "quiet: send volume and paid budget are reduced over the holidays. "
            "A December decline is EXPECTED SEASONALITY and is not a "
            "performance problem.")
    notes.extend(declared)
    if ev.get("seasonal_guidance"):
        notes.append(ev["seasonal_guidance"])
    return notes


def _confidence(spec: dict, results: list[dict], period_start: str,
                period_end: str, cohort_size: int | None,
                filters: dict | None = None) -> dict:
    """Compute the confidence block at query time.

    Three independent things can degrade a result: sample size, a declared
    coverage hole intersecting the requested period, and a definition caveat that
    applies to the question. Each is reported with a plain language reason.
    """
    rel = spec.get("reliability", {}) or {}
    min_sample = rel.get("min_sample", 100)
    # A census metric counts a population rather than estimating a rate from a
    # sample, so its value IS the sample size and a small number is exact, not
    # unreliable. Flagging it would label "74 signups" as directional when it is
    # a precise fact, which misleads in the opposite direction from usual.
    is_census = bool(rel.get("is_census")) or min_sample is None
    reasons: list[str] = []
    flags: list[str] = []

    # ---- sample adequacy, per result row -------------------------------
    thin_rows = []
    for r in results if not is_census else []:
        n = r.get("sample_size")
        if n is not None and n < min_sample:
            dim_desc = ", ".join(
                f"{k}={v}" for k, v in r.items()
                if k not in ("value", "sample_size")) or "overall"
            thin_rows.append((dim_desc, n))
    if thin_rows:
        flags.append("low_sample")
        for dim_desc, n in thin_rows[:6]:
            reasons.append(
                f"SMALL SAMPLE: the slice '{dim_desc}' rests on {n} underlying "
                f"rows, below the reliability threshold of {min_sample}. Report "
                "this value WITH the sample size and label it directional; do "
                "not present it as a stable figure.")

    # ---- declared coverage holes ---------------------------------------
    for cov in rel.get("coverage") or []:
        if isinstance(cov, str):
            reasons.append(f"COVERAGE LIMIT: {cov}")
            flags.append("coverage_limit_declared")
            continue
        dim, val = cov.get("dimension"), cov.get("value")
        limit = cov.get("limit", "")
        if not dim:
            continue
        sliced_by_dim = any(dim in r for r in results)
        present = any(str(r.get(dim)) == str(val) for r in results)
        if sliced_by_dim and not present:
            # The affected slice is MISSING from the results. This is the most
            # dangerous case: a silent absence reads as "this channel does not
            # exist" rather than "we never tracked it". Say so explicitly.
            flags.append("coverage_hole")
            flags.append("declared_slice_absent")
            reasons.append(
                f"DECLARED SLICE ABSENT ({dim}={val}): this slice returned NO "
                f"ROWS for the requested period, and that absence is EXPECTED "
                f"and DOCUMENTED, not a data error. {limit} "
                f"State explicitly that {val} is unavailable for this period and "
                "why. Do NOT report it as zero, do NOT omit it silently, and do "
                "NOT extrapolate a value from the covered periods.")
        elif present or not sliced_by_dim:
            # Either the affected slice is in the results, or the request was
            # ungrouped so the hole sits inside the reported total.
            flags.append("coverage_hole")
            reasons.append(
                f"COVERAGE HOLE ({dim}={val}): {limit} "
                "Report the covered periods and name the boundary. Do NOT "
                "extrapolate into the uncovered period.")

    # ---- definition caveats --------------------------------------------
    for cav in rel.get("definition_caveats") or []:
        reasons.append(f"DEFINITION: {cav}")
    if rel.get("definition_caveats"):
        flags.append("definition_caveats_apply")

    # ---- cohort context -------------------------------------------------
    if cohort_size is not None:
        if min_sample is not None and cohort_size < min_sample:
            flags.append("small_cohort")
            reasons.append(
                f"SMALL COHORT: the requested cohort contains {cohort_size} "
                f"customers, below the reliability threshold of {min_sample}. "
                "Any comparison against a baseline is directional only.")
        reasons.append(
            f"COHORT FILTERED: computed on an explicit cohort of {cohort_size} "
            "customers through the governed definition. Compare against a "
            "matched or non exposed cohort measured the same way, NOT against "
            "the overall benchmark band.")

    non_null = [r for r in results if r.get("value") is not None]
    if not non_null:
        flags.append("no_data")
        msg = ("NO DATA: the query returned no rows for this period and filter "
               "combination. This is an absence of data, not a value of zero. Do "
               "not report zero, and do not estimate.")
        # An empty result is ambiguous, and the ambiguity has burned us: a
        # campaign filter on the default period returns nothing simply because
        # the campaign ran earlier, which reads as "attribution is unavailable"
        # unless the payload says otherwise.
        if filters:
            msg += (
                f" IMPORTANT: filters were applied ({', '.join(sorted(filters))})"
                f" over the period {period_start} to {period_end}. The most "
                "likely cause is that the filtered entity does not exist IN THAT "
                "PERIOD, not that the data is missing. If you filtered by "
                "campaign_id, re query using the campaign's own start and end "
                "dates before concluding anything is unavailable.")
        reasons.append(msg)

    level = "high"
    if "no_data" in flags:
        level = "none"
    elif {"coverage_hole", "low_sample", "small_cohort"} & set(flags):
        level = "low"
    elif flags:
        level = "medium"

    return {
        "level": level,
        "flags": sorted(set(flags)),
        "min_sample": min_sample,
        "reasons": reasons,
        "must_surface": level in ("low", "none") or bool(
            {"coverage_hole", "low_sample", "small_cohort", "no_data"} & set(flags)),
        "instruction": (
            "Degraded confidence must be surfaced in the ANSWER BODY with its "
            "reason, not buried in a footnote or omitted."
            if level in ("low", "none") else
            "Confidence is adequate. Required caveats still apply."),
    }


def interpret(raw: dict) -> dict:
    """Wrap a metrics_engine result with its full semantic payload."""
    cat = get_catalog()
    metric_id = raw["metric_id"]
    spec = cat.metric(metric_id) or {}
    ev = spec.get("evaluation", {}) or {}
    fr = spec.get("framing", {}) or {}
    df = spec.get("definition", {}) or {}
    bench = cat.benchmark_for(metric_id)

    direction = ev.get("direction", "higher_better")
    results = raw.get("results", [])

    # ---- benchmark comparison, per row where a band exists -------------
    low, high = bench.get("baseline_low"), bench.get("baseline_high")
    benchmark_block: dict = {
        "direction": direction,
        "direction_meaning": (
            "HIGHER is better for this metric."
            if direction == "higher_better" else
            "LOWER IS BETTER for this metric. An increase is unfavorable; do "
            "not describe a rise as an improvement."),
        "band_source": "benchmarks.yaml, computed from the seeded data",
    }
    if bench.get("note"):
        benchmark_block["band_note"] = bench["note"]

    if len(results) == 1 and not raw.get("dimensions"):
        benchmark_block["comparison"] = _band_verdict(
            results[0].get("value"), low, high, direction)
    elif results:
        # Per-slice comparison. By-channel and by-segment bands are declared
        # separately where they exist; otherwise the overall band is the only
        # reference and that is stated rather than silently assumed.
        per = {}
        by_channel = bench.get("by_channel") or {}
        by_segment = bench.get("by_segment") or {}
        for r in results:
            key = ", ".join(str(r.get(d)) for d in raw.get("dimensions", []))
            ref_low, ref_high = low, high
            slice_band = None
            for m in (by_channel, by_segment):
                if key in m:
                    slice_band = m[key]
            if slice_band is not None:
                per[key] = {
                    "value": r.get("value"),
                    "reference": slice_band,
                    "reading": (
                        f"Reference value for {key} is {slice_band}. "
                        + ("Higher is better." if direction == "higher_better"
                           else "LOWER is better.")),
                }
            else:
                per[key] = {"value": r.get("value"),
                            "reference": None,
                            "reading": "No slice specific band is defined."}
        benchmark_block["per_slice"] = per
        if low is not None:
            benchmark_block["overall_band"] = [low, high]
            benchmark_block["overall_band_caveat"] = (
                "The overall band is computed on the whole population. A single "
                "slice may sit outside it for structural reasons that are not a "
                "performance signal.")

    # ---- computation notes ---------------------------------------------
    computation = {
        "formula": df.get("formula"),
        "filters_applied": df.get("filters", []),
        "filter_rationale": df.get("filter_rationale"),
        "additive": df.get("additive"),
        "additive_note": df.get("additive_note"),
        "source": df.get("source_table"),
    }
    # Filters a metric accepts are part of its interface. Left undeclared, an
    # agent has no way to discover that a question IS answerable (a campaign
    # revenue question needs a campaign_id filter, not a dimension) and will
    # decline something it could have answered.
    if df.get("available_filters"):
        computation["available_filters"] = df["available_filters"]
    if df.get("available_filters_note"):
        computation["available_filters_note"] = df["available_filters_note"]
    if df.get("dimension_notes"):
        computation["dimension_notes"] = df["dimension_notes"]
    if df.get("denominator_note"):
        computation["denominator_note"] = df["denominator_note"]
    if df.get("join_note"):
        computation["join_note"] = df["join_note"]
    if df.get("window"):
        computation["window"] = df["window"]

    # ---- framing --------------------------------------------------------
    framing = {
        "required_caveats": fr.get("required_caveats", []),
        "companions": fr.get("companions", []),
        "companion_rationale": fr.get("companion_rationale"),
        "when_not_to_use": fr.get("when_not_to_use", []),
    }
    for key in ("conflict_rule", "segment_note", "diagnosis_note",
                "direction_caveat", "cohort_comparison_guidance"):
        if fr.get(key):
            framing[key] = fr[key]
        elif ev.get(key):
            framing[key] = ev[key]

    payload = dict(raw)
    payload["interpretation"] = {
        "computation": computation,
        "evaluation": {
            **benchmark_block,
            "seasonal_notes": _seasonal_notes(spec, raw.get("period_end", ""),
                                              raw.get("period", "")),
            "known_events": ev.get("known_events", []),
        },
        "framing": framing,
        "confidence": _confidence(spec, results, raw.get("period_start", ""),
                                  raw.get("period_end", ""),
                                  raw.get("cohort_size"),
                                  raw.get("filters")),
        "cannot_answer": (spec.get("reliability", {}) or {}).get(
            "cannot_answer", []),
        "access": (spec.get("access", {}) or {}).get("path", "metrics_engine"),
    }
    return payload
