"""Central configuration for the synthetic insurance simulation.

Every tunable number lives here. Other modules read parameters from these
dataclasses rather than embedding literals, so a run is fully described by a
config plus a seed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ProductClassParameters:
    """Actuarial parameters for a single line of business."""

    name: str
    claim_frequency_per_year: float
    severity_log_mean: float
    severity_log_sigma: float
    premium_rate: float
    minimum_sum_insured: float
    maximum_sum_insured: float
    mean_reporting_lag_days: float


MOTOR_PRIVATE = ProductClassParameters(
    name="MOTOR_PRIVATE",
    claim_frequency_per_year=0.16,
    severity_log_mean=11.4,
    severity_log_sigma=0.95,
    premium_rate=0.045,
    minimum_sum_insured=400_000,
    maximum_sum_insured=6_000_000,
    mean_reporting_lag_days=9.0,
)

MOTOR_COMMERCIAL = ProductClassParameters(
    name="MOTOR_COMMERCIAL",
    claim_frequency_per_year=0.34,
    severity_log_mean=12.1,
    severity_log_sigma=1.10,
    premium_rate=0.062,
    minimum_sum_insured=800_000,
    maximum_sum_insured=15_000_000,
    mean_reporting_lag_days=12.0,
)

MEDICAL = ProductClassParameters(
    name="MEDICAL",
    claim_frequency_per_year=2.30,
    severity_log_mean=9.6,
    severity_log_sigma=0.80,
    premium_rate=0.085,
    minimum_sum_insured=250_000,
    maximum_sum_insured=5_000_000,
    mean_reporting_lag_days=4.0,
)

PROPERTY = ProductClassParameters(
    name="PROPERTY",
    claim_frequency_per_year=0.07,
    severity_log_mean=12.6,
    severity_log_sigma=1.35,
    premium_rate=0.028,
    minimum_sum_insured=1_500_000,
    maximum_sum_insured=80_000_000,
    mean_reporting_lag_days=16.0,
)

PRODUCT_CLASSES: tuple[ProductClassParameters, ...] = (
    MOTOR_PRIVATE,
    MOTOR_COMMERCIAL,
    MEDICAL,
    PROPERTY,
)

# Relative likelihood of a policy being written in each class.
PRODUCT_CLASS_WEIGHTS: tuple[float, ...] = (0.42, 0.18, 0.30, 0.10)


@dataclass(frozen=True)
class FraudParameters:
    """Controls how much fraud is injected and of which kinds."""

    overall_fraud_rate: float = 0.035
    staged_accident_share: float = 0.40
    inflated_claim_share: float = 0.40
    agent_collusion_share: float = 0.20

    staged_ring_minimum_size: int = 3
    staged_ring_maximum_size: int = 9
    staged_maximum_days_from_inception: int = 45

    inflation_multiplier_minimum: float = 1.8
    inflation_multiplier_maximum: float = 4.5


@dataclass(frozen=True)
class SimulationConfig:
    """A complete, reproducible description of one generated dataset."""

    seed: int = 42
    history_start: date = date(2023, 1, 1)
    history_end: date = date(2026, 9, 1)

    customer_count: int = 20_000
    agent_count: int = 120
    service_provider_count: int = 260

    policies_per_customer_mean: float = 1.4
    lapse_probability: float = 0.11
    reinstatement_probability: float = 0.45
    endorsement_probability: float = 0.18

    fraud: FraudParameters = field(default_factory=FraudParameters)


COUNTIES: tuple[str, ...] = (
    "Nairobi", "Kiambu", "Mombasa", "Nakuru", "Kisumu", "Uasin Gishu",
    "Machakos", "Kajiado", "Meru", "Nyeri", "Kakamega", "Bungoma",
    "Kilifi", "Murang'a", "Trans Nzoia", "Kericho",
)

# Nairobi and Kiambu carry a disproportionate share of insured risk.
COUNTY_WEIGHTS: tuple[float, ...] = (
    0.31, 0.11, 0.09, 0.07, 0.06, 0.05,
    0.04, 0.04, 0.03, 0.03, 0.03, 0.03,
    0.04, 0.03, 0.02, 0.02,
)

PROVIDER_TYPES: tuple[str, ...] = ("GARAGE", "HOSPITAL", "ASSESSOR")

PAYMENT_CHANNELS: tuple[str, ...] = ("MPESA", "BANK_TRANSFER", "CARD", "CHEQUE")

POLICY_STATUSES: tuple[str, ...] = ("ACTIVE", "LAPSED", "EXPIRED", "CANCELLED")

CLAIM_STATUSES: tuple[str, ...] = (
    "REPORTED", "UNDER_ASSESSMENT", "APPROVED", "SETTLED", "REPUDIATED",
)