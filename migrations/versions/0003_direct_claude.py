"""Allow direct Anthropic runs without changing existing runs or call budgets."""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    if connection.dialect.name == "sqlite":
        # SQLite is used for fresh test databases. Name the old anonymous CHECK
        # in the reflected copy so batch migration can replace only that CHECK.
        table = sa.Table("agent_run", sa.MetaData(), autoload_with=connection)
        for constraint in table.constraints:
            if isinstance(constraint, sa.CheckConstraint) and str(constraint.sqltext).startswith(
                "mode "
            ):
                constraint.name = "ck_agent_run_mode"
        with op.batch_alter_table("agent_run", copy_from=table) as batch:
            batch.drop_constraint("ck_agent_run_mode", type_="check")
            batch.create_check_constraint(
                "ck_agent_run_mode", "mode IN ('mock','organiser','anthropic')"
            )
    else:
        constraints = sa.inspect(connection).get_check_constraints("agent_run")
        mode_check = next(c for c in constraints if "mode" in c["sqltext"])
        op.drop_constraint(mode_check["name"], "agent_run", type_="check")
        op.create_check_constraint(
            "ck_agent_run_mode", "agent_run", "mode IN ('mock','organiser','anthropic')"
        )


def downgrade():
    raise RuntimeError("Forward-only migration: preserve recorded Anthropic runs.")
