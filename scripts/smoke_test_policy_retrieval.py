"""Exercise semantic policy retrieval and verify every returned citation."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg
from langchain_cockroachdb import CockroachDBEngine, CockroachDBVectorStore
from langchain_openai import OpenAIEmbeddings
from psycopg.rows import dict_row

from policy_document import normalize_text, parse_policy_document


REPO_DIR = Path(__file__).resolve().parents[1]
REQUIRED_METADATA = {
    "document_title",
    "policy_key",
    "policy_version",
    "section_heading",
    "clause_key",
    "source_uri",
    "content_sha256",
    "chunk_index",
    "embedding_model",
    "embedding_dimensions",
    "return_policy_id",
    "policy_clause_id",
}
TEST_CASES = (
    ("Can I return a gift card?", "RET-EXCEPTION-001"),
    ("Does a $700 refund need manager approval?", "RET-APPROVAL-001"),
    ("Can I return an ordinary product 45 days after purchase?", "RET-ELIGIBILITY-001"),
)


def required_environment(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Required environment variable {name} is not set")
    return value


def main() -> int:
    connection_url = required_environment("CRDB_APP_URL")
    required_environment("OPENAI_API_KEY")
    model = required_environment("OPENAI_EMBEDDING_MODEL")
    dimensions = int(required_environment("OPENAI_EMBEDDING_DIMENSIONS"))
    source_uri = required_environment("POLICY_SOURCE_URI")
    table_name = required_environment("POLICY_VECTOR_TABLE")
    namespace = required_environment("POLICY_VECTOR_NAMESPACE")
    policy = parse_policy_document(REPO_DIR / source_uri)

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT
                rp.return_policy_id,
                rp.title,
                rp.policy_key,
                rp.policy_version,
                rp.source_uri,
                rp.content_sha256,
                pc.policy_clause_id,
                pc.clause_key,
                pc.clause_text
            FROM return_policies AS rp
            JOIN policy_clauses AS pc
              ON pc.return_policy_id = rp.return_policy_id
            WHERE rp.policy_key = %s
              AND rp.policy_version = %s
              AND rp.policy_status = 'active'
            ORDER BY pc.display_order
            """,
            (policy.policy_key, policy.policy_version),
        ).fetchall()

    authoritative = {row["clause_key"]: row for row in rows}
    if len(authoritative) != len(policy.sections):
        raise RuntimeError("Authoritative policy clause count is inconsistent")

    embeddings = OpenAIEmbeddings(model=model, dimensions=dimensions)
    engine = CockroachDBEngine.from_connection_string(connection_url)
    vector_store = CockroachDBVectorStore(
        engine=engine,
        embeddings=embeddings,
        collection_name=table_name,
        namespace=namespace,
    )

    for query, expected_clause in TEST_CASES:
        results = vector_store.similarity_search_with_score(query, k=3)
        if not results:
            raise RuntimeError(f"No policy results returned for query: {query}")

        returned_clauses: list[str] = []
        for document, _score in results:
            metadata = document.metadata
            if not REQUIRED_METADATA.issubset(metadata):
                raise RuntimeError("Retrieved chunk is missing citation metadata")
            clause_key = metadata["clause_key"]
            clause = authoritative.get(clause_key)
            if clause is None:
                raise RuntimeError(f"Retrieved unknown clause {clause_key}")
            if metadata["document_title"] != clause["title"]:
                raise RuntimeError(f"Title verification failed for {clause_key}")
            if metadata["policy_key"] != clause["policy_key"]:
                raise RuntimeError(f"Policy-key verification failed for {clause_key}")
            if metadata["policy_version"] != clause["policy_version"]:
                raise RuntimeError(f"Version verification failed for {clause_key}")
            if metadata["source_uri"] != clause["source_uri"]:
                raise RuntimeError(f"Source verification failed for {clause_key}")
            if metadata["content_sha256"] != policy.content_sha256:
                raise RuntimeError(f"Hash verification failed for {clause_key}")
            if normalize_text(document.page_content) != normalize_text(clause["clause_text"]):
                raise RuntimeError(f"Text verification failed for {clause_key}")
            returned_clauses.append(clause_key)

        if expected_clause not in returned_clauses:
            raise RuntimeError(
                f"Expected {expected_clause} in top 3 for {query!r}; got {returned_clauses}"
            )

        top_document, top_score = results[0]
        top = top_document.metadata
        citation = (
            f"{top['document_title']}, version {top['policy_version']}, "
            f"section '{top['section_heading']}' ({top['clause_key']})"
        )
        excerpt = top_document.page_content.split(".", 1)[0] + "."
        print(f"Query: {query}")
        print(f"Top citation: {citation}")
        print(f"Verified quote: \"{excerpt}\"")
        print(f"Distance score: {top_score:.6f}")

    print("Policy retrieval smoke test successful: 3/3 expected clauses retrieved and verified.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Policy retrieval smoke test failed: {error}", file=sys.stderr)
        raise
