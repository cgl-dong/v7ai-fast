"""add skill system columns and table

Revision ID: 202606220002
Revises: 202606220001
Create Date: 2026-06-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "202606220002"
down_revision: Union[str, None] = "202606220001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add columns to knowledge_files (if not exist)
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)
    existing_cols = {c["name"] for c in inspector.get_columns("knowledge_files")}

    if "source_file_id" not in existing_cols:
        op.add_column(
            "knowledge_files",
            sa.Column("source_file_id", sa.Integer(),
                      sa.ForeignKey("knowledge_files.id", ondelete="SET NULL"),
                      nullable=True, comment="来源文件ID（技能转换生成时指向原始文件）"),
        )
        op.create_index("ix_knowledge_files_source_file_id", "knowledge_files", ["source_file_id"])

    if "skills_applied" not in existing_cols:
        op.add_column(
            "knowledge_files",
            sa.Column("skills_applied", sa.Text(), nullable=True,
                      comment='应用的技能管线JSON数组'),
        )

    # 2. Create skill_definitions table (may already exist from baseline)
    if "skill_definitions" not in inspector.get_table_names():
        op.create_table(
            "skill_definitions",
            sa.Column("id", sa.Integer(), primary_key=True, index=True),
            sa.Column("name", sa.String(100), unique=True, nullable=False, index=True,
                      comment="技能名称（唯一标识）"),
            sa.Column("skill_type", sa.String(20), nullable=False, server_default="tool",
                      comment="技能类型: transform / tool"),
            sa.Column("description", sa.String(500), comment="技能描述"),
            sa.Column("input_types", sa.Text(), comment='输入文件类型JSON数组'),
            sa.Column("output_type", sa.String(50), comment="输出文件类型"),
            sa.Column("metadata_json", sa.Text(), comment="额外元数据JSON"),
            sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"),
                      comment="是否启用"),
            sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
        )


def downgrade() -> None:
    from sqlalchemy import inspect
    conn = op.get_bind()
    inspector = inspect(conn)

    if "skill_definitions" in inspector.get_table_names():
        op.drop_table("skill_definitions")

    existing_cols = {c["name"] for c in inspector.get_columns("knowledge_files")}
    if "source_file_id" in existing_cols:
        op.drop_index("ix_knowledge_files_source_file_id", table_name="knowledge_files")
        op.drop_column("knowledge_files", "source_file_id")
    if "skills_applied" in existing_cols:
        op.drop_column("knowledge_files", "skills_applied")
