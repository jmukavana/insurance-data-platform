"""Domain entities for the insurance simulation.

These are plain immutable records. They carry no persistence concerns and no
sampling logic, so they can be constructed in tests without a database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Customer:
    national_id: str
    full_name: str
    date_of_birth: date
    county: str
    msisdn: str


@dataclass(frozen=True)
class Agent:
    agent_code: str
    full_name: str
    branch: str
    appointed_on: date


@dataclass(frozen=True)
class ServiceProvider:
    provider_code: str
    provider_name: str
    provider_type: str
    county: str


@dataclass(frozen=True)
class Policy:
    policy_number: str
    customer_index: int
    agent_index: int
    product_class: str
    sum_insured: float
    annual_premium: float
    inception_date: date
    expiry_date: date
    status: str


@dataclass(frozen=True)
class Endorsement:
    policy_number: str
    effective_date: date
    endorsement_type: str
    premium_delta: float
    sum_insured_delta: float


@dataclass(frozen=True)
class PremiumPayment:
    policy_number: str
    due_date: date
    paid_date: date | None
    amount_due: float
    amount_paid: float | None
    payment_channel: str | None
    status: str


@dataclass(frozen=True)
class Claim:
    claim_number: str
    policy_number: str
    provider_index: int | None
    incident_date: date
    reported_date: date
    claimed_amount: float
    settled_amount: float | None
    status: str


@dataclass(frozen=True)
class ClaimAssessment:
    claim_number: str
    assessor_index: int
    assessed_on: date
    assessed_amount: float
    recommendation: str


@dataclass(frozen=True)
class FraudLabel:
    """Ground truth. Written to the evaluation schema only."""

    claim_number: str
    is_fraudulent: bool
    fraud_pattern: str | None
    ring_id: str | None


@dataclass
class GeneratedDataset:
    """Everything one simulation run produced, ready for persistence."""

    customers: list[Customer]
    agents: list[Agent]
    service_providers: list[ServiceProvider]
    policies: list[Policy]
    endorsements: list[Endorsement]
    premium_payments: list[PremiumPayment]
    claims: list[Claim]
    assessments: list[ClaimAssessment]
    fraud_labels: list[FraudLabel]