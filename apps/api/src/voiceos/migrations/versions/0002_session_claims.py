"""session claims: a session token is single use across every runtime replica

Revision ID: 3c1f0a7d9e21 (file name 0002)
Revises: b59fa127dcc4
Create Date: 2026-10-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "3c1f0a7d9e21"
down_revision: str | Sequence[str] | None = "b59fa127dcc4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "session_claims",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("session_id", name=op.f("session_claims_pkey")),
    )
    op.create_index(
        op.f("ix_session_claims_claimed_at"), "session_claims", ["claimed_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_session_claims_claimed_at"), table_name="session_claims")
    op.drop_table("session_claims")
