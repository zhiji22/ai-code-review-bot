"""Initial schema: all tables per DESIGN.md §5.

Revision ID: 0001
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Enable pgvector extension (idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")  # for text search

    # ---------- users ----------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("github_access_token", sa.Text(), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("company", sa.String(length=255), nullable=True),
        sa.Column("location", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_github_id", "users", ["github_id"], unique=True)
    op.create_index("ix_users_username", "users", ["username"], unique=True)

    # ---------- repositories ----------
    op.create_table(
        "repositories",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("github_repo_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("owner", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=64), nullable=True),
        sa.Column("default_branch", sa.String(length=255), nullable=True),
        sa.Column("is_private", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("webhook_secret", sa.LargeBinary(), nullable=True),
        sa.Column("encryption_key_id", sa.String(length=128), nullable=True),
        sa.Column("installation_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("last_review_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_reviews", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_repositories_github_repo_id", "repositories", ["github_repo_id"], unique=True)
    op.create_index("ix_repositories_full_name", "repositories", ["full_name"], unique=True)
    op.create_index("ix_repositories_owner", "repositories", ["owner"])
    op.create_index("ix_repositories_is_active", "repositories", ["is_active"])

    # ---------- rules ----------
    op.create_table(
        "rules",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("pattern", sa.Text(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("languages", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_builtin", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_rules_rule_id", "rules", ["rule_id"], unique=True)
    op.create_index("ix_rules_category", "rules", ["category"])
    op.create_index("ix_rules_repository_id", "rules", ["repository_id"])

    # ---------- reviews ----------
    op.create_table(
        "reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("pr_number", sa.Integer(), nullable=False),
        sa.Column("commit_sha", sa.String(length=40), nullable=False),
        sa.Column("pr_title", sa.Text(), nullable=True),
        sa.Column("pr_author", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("trigger", sa.String(length=32), nullable=False, server_default=sa.text("'webhook'")),
        sa.Column("overall_score", sa.Float(), nullable=True),
        sa.Column("security_score", sa.Float(), nullable=True),
        sa.Column("performance_score", sa.Float(), nullable=True),
        sa.Column("maintainability_score", sa.Float(), nullable=True),
        sa.Column("files_reviewed", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("files_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("lines_of_code", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("additions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("deletions", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("critical_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("info_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_model", sa.String(length=64), nullable=True),
        sa.Column("llm_tokens_prompt", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_tokens_completion", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_tokens_total", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("llm_cost_usd", sa.Numeric(precision=10, scale=6), nullable=False, server_default=sa.text("0")),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("pr_comment_posted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("inline_comments_posted", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("raw_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reviews_repository_id", "reviews", ["repository_id"])
    op.create_index("ix_reviews_repo_pr", "reviews", ["repository_id", "pr_number"])
    op.create_index("ix_reviews_repo_pr_sha", "reviews", ["repository_id", "pr_number", "commit_sha"])
    op.create_index("ix_reviews_status_created", "reviews", ["status", "created_at"])

    # ---------- review_comments ----------
    op.create_table(
        "review_comments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("suggestion", sa.Text(), nullable=True),
        sa.Column("rule_id", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default=sa.text("1.0")),
        sa.Column("issue_type", sa.String(length=64), nullable=True),
        sa.Column("matched_text", sa.Text(), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_review_comments_review_id", "review_comments", ["review_id"])
    op.create_index("ix_review_comments_file_path", "review_comments", ["file_path"])
    op.create_index("ix_review_comments_severity", "review_comments", ["severity"])
    op.create_index("ix_review_comments_rule_id", "review_comments", ["rule_id"])
    op.create_index("ix_review_comments_review_severity", "review_comments", ["review_id", "severity"])
    op.create_index("ix_review_comments_review_file", "review_comments", ["review_id", "file_path"])

    # ---------- llm_usage ----------
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("review_id", sa.BigInteger(), nullable=True),
        sa.Column("repository_id", sa.BigInteger(), nullable=True),
        sa.Column("model", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False, server_default=sa.text("'openai'")),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=False, server_default=sa.text("0")),
        sa.Column("cached", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("file_path", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("request_meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["review_id"], ["reviews.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_review_id", "llm_usage", ["review_id"])
    op.create_index("ix_llm_usage_repository_id", "llm_usage", ["repository_id"])
    op.create_index("ix_llm_usage_model", "llm_usage", ["model"])

    # ---------- code_embeddings ----------
    op.create_table(
        "code_embeddings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("chunk_hash", sa.String(length=64), nullable=False),
        sa.Column("embedding", sa.Text(), nullable=True),  # Will be vector(1536) when pgvector active
        sa.Column("metadata_", postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["repository_id"], ["repositories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_code_embeddings_repository_id", "code_embeddings", ["repository_id"])
    op.create_index("ix_code_embeddings_file_path", "code_embeddings", ["file_path"])
    op.create_index("ix_code_embeddings_chunk_hash", "code_embeddings", ["chunk_hash"])

    # Convert embedding column to vector type if pgvector is available
    op.execute("ALTER TABLE code_embeddings ALTER COLUMN embedding TYPE vector(1536) USING NULL")

    # ---------- updated_at triggers for all tables ----------
    for table in (
        "users",
        "repositories",
        "rules",
        "reviews",
        "review_comments",
        "llm_usage",
        "code_embeddings",
    ):
        op.execute(
            f"""
            CREATE OR REPLACE FUNCTION update_updated_at_{table}()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ language 'plpgsql';
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER update_updated_at_{table}
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_{table}();
            """
        )


def downgrade() -> None:
    for table in (
        "code_embeddings",
        "llm_usage",
        "review_comments",
        "reviews",
        "rules",
        "repositories",
        "users",
    ):
        op.execute(f"DROP TRIGGER IF EXISTS update_updated_at_{table} ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS update_updated_at_{table}()")
        op.drop_table(table)
