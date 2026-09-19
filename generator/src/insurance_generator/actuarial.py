"""Actuarial sampling.

Frequency and severity are modelled as independent distributions, which is how
pricing actuaries treat them. Aggregate loss then emerges from the simulation
rather than being imposed on it.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from .config import ProductClassParameters

DAYS_PER_YEAR = 365.25
MINIMUM_REPORTING_LAG_DAYS = 0
MAXIMUM_REPORTING_LAG_DAYS = 400


def exposure_years(period_start: date, period_end: date) -> float:
    """Fraction of a year a policy was on risk between two dates."""
    if period_end <= period_start:
        return 0.0
    return (period_end - period_start).days / DAYS_PER_YEAR


def sample_claim_count(
    rng: np.random.Generator,
    product: ProductClassParameters,
    years_on_risk: float,
) -> int:
    """Number of claims a policy produces, Poisson in its exposure period."""
    if years_on_risk <= 0:
        return 0
    expected_claims = product.claim_frequency_per_year * years_on_risk
    return int(rng.poisson(expected_claims))


def sample_claim_severity(
    rng: np.random.Generator,
    product: ProductClassParameters,
    sum_insured: float,
) -> float:
    """Claim amount from a log-normal distribution, capped at the sum insured.

    Log-normal reproduces the right skew of real claims: many small losses and
    a thin tail of very large ones.
    """
    severity = rng.lognormal(product.severity_log_mean, product.severity_log_sigma)
    return float(min(severity, sum_insured))


def sample_reporting_lag_days(
    rng: np.random.Generator,
    product: ProductClassParameters,
) -> int:
    """Days between incident and notification.

    Exponential, so most claims are reported quickly while a minority surface
    months later. This lag is what creates IBNR reserves and late-arriving
    stream events.
    """
    lag = rng.exponential(product.mean_reporting_lag_days)
    bounded_lag = np.clip(lag, MINIMUM_REPORTING_LAG_DAYS, MAXIMUM_REPORTING_LAG_DAYS)
    return int(round(bounded_lag))


def sample_sum_insured(
    rng: np.random.Generator,
    product: ProductClassParameters,
) -> float:
    """Sum insured, log-uniform across the product's band.

    Log-uniform rather than uniform because insured values cluster toward the
    lower end of any band in practice.
    """
    log_low = np.log(product.minimum_sum_insured)
    log_high = np.log(product.maximum_sum_insured)
    return float(round(np.exp(rng.uniform(log_low, log_high)), -3))


def calculate_annual_premium(
    rng: np.random.Generator,
    product: ProductClassParameters,
    sum_insured: float,
) -> float:
    """Premium as a rate on sum insured, with underwriting discretion applied."""
    underwriting_factor = float(rng.normal(1.0, 0.12))
    bounded_factor = float(np.clip(underwriting_factor, 0.7, 1.45))
    return float(round(sum_insured * product.premium_rate * bounded_factor, 2))


def sample_incident_date(
    rng: np.random.Generator,
    coverage_start: date,
    coverage_end: date,
) -> date:
    """Uniform incident date within the coverage period."""
    coverage_days = max((coverage_end - coverage_start).days, 1)
    return coverage_start + timedelta(days=int(rng.integers(0, coverage_days)))