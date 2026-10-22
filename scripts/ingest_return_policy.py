"""Embed the authoritative return policy into CockroachDB, safely and rerunnably."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import psycopg
from langchain_core.documents import Document
from langchain_cockroachdb import CockroachDBEngine, CockroachDBVectorStore
from langchain_openai import OpenAIEmbeddings
from psycopg.rows import dict_row

from policy_document import normalize_text, parse_policy_document


REPO_DIR = Path(__file__).resolve().parents[1]
ID_NAMESPACE = uuid5(NAMESPACE_URL, "product-returns/policy-chunks")
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

    if model != "text-embedding-3-small" or dimensions != 1536:
        raise RuntimeError("This schema expects text-embedding-3-small with 1,536 dimensions")
    if table_name != "policy_chunks":
        raise RuntimeError("POLICY_VECTOR_TABLE must target the reviewed policy_chunks table")

    policy = parse_policy_document(REPO_DIR / source_uri)
    expected_namespace = f"{policy.policy_key}:{policy.policy_version}"
    if namespace != expected_namespace:
        raise RuntimeError(
            f"POLICY_VECTOR_NAMESPACE must be {expected_namespace!r} for this document"
        )

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT
                rp.return_policy_id,
                rp.title,
                rp.source_uri,
                rp.content_sha256,
                pc.policy_clause_id,
                pc.clause_key,
                pc.clause_text,
                pc.display_order
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

    if len(rows) != len(policy.sections):
        raise RuntimeError(
            f"Document has {len(policy.sections)} sections but database has {len(rows)} clauses"
        )

    database_by_clause = {row["clause_key"]: row for row in rows}
    documents: list[Document] = []
    ids: list[str] = []

    for section in policy.sections:
        row = database_by_clause.get(section.clause_key)
        if row is None:
            raise RuntimeError(f"Clause {section.clause_key} is absent from CockroachDB")
        if row["title"] != policy.title:
            raise RuntimeError(f"Title mismatch for clause {section.clause_key}")
        if row["source_uri"] != source_uri:
            raise RuntimeError(f"Source URI mismatch for clause {section.clause_key}")
        if row["content_sha256"] != policy.content_sha256:
            raise RuntimeError(f"Source hash mismatch for clause {section.clause_key}")
        if normalize_text(row["clause_text"]) != section.text:
            raise RuntimeError(f"Authoritative text mismatch for clause {section.clause_key}")

        chunk_id = str(
            uuid5(
                ID_NAMESPACE,
                f"{policy.policy_key}:{policy.policy_version}:{section.clause_key}:0",
            )
        )
        metadata = {
            "document_title": policy.title,
            "policy_key": policy.policy_key,
            "policy_version": policy.policy_version,
            "section_heading": section.heading,
            "clause_key": section.clause_key,
            "source_uri": source_uri,
            "content_sha256": policy.content_sha256,
            "chunk_index": section.chunk_index,
            "embedding_model": model,
            "embedding_dimensions": dimensions,
            "return_policy_id": str(row["return_policy_id"]),
            "policy_clause_id": str(row["policy_clause_id"]),
        }
        if set(metadata) != REQUIRED_METADATA:
            raise RuntimeError(f"Unexpected metadata shape for clause {section.clause_key}")
        ids.append(chunk_id)
        documents.append(Document(id=chunk_id, page_content=section.text, metadata=metadata))

    embeddings = OpenAIEmbeddings(model=model, dimensions=dimensions)
    engine = CockroachDBEngine.from_connection_string(connection_url)
    vector_store = CockroachDBVectorStore(
        engine=engine,
        embeddings=embeddings,
        collection_name=table_name,
        namespace=namespace,
    )

    written_ids = vector_store.add_documents(documents, ids=ids)
    if set(written_ids) != set(ids):
        raise RuntimeError("Vector store did not report the expected deterministic IDs")

    with psycopg.connect(connection_url, row_factory=dict_row) as connection:
        stored_rows = connection.execute(
            """
            SELECT id, content, metadata
            FROM policy_chunks
            WHERE namespace = %s
            ORDER BY id
            """,
            (namespace,),
        ).fetchall()

    desired_ids = set(ids)
    stale_ids = [str(row["id"]) for row in stored_rows if str(row["id"]) not in desired_ids]
    if stale_ids:
        vector_store.delete(ids=stale_ids)
        with psycopg.connect(connection_url, row_factory=dict_row) as connection:
            stored_rows = connection.execute(
                """
                SELECT id, content, metadata
                FROM policy_chunks
                WHERE namespace = %s
                ORDER BY id
                """,
                (namespace,),
            ).fetchall()

    if len(stored_rows) != len(documents):
        raise RuntimeError(
            f"Expected {len(documents)} stored chunks but found {len(stored_rows)}"
        )
    for row in stored_rows:
        metadata = row["metadata"]
        if not REQUIRED_METADATA.issubset(metadata):
            raise RuntimeError(f"Stored chunk {row['id']} is missing citation metadata")
        clause = database_by_clause.get(metadata["clause_key"])
        if clause is None or normalize_text(row["content"]) != normalize_text(
            clause["clause_text"]
        ):
            raise RuntimeError(f"Stored chunk {row['id']} failed clause verification")

    print(
        f"Policy ingestion successful: {len(stored_rows)} verified chunks, "
        f"namespace={namespace}, model={model}, dimensions={dimensions}."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Policy ingestion failed: {error}", file=sys.stderr)
        raise
