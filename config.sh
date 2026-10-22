export CRDB_HOST='nollen-langgraph-demo-35081.j77.cockroachlabs.cloud'
export CRDB_PORT='26257'
export CRDB_DATABASE='product_returns'
export CRDB_APP_USER='product_returns_app'
export CRDB_SSLMODE='verify-full'
export CRDB_SSLROOTCERT='/etc/pki/tls/certs/ca-bundle.crt'

export OPENAI_EMBEDDING_MODEL='text-embedding-3-small'
export OPENAI_EMBEDDING_DIMENSIONS='1536'
export OPENAI_CLASSIFIER_MODEL='gpt-6-luna'
export OPENAI_CLASSIFIER_REASONING_EFFORT='none'
export OTEL_SERVICE_NAME='product-returns'
export OTEL_EXPORTER_OTLP_PROTOCOL='http/protobuf'
export OTEL_EXPORTER_OTLP_ENDPOINT='http://127.0.0.1:4318'
export PRODUCT_RETURNS_OTLP_ENABLED='true'
export PROMETHEUS_METRICS_PORT='8000'
export PROMETHEUS_URL='http://127.0.0.1:9091'
export PROMETHEUS_SCRAPE_TIMEOUT_SECONDS='30'
export PRODUCT_RETURNS_LOG_FILE='/home/ec2-user/.local/state/product-returns/logs/events.jsonl'
export EXPECTED_GRAPH_VERSION='8'
export WORKFLOW_LEASE_DURATION_SECONDS='30'
export WORKFLOW_HEARTBEAT_INTERVAL_SECONDS='10'
export POLICY_SOURCE_URI='policies/standard-return-policy-v1.md'
export POLICY_VECTOR_TABLE='policy_chunks'
export POLICY_VECTOR_NAMESPACE='standard-returns:1.0'

export CRDB_RON_URL="postgresql://ron:${CRDB_RON_PASSWORD_URLENCODED}@${CRDB_HOST}:${CRDB_PORT}/${CRDB_DATABASE}?sslmode=${CRDB_SSLMODE}&sslrootcert=${CRDB_SSLROOTCERT}"
export CRDB_RON_ADMIN_URL="postgresql://ron:${CRDB_RON_PASSWORD_URLENCODED}@${CRDB_HOST}:${CRDB_PORT}/defaultdb?sslmode=${CRDB_SSLMODE}&sslrootcert=${CRDB_SSLROOTCERT}"

export CRDB_APP_URL="postgresql://${CRDB_APP_USER}:${CRDB_APP_PASSWORD_URLENCODED}@${CRDB_HOST}:${CRDB_PORT}/${CRDB_DATABASE}?sslmode=${CRDB_SSLMODE}&sslrootcert=${CRDB_SSLROOTCERT}"
