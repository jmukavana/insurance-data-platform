FROM flink:1.20.1-scala_2.12-java17

# Connector JARs are not shipped with Flink. Pinning exact versions here keeps
# the image reproducible; the trailing "-1.20" is the Flink minor it targets.
ARG KAFKA_CONNECTOR_VERSION=3.3.0-1.20

RUN mkdir -p /opt/flink/lib \
 && curl -fsSL -o /opt/flink/lib/flink-sql-connector-kafka.jar \
      "https://repo1.maven.org/maven2/org/apache/flink/flink-sql-connector-kafka/${KAFKA_CONNECTOR_VERSION}/flink-sql-connector-kafka-${KAFKA_CONNECTOR_VERSION}.jar"

# The checkpoint directory must exist in the image with the right ownership.
# Container runtimes copy the image path's ownership onto a fresh named volume;
# if the path is absent the volume is created root-owned and Flink (UID 9999)
# cannot write to it.
RUN mkdir -p /flink-checkpoints && chown -R flink:flink /flink-checkpoints