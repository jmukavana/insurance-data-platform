"""Lifecycle simulation.

Builds a book of business across the configured history window: parties first,
then policies, then the payment schedule and claims each policy produces.
Fraud is layered on afterwards by the fraud module.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from . import actuarial
from .config import (
    CLAIM_STATUSES,
    COUNTIES,
    COUNTY_WEIGHTS,
    PAYMENT_CHANNELS,
    PRODUCT_CLASS_WEIGHTS,
    PRODUCT_CLASSES,
    PROVIDER_TYPES,
    ProductClassParameters,
    SimulationConfig,
)
from .domain import (
    Agent,
    Claim,
    ClaimAssessment,
    Customer,
    Endorsement,
    GeneratedDataset,
    Policy,
    PremiumPayment,
    ServiceProvider,
)
from .fraud import inject_fraud

FIRST_NAMES = (
    "Amina", "Brian", "Cynthia", "David", "Esther", "Felix", "Grace", "Hassan",
    "Irene", "James", "Kevin", "Lydia", "Moses", "Nancy", "Oscar", "Purity",
    "Robert", "Sarah", "Timothy", "Valerie", "Wycliffe", "Zipporah",
)

LAST_NAMES = (
    "Wanjiku", "Otieno", "Mutiso", "Kiprop", "Achieng", "Njoroge", "Wafula",
    "Chelimo", "Kamau", "Odhiambo", "Mwangi", "Barasa", "Cheruiyot", "Nyambura",
    "Omondi", "Kirui", "Wekesa", "Muthoni",
)

BRANCHES = (
    "Nairobi CBD", "Westlands", "Mombasa Road", "Nakuru", "Kisumu", "Eldoret",
    "Thika", "Nyeri",
)

MONTHS_PER_PAYMENT_INTERVAL = 3
PAYMENTS_PER_YEAR = 4
POLICY_TERM_DAYS = 365
ASSESSMENT_PROBABILITY = 0.72


def simulate(config: SimulationConfig) -> GeneratedDataset:
    """Run one full reproducible simulation."""
    rng = np.random.default_rng(config.seed)

    customers = _build_customers(rng, config)
    agents = _build_agents(rng, config)
    providers = _build_service_providers(rng, config)

    policies, endorsements, payments = _build_policies(rng, config, customers, agents)
    claims, assessments = _build_claims(rng, config, policies, providers)

    claims, fraud_labels = inject_fraud(rng, claims, policies, config.fraud)

    return GeneratedDataset(
        customers=customers,
        agents=agents,
        service_providers=providers,
        policies=policies,
        endorsements=endorsements,
        premium_payments=payments,
        claims=claims,
        assessments=assessments,
        fraud_labels=fraud_labels,
    )


def _build_customers(
    rng: np.random.Generator,
    config: SimulationConfig,
) -> list[Customer]:
    counties = rng.choice(COUNTIES, size=config.customer_count, p=COUNTY_WEIGHTS)
    birth_years = rng.integers(1960, 2005, size=config.customer_count)

    return [
        Customer(
            national_id=f"{20_000_000 + index:08d}",
            full_name=_random_full_name(rng),
            date_of_birth=date(int(birth_years[index]), 1, 1)
            + timedelta(days=int(rng.integers(0, 364))),
            county=str(counties[index]),
            msisdn=f"2547{rng.integers(10_000_000, 99_999_999)}",
        )
        for index in range(config.customer_count)
    ]


def _build_agents(rng: np.random.Generator, config: SimulationConfig) -> list[Agent]:
    return [
        Agent(
            agent_code=f"AGT-{index + 1:04d}",
            full_name=_random_full_name(rng),
            branch=str(rng.choice(BRANCHES)),
            appointed_on=config.history_start
            - timedelta(days=int(rng.integers(30, 2_000))),
        )
        for index in range(config.agent_count)
    ]


def _build_service_providers(
    rng: np.random.Generator,
    config: SimulationConfig,
) -> list[ServiceProvider]:
    counties = rng.choice(
        COUNTIES, size=config.service_provider_count, p=COUNTY_WEIGHTS,
    )
    types = rng.choice(PROVIDER_TYPES, size=config.service_provider_count)

    return [
        ServiceProvider(
            provider_code=f"SPV-{index + 1:05d}",
            provider_name=f"{rng.choice(LAST_NAMES)} {str(types[index]).title()} Services",
            provider_type=str(types[index]),
            county=str(counties[index]),
        )
        for index in range(config.service_provider_count)
    ]


def _build_policies(
    rng: np.random.Generator,
    config: SimulationConfig,
    customers: list[Customer],
    agents: list[Agent],
) -> tuple[list[Policy], list[Endorsement], list[PremiumPayment]]:
    policies: list[Policy] = []
    endorsements: list[Endorsement] = []
    payments: list[PremiumPayment] = []

    history_days = (config.history_end - config.history_start).days
    policy_sequence = 0

    for customer_index in range(len(customers)):
        policy_count = 1 + int(rng.poisson(config.policies_per_customer_mean - 1))

        for _ in range(policy_count):
            policy_sequence += 1
            product = _choose_product_class(rng)
            inception = config.history_start + timedelta(
                days=int(rng.integers(0, history_days)),
            )
            expiry = inception + timedelta(days=POLICY_TERM_DAYS)
            sum_insured = actuarial.sample_sum_insured(rng, product)
            annual_premium = actuarial.calculate_annual_premium(
                rng, product, sum_insured,
            )

            policy = Policy(
                policy_number=f"POL-{policy_sequence:07d}",
                customer_index=customer_index,
                agent_index=int(rng.integers(0, len(agents))),
                product_class=product.name,
                sum_insured=sum_insured,
                annual_premium=annual_premium,
                inception_date=inception,
                expiry_date=expiry,
                status=_derive_policy_status(rng, config, expiry),
            )
            policies.append(policy)

            payments.extend(_build_payment_schedule(rng, config, policy))
            endorsement = _maybe_build_endorsement(rng, config, policy)
            if endorsement is not None:
                endorsements.append(endorsement)

    return policies, endorsements, payments


def _build_payment_schedule(
    rng: np.random.Generator,
    config: SimulationConfig,
    policy: Policy,
) -> list[PremiumPayment]:
    """Quarterly instalments, some of which are missed or paid late."""
    instalment = round(policy.annual_premium / PAYMENTS_PER_YEAR, 2)
    schedule: list[PremiumPayment] = []

    for instalment_index in range(PAYMENTS_PER_YEAR):
        due_date = policy.inception_date + timedelta(
            days=int(instalment_index * MONTHS_PER_PAYMENT_INTERVAL * 30),
        )
        if due_date > config.history_end:
            break

        is_missed = rng.random() < config.lapse_probability
        if is_missed:
            schedule.append(PremiumPayment(
                policy_number=policy.policy_number,
                due_date=due_date,
                paid_date=None,
                amount_due=instalment,
                amount_paid=None,
                payment_channel=None,
                status="OVERDUE",
            ))
            continue

        days_late = max(0, int(rng.normal(2, 6)))
        paid_date = due_date + timedelta(days=days_late)
        schedule.append(PremiumPayment(
            policy_number=policy.policy_number,
            due_date=due_date,
            paid_date=min(paid_date, config.history_end),
            amount_due=instalment,
            amount_paid=instalment,
            payment_channel=str(rng.choice(PAYMENT_CHANNELS)),
            status="PAID" if days_late <= 7 else "PAID_LATE",
        ))

    return schedule


def _maybe_build_endorsement(
    rng: np.random.Generator,
    config: SimulationConfig,
    policy: Policy,
) -> Endorsement | None:
    if rng.random() >= config.endorsement_probability:
        return None

    sum_insured_delta = float(round(policy.sum_insured * rng.uniform(-0.2, 0.35), 2))
    premium_delta = float(round(sum_insured_delta * 0.05, 2))
    effective_date = policy.inception_date + timedelta(
        days=int(rng.integers(30, POLICY_TERM_DAYS - 30)),
    )

    return Endorsement(
        policy_number=policy.policy_number,
        effective_date=min(effective_date, config.history_end),
        endorsement_type="SUM_INSURED_ADJUSTMENT",
        premium_delta=premium_delta,
        sum_insured_delta=sum_insured_delta,
    )


def _build_claims(
    rng: np.random.Generator,
    config: SimulationConfig,
    policies: list[Policy],
    providers: list[ServiceProvider],
) -> tuple[list[Claim], list[ClaimAssessment]]:
    claims: list[Claim] = []
    assessments: list[ClaimAssessment] = []
    claim_sequence = 0

    for policy in policies:
        product = _product_by_name(policy.product_class)
        coverage_end = min(policy.expiry_date, config.history_end)
        years_on_risk = actuarial.exposure_years(policy.inception_date, coverage_end)
        claim_count = actuarial.sample_claim_count(rng, product, years_on_risk)

        for _ in range(claim_count):
            claim_sequence += 1
            incident_date = actuarial.sample_incident_date(
                rng, policy.inception_date, coverage_end,
            )
            reported_date = incident_date + timedelta(
                days=actuarial.sample_reporting_lag_days(rng, product),
            )
            if reported_date > config.history_end:
                continue

            claimed_amount = actuarial.sample_claim_severity(
                rng, product, policy.sum_insured,
            )
            status = _derive_claim_status(rng, reported_date, config.history_end)

            claim = Claim(
                claim_number=f"CLM-{claim_sequence:07d}",
                policy_number=policy.policy_number,
                provider_index=int(rng.integers(0, len(providers))),
                incident_date=incident_date,
                reported_date=reported_date,
                claimed_amount=round(claimed_amount, 2),
                settled_amount=(
                    round(claimed_amount * float(rng.uniform(0.72, 1.0)), 2)
                    if status == "SETTLED" else None
                ),
                status=status,
            )
            claims.append(claim)

            assessment = _maybe_build_assessment(rng, claim, providers)
            if assessment is not None:
                assessments.append(assessment)

    return claims, assessments


def _maybe_build_assessment(
    rng: np.random.Generator,
    claim: Claim,
    providers: list[ServiceProvider],
) -> ClaimAssessment | None:
    if rng.random() >= ASSESSMENT_PROBABILITY:
        return None

    return ClaimAssessment(
        claim_number=claim.claim_number,
        assessor_index=int(rng.integers(0, len(providers))),
        assessed_on=claim.reported_date + timedelta(days=int(rng.integers(1, 21))),
        assessed_amount=round(claim.claimed_amount * float(rng.uniform(0.6, 1.02)), 2),
        recommendation=str(rng.choice(
            ("APPROVE", "APPROVE", "APPROVE", "PARTIAL", "DECLINE"),
        )),
    )


def _choose_product_class(rng: np.random.Generator) -> ProductClassParameters:
    chosen_index = int(rng.choice(len(PRODUCT_CLASSES), p=PRODUCT_CLASS_WEIGHTS))
    return PRODUCT_CLASSES[chosen_index]


def _product_by_name(name: str) -> ProductClassParameters:
    for product in PRODUCT_CLASSES:
        if product.name == name:
            return product
    raise ValueError(f"Unknown product class: {name}")


def _derive_policy_status(
    rng: np.random.Generator,
    config: SimulationConfig,
    expiry_date: date,
) -> str:
    if expiry_date < config.history_end:
        return "EXPIRED"
    if rng.random() < config.lapse_probability:
        return "LAPSED"
    return "ACTIVE"


def _derive_claim_status(
    rng: np.random.Generator,
    reported_date: date,
    as_of: date,
) -> str:
    days_open = (as_of - reported_date).days
    if days_open < 7:
        return "REPORTED"
    if days_open < 21:
        return str(rng.choice(("UNDER_ASSESSMENT", "REPORTED")))
    if days_open < 60:
        return str(rng.choice(("APPROVED", "UNDER_ASSESSMENT", "REPUDIATED")))
    return str(rng.choice(
        CLAIM_STATUSES, p=(0.02, 0.05, 0.10, 0.75, 0.08),
    ))


def _random_full_name(rng: np.random.Generator) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"