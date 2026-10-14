#!/usr/bin/env bash
set -euo pipefail

CONNECT=http://localhost:8083
NAME=insurance-cdc
PSQL="docker exec -i insurance-postgres psql -U insurance -d insurance"
KTOPICS="docker exec insurance-kafka /opt/kafka/bin/kafka-topics.sh --bootstrap-server localhost:9092"

echo "1/6 stopping connector"
curl -sS -X PUT "$CONNECT/connectors/$NAME/stop" || true
sleep 10

echo "2/6 clearing offsets"
curl -sS -X DELETE "$CONNECT/connectors/$NAME/offsets" || true

echo "3/6 deleting connector"
curl -sS -X DELETE "$CONNECT/connectors/$NAME" || true
sleep 15

echo "4/6 dropping replication slot"
$PSQL -c "SELECT pg_drop_replication_slot('insurance_cdc_slot');" || true

echo "5/6 deleting topics"
for t in $($KTOPICS --list | grep '^insurance\.'); do
  $KTOPICS --delete --topic "$t" || true
done
sleep 20

echo "6/6 registering connector"
curl -sS -X POST -H "Content-Type: application/json" \
  --data @infrastructure/debezium/insurance-connector.json \
  "$CONNECT/connectors" > /dev/null
sleep 20
curl -sS "$CONNECT/connectors/$NAME/status"
