"""Fraud injection.

Three patterns are layered onto an already-generated book of claims. Each
mutated claim gets a ground-truth label; every untouched claim gets a negative
label, so the evaluation set is complete rather than positive-only.

Labels are returned separately and are written only to the evaluation schema.
"""

from __future__ import annotations

import dataclasses
from datetime import timedelta

import numpy as np

from .config import FraudParameters
from .domain import Claim, FraudLabel, Policy

STAGED_ACCIDENT = "STAGED_ACCIDENT_RING"
INFLATED_CLAIM = "INFLATED_CLAIM"
AGENT_COLLUSION = "AGENT_COLLUSION"


def inject_fraud(
    rng: np.random.Generator,
    claims: list[Claim],
    policies: list[Policy],
    parameters: FraudParameters,
) -> tuple[list[Claim], list[FraudLabel]]:
    """Return claims with fraud patterns applied, plus labels for every claim."""
    if not claims:
        return claims, []

    policy_by_number = {policy.policy_number: policy for policy in policies}
    mutable_claims = list(claims)
    labels_by_claim: dict[str, FraudLabel] = {}

    target_count = int(len(mutable_claims) * parameters.overall_fraud_rate)
    staged_target = int(target_count * parameters.staged_accident_share)
    inflated_target = int(target_count * parameters.inflated_claim_share)
    collusion_target = target_count - staged_target - inflated_target

    available_indices = set(range(len(mutable_claims)))

    _apply_staged_accident_rings(
        rng, mutable_claims, policy_by_number, parameters,
        available_indices, labels_by_claim, staged_target,
    )
    _apply_inflated_claims(
        rng, mutable_claims, parameters, available_indices,
        labels_by_claim, inflated_target,
    )
    _apply_agent_collusion(
        rng, mutable_claims, policy_by_number, available_indices,
        labels_by_claim, collusion_target,
    )

    labels = _complete_labels(mutable_claims, labels_by_claim)
    return mutable_claims, labels


def _apply_staged_accident_rings(
    rng: np.random.Generator,
    claims: list[Claim],
    policy_by_number: dict[str, Policy],
    parameters: FraudParameters,
    available_indices: set[int],
    labels: dict[str, FraudLabel],
    target_count: int,
) -> None:
    """Clusters of claims sharing one provider, shortly after policy inception.

    The detectable signal is the combination: same provider, tight inception
    gap, similar amounts. No single attribute is suspicious on its own.
    """
    assigned = 0
    ring_sequence = 0

    while assigned < target_count and available_indices:
        ring_size = int(rng.integers(
            parameters.staged_ring_minimum_size,
            parameters.staged_ring_maximum_size + 1,
        ))
        ring_size = min(ring_size, target_count - assigned, len(available_indices))
        if ring_size <= 0:
            break

        ring_sequence += 1
        ring_id = f"RING-{ring_sequence:04d}"
        shared_provider_index = int(rng.integers(0, 200))
        ring_amount_centre = float(rng.uniform(180_000, 900_000))

        chosen = rng.choice(
            sorted(available_indices), size=ring_size, replace=False,
        )
        for claim_index in chosen:
            claim_index = int(claim_index)
            original = claims[claim_index]
            policy = policy_by_number.get(original.policy_number)
            if policy is None:
                continue

            days_after_inception = int(rng.integers(
                1, parameters.staged_maximum_days_from_inception,
            ))
            incident_date = policy.inception_date + timedelta(days=days_after_inception)
            reporting_lag = int(rng.integers(0, 4))
            claimed_amount = float(round(
                ring_amount_centre * rng.uniform(0.88, 1.12), 2,
            ))

            claims[claim_index] = dataclasses.replace(
                original,
                provider_index=shared_provider_index,
                incident_date=incident_date,
                reported_date=incident_date + timedelta(days=reporting_lag),
                claimed_amount=min(claimed_amount, policy.sum_insured),
            )
            labels[original.claim_number] = FraudLabel(
                claim_number=original.claim_number,
                is_fraudulent=True,
                fraud_pattern=STAGED_ACCIDENT,
                ring_id=ring_id,
            )
            available_indices.discard(claim_index)
            assigned += 1


def _apply_inflated_claims(
    rng: np.random.Generator,
    claims: list[Claim],
    parameters: FraudParameters,
    available_indices: set[int],
    labels: dict[str, FraudLabel],
    target_count: int,
) -> None:
    """Genuine incidents with the loss amount exaggerated.

    Harder to detect than staged rings: only the severity is anomalous, so
    detection depends on peer comparison rather than relationship structure.
    """
    selectable = min(target_count, len(available_indices))
    if selectable <= 0:
        return

    chosen = rng.choice(sorted(available_indices), size=selectable, replace=False)
    for claim_index in chosen:
        claim_index = int(claim_index)
        original = claims[claim_index]
        multiplier = float(rng.uniform(
            parameters.inflation_multiplier_minimum,
            parameters.inflation_multiplier_maximum,
        ))

        claims[claim_index] = dataclasses.replace(
            original,
            claimed_amount=float(round(original.claimed_amount * multiplier, 2)),
        )
        labels[original.claim_number] = FraudLabel(
            claim_number=original.claim_number,
            is_fraudulent=True,
            fraud_pattern=INFLATED_CLAIM,
            ring_id=None,
        )
        available_indices.discard(claim_index)


def _apply_agent_collusion(
    rng: np.random.Generator,
    claims: list[Claim],
    policy_by_number: dict[str, Policy],
    available_indices: set[int],
    labels: dict[str, FraudLabel],
    target_count: int,
) -> None:
    """Claims concentrated on policies written by a small set of agents.

    Detectable only by aggregating claim rates per agent, which is a different
    query shape from per-claim scoring and worth having in the dataset.
    """
    if target_count <= 0 or not available_indices:
        return

    agent_indices = {
        policy.agent_index for policy in policy_by_number.values()
    }
    if not agent_indices:
        return

    colluding_agents = set(rng.choice(
        sorted(agent_indices),
        size=max(1, len(agent_indices) // 25),
        replace=False,
    ).tolist())

    candidates = [
        index for index in sorted(available_indices)
        if _policy_agent_index(claims[index], policy_by_number) in colluding_agents
    ]
    if not candidates:
        return

    selectable = min(target_count, len(candidates))
    chosen = rng.choice(candidates, size=selectable, replace=False)

    for claim_index in chosen:
        claim_index = int(claim_index)
        original = claims[claim_index]
        policy = policy_by_number[original.policy_number]

        days_after_inception = int(rng.integers(5, 60))
        incident_date = policy.inception_date + timedelta(days=days_after_inception)

        claims[claim_index] = dataclasses.replace(
            original,
            incident_date=incident_date,
            reported_date=incident_date + timedelta(days=int(rng.integers(0, 6))),
        )
        labels[original.claim_number] = FraudLabel(
            claim_number=original.claim_number,
            is_fraudulent=True,
            fraud_pattern=AGENT_COLLUSION,
            ring_id=None,
        )
        available_indices.discard(claim_index)


def _policy_agent_index(
    claim: Claim,
    policy_by_number: dict[str, Policy],
) -> int | None:
    policy = policy_by_number.get(claim.policy_number)
    return policy.agent_index if policy else None


def _complete_labels(
    claims: list[Claim],
    fraudulent_labels: dict[str, FraudLabel],
) -> list[FraudLabel]:
    """Emit a label for every claim so evaluation has true negatives too."""
    return [
        fraudulent_labels.get(
            claim.claim_number,
            FraudLabel(
                claim_number=claim.claim_number,
                is_fraudulent=False,
                fraud_pattern=None,
                ring_id=None,
            ),
        )
        for claim in claims
    ]