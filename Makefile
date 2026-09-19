COMPOSE := docker compose
CONNECT_URL := http://localhost:8083
CONNECTOR_NAME := insurance-cdc
GENERATOR := generator/.venv/bin/insurance-generator
PSQL := docker exec -i insurance-postgres psql -U insurance -d insurance

.PHONY: core stream down clean backfill live connector-register connector-status \
        connector-delete slot-status topics consume-claims

core:
	$(COMPOSE) --profile core up -d

stream:
	$(COMPOSE) --profile core --profile stream up -d

down:
	$(COMPOSE) --profile core --profile stream down

clean:
	$(COMPOSE) --profile core --profile stream down -v

backfill:
	cd generator && insurance-generator backfill --seed 42 --customers 20000

live:
	cd generator && insurance-generator live --events-per-minute 30

connector-register:
	curl -sS -X POST -H "Content-Type: application/json" \
		--data @infrastructure/debezium/insurance-connector.json \
		$(CONNECT_URL)/connectors | jq .

connector-status:
	curl -sS $(CONNECT_URL)/connectors/$(CONNECTOR_NAME)/status | jq .

connector-delete:
	curl -sS -X DELETE $(CONNECT_URL)/connectors/$(CONNECTOR_NAME)

slot-status:
	@$(PSQL) -x -c "SELECT slot_name, active, \
		pg_size_pretty(pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)) \
		AS retained_wal FROM pg_replication_slots;"

topics:
	docker exec -it insurance-kafka /opt/kafka/bin/kafka-topics.sh \
		--bootstrap-server localhost:9092 --list

consume-claims:
	docker exec -it insurance-kafka /opt/kafka/bin/kafka-console-consumer.sh \
		--bootstrap-server localhost:9092 \
		--topic insurance.insurance.claims \
		--from-beginning --max-messages 3

sql:
	docker exec -it insurance-flink-jobmanager \
		./bin/sql-client.sh -i /opt/sql/01_sources.sql
backfill:
	$(GENERATOR) backfill --seed 42 --customers 20000

live:
	$(GENERATOR) live --events-per-minute 30

cdc-reset:
	-curl -sS -X DELETE $(CONNECT_URL)/connectors/$(CONNECTOR_NAME)
	sleep 15
	-$(PSQL) -c "SELECT pg_drop_replication_slot('insurance_cdc_slot');"
	for t in $$(docker exec insurance-kafka /opt/kafka/bin/kafka-topics.sh \
		--bootstrap-server localhost:9092 --list | grep '^insurance\.'); do \
		docker exec insurance-kafka /opt/kafka/bin/kafka-topics.sh \
			--bootstrap-server localhost:9092 --delete --topic "$$t"; done
	$(MAKE) connector-register
sql-check:
	docker exec -it insurance-flink-jobmanager \
		./bin/sql-client.sh -f /opt/sql/01_sources.sql