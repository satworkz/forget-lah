"""Durable, explicitly bound WhatsApp test-phone channel."""

import sqlalchemy as sa
from alembic import op

from forget_lah.channel_models import ChannelBinding, ChannelInbox, ChannelOutbox

revision = "0008"
down_revision = "0007"
branch_labels = depends_on = None


def upgrade():
    op.add_column("simulated_message", sa.Column("translation", sa.JSON(), nullable=True))
    for model in (ChannelBinding, ChannelInbox, ChannelOutbox):
        model.__table__.create(op.get_bind())


def downgrade():
    raise RuntimeError("Forward-only: preserve provider replay protection")
