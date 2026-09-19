"""Command line entry point.

    backfill  load a full synthetic history into Postgres
    live      drip new claims and status changes for CDC to pick up
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import sys
import time
from datetime import date, timedelta

import psycopg

from .config import SimulationConfig
from .repository import open_connection, persist
from .simulation import simulate

DEFAULT_DSN = "postgresql://insurance:insurance@localhost:5436/insurance"
LIVE_CLAIM_STATUSES = ("UNDER_ASSESSMENT", "APPROVED", "SETTLED", "REPUDIATED")

logger = logging.getLogger("insurance_generator")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        return arguments.handler(arguments)
    except psycopg.Error as error:
        logger.error("Database error: %s", error)
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted")
        return 130


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="insurance-generator")
    subparsers = parser.add_subparsers(required=True)

    backfill = subparsers.add_parser(
        "backfill", help="generate and load a full synthetic history",
    )
    backfill.add_argument("--dsn", default=os.getenv("POSTGRES_DSN", DEFAULT_DSN))
    backfill.add_argument("--seed", type=int, default=42)
    backfill.add_argument("--customers", type=int, default=20_000)
    backfill.set_defaults(handler=_run_backfill)

    live = subparsers.add_parser(
        "live", help="continuously emit new claims and status transitions",
    )
    live.add_argument("--dsn", default=os.getenv("POSTGRES_DSN", DEFAULT_DSN))
    live.add_argument("--events-per-minute", type=int, default=30)
    live.set_defaults(handler=_run_live)

    return parser


def _run_backfill(arguments: argparse.Namespace) -> int:
    config = SimulationConfig(seed=arguments.seed, customer_count=arguments.customers)

    logger.info("Simulating with seed %d", config.seed)
    started_at = time.monotonic()
    dataset = simulate(config)
    logger.info("Simulation finished in %.1fs", time.monotonic() - started_at)

    with open_connection(arguments.dsn) as connection:
        persist(connection, dataset)

    fraud_count = sum(1 for label in dataset.fraud_labels if label.is_fraudulent)
    logger.info(
        "Fraud rate in loaded data: %.2f%%",
        100.0 * fraud_count / max(len(dataset.fraud_labels), 1),
    )
    return 0


def _run_live(arguments: argparse.Namespace) -> int:
    """Emit ongoing INSERTs and UPDATEs so the WAL keeps producing events."""
    interval_seconds = 60.0 / max(arguments.events_per_minute, 1)
    logger.info("Emitting roughly %d events/minute", arguments.events_per_minute)

    with psycopg.connect(arguments.dsn, autocommit=True) as connection:
        while True:
            if random.random() < 0.6:
                _insert_new_claim(connection)
            else:
                _advance_random_claim(connection)
            time.sleep(interval_seconds)


def _insert_new_claim(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO insurance.claims (
                claim_number, policy_id, provider_id, incident_date,
                reported_date, claimed_amount, status
            )
            SELECT
                'CLM-LIVE-' || nextval('insurance.claims_claim_id_seq'),
                p.policy_id,
                (SELECT provider_id FROM insurance.service_providers
                 ORDER BY random() LIMIT 1),
                %(incident_date)s,
                CURRENT_DATE,
                round((random() * 0.4 + 0.02) * p.sum_insured, 2),
                'REPORTED'
            FROM insurance.policies p
            WHERE p.status = 'ACTIVE'
            ORDER BY random()
            LIMIT 1
            """,
            {"incident_date": date.today() - timedelta(days=random.randint(0, 30))},
        )


def _advance_random_claim(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE insurance.claims
            SET status = %(status)s,
                updated_at = now(),
                settled_amount = CASE
                    WHEN %(status)s = 'SETTLED'
                    THEN round(claimed_amount * 0.85, 2)
                    ELSE settled_amount
                END
            WHERE claim_id = (
                SELECT claim_id FROM insurance.claims
                WHERE status IN ('REPORTED', 'UNDER_ASSESSMENT', 'APPROVED')
                ORDER BY random() LIMIT 1
            )
            """,
            {"status": random.choice(LIVE_CLAIM_STATUSES)},
        )


if __name__ == "__main__":
    sys.exit(main())