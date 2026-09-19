"""Postgres persistence.

Bulk loading uses COPY rather than INSERT. At a few million rows the difference
is minutes versus hours, and COPY also generates far less WAL noise before
Debezium is attached.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Iterator, Sequence

import psycopg

from .domain import GeneratedDataset

logger = logging.getLogger(__name__)

TRUNCATE_STATEMENT = """
TRUNCATE
    insurance.claim_assessments,
    insurance.claims,
    insurance.premium_payments,
    insurance.endorsements,
    insurance.policies,
    insurance.service_providers,
    insurance.agents,
    insurance.customers,
    evaluation.fraud_labels
RESTART IDENTITY CASCADE
"""


@contextmanager
def open_connection(dsn: str) -> Iterator[psycopg.Connection]:
    """Yield a transactional connection, rolling back on any failure."""
    connection = psycopg.connect(dsn)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def persist(connection: psycopg.Connection, dataset: GeneratedDataset) -> None:
    """Load a full generated dataset, replacing whatever is there."""
    with connection.cursor() as cursor:
        cursor.execute(TRUNCATE_STATEMENT)

    _copy_customers(connection, dataset)
    _copy_agents(connection, dataset)
    _copy_service_providers(connection, dataset)

    policy_ids = _copy_policies(connection, dataset)
    _copy_endorsements(connection, dataset, policy_ids)
    _copy_premium_payments(connection, dataset, policy_ids)

    claim_ids = _copy_claims(connection, dataset, policy_ids)
    _copy_assessments(connection, dataset, claim_ids)
    _copy_fraud_labels(connection, dataset)

    logger.info(
        "Loaded %d policies, %d claims, %d fraud labels",
        len(dataset.policies), len(dataset.claims), len(dataset.fraud_labels),
    )


def _copy_rows(
    connection: psycopg.Connection,
    table: str,
    columns: Sequence[str],
    rows: Iterator[tuple],
) -> None:
    column_list = ", ".join(columns)
    statement = f"COPY {table} ({column_list}) FROM STDIN"
    with connection.cursor() as cursor, cursor.copy(statement) as copy:
        for row in rows:
            copy.write_row(row)


def _copy_customers(connection: psycopg.Connection, dataset: GeneratedDataset) -> None:
    _copy_rows(
        connection,
        "insurance.customers",
        ("national_id", "full_name", "date_of_birth", "county", "msisdn"),
        (
            (c.national_id, c.full_name, c.date_of_birth, c.county, c.msisdn)
            for c in dataset.customers
        ),
    )


def _copy_agents(connection: psycopg.Connection, dataset: GeneratedDataset) -> None:
    _copy_rows(
        connection,
        "insurance.agents",
        ("agent_code", "full_name", "branch", "appointed_on"),
        (
            (a.agent_code, a.full_name, a.branch, a.appointed_on)
            for a in dataset.agents
        ),
    )


def _copy_service_providers(
    connection: psycopg.Connection,
    dataset: GeneratedDataset,
) -> None:
    _copy_rows(
        connection,
        "insurance.service_providers",
        ("provider_code", "provider_name", "provider_type", "county"),
        (
            (p.provider_code, p.provider_name, p.provider_type, p.county)
            for p in dataset.service_providers
        ),
    )


def _copy_policies(
    connection: psycopg.Connection,
    dataset: GeneratedDataset,
) -> dict[str, int]:
    customer_ids = _fetch_surrogate_keys(
        connection, "insurance.customers", "national_id", "customer_id",
    )
    agent_ids = _fetch_surrogate_keys(
        connection, "insurance.agents", "agent_code", "agent_id",
    )

    def rows() -> Iterator[tuple]:
        for policy in dataset.policies:
            customer = dataset.customers[policy.customer_index]
            agent = dataset.agents[policy.agent_index]
            yield (
                policy.policy_number,
                customer_ids[customer.national_id],
                agent_ids[agent.agent_code],
                policy.product_class,
                policy.sum_insured,
                policy.annual_premium,
                policy.inception_date,
                policy.expiry_date,
                policy.status,
            )

    _copy_rows(
        connection,
        "insurance.policies",
        (
            "policy_number", "customer_id", "agent_id", "product_class",
            "sum_insured", "annual_premium", "inception_date", "expiry_date",
            "status",
        ),
        rows(),
    )
    return _fetch_surrogate_keys(
        connection, "insurance.policies", "policy_number", "policy_id",
    )


def _copy_endorsements(
    connection: psycopg.Connection,
    dataset: GeneratedDataset,
    policy_ids: dict[str, int],
) -> None:
    _copy_rows(
        connection,
        "insurance.endorsements",
        (
            "policy_id", "effective_date", "endorsement_type",
            "premium_delta", "sum_insured_delta",
        ),
        (
            (
                policy_ids[e.policy_number], e.effective_date, e.endorsement_type,
                e.premium_delta, e.sum_insured_delta,
            )
            for e in dataset.endorsements
        ),
    )


def _copy_premium_payments(
    connection: psycopg.Connection,
    dataset: GeneratedDataset,
    policy_ids: dict[str, int],
) -> None:
    _copy_rows(
        connection,
        "insurance.premium_payments",
        (
            "policy_id", "due_date", "paid_date", "amount_due",
            "amount_paid", "payment_channel", "status",
        ),
        (
            (
                policy_ids[p.policy_number], p.due_date, p.paid_date,
                p.amount_due, p.amount_paid, p.payment_channel, p.status,
            )
            for p in dataset.premium_payments
        ),
    )


def _copy_claims(
    connection: psycopg.Connection,
    dataset: GeneratedDataset,
    policy_ids: dict[str, int],
) -> dict[str, int]:
    provider_ids = _fetch_surrogate_keys(
        connection, "insurance.service_providers", "provider_code", "provider_id",
    )
    provider_id_by_index = [
        provider_ids[provider.provider_code]
        for provider in dataset.service_providers
    ]

    def resolve_provider(index: int | None) -> int | None:
        if index is None:
            return None
        return provider_id_by_index[index % len(provider_id_by_index)]

    _copy_rows(
        connection,
        "insurance.claims",
        (
            "claim_number", "policy_id", "provider_id", "incident_date",
            "reported_date", "claimed_amount", "settled_amount", "status",
        ),
        (
            (
                c.claim_number, policy_ids[c.policy_number],
                resolve_provider(c.provider_index), c.incident_date,
                c.reported_date, c.claimed_amount, c.settled_amount, c.status,
            )
            for c in dataset.claims
        ),
    )
    return _fetch_surrogate_keys(
        connection, "insurance.claims", "claim_number", "claim_id",
    )


def _copy_assessments(
    connection: psycopg.Connection,
    dataset: GeneratedDataset,
    claim_ids: dict[str, int],
) -> None:
    provider_ids = _fetch_surrogate_keys(
        connection, "insurance.service_providers", "provider_code", "provider_id",
    )
    provider_id_by_index = [
        provider_ids[provider.provider_code]
        for provider in dataset.service_providers
    ]

    _copy_rows(
        connection,
        "insurance.claim_assessments",
        (
            "claim_id", "assessor_id", "assessed_on",
            "assessed_amount", "recommendation",
        ),
        (
            (
                claim_ids[a.claim_number],
                provider_id_by_index[a.assessor_index % len(provider_id_by_index)],
                a.assessed_on, a.assessed_amount, a.recommendation,
            )
            for a in dataset.assessments
        ),
    )


def _copy_fraud_labels(
    connection: psycopg.Connection,
    dataset: GeneratedDataset,
) -> None:
    _copy_rows(
        connection,
        "evaluation.fraud_labels",
        ("claim_number", "is_fraudulent", "fraud_pattern", "ring_id"),
        (
            (l.claim_number, l.is_fraudulent, l.fraud_pattern, l.ring_id)
            for l in dataset.fraud_labels
        ),
    )


def _fetch_surrogate_keys(
    connection: psycopg.Connection,
    table: str,
    natural_key: str,
    surrogate_key: str,
) -> dict[str, int]:
    """Map natural business keys to database-assigned identifiers."""
    with connection.cursor() as cursor:
        cursor.execute(f"SELECT {natural_key}, {surrogate_key} FROM {table}")
        return {row[0]: row[1] for row in cursor.fetchall()}