"""Add opportunity_criteria and risk_criteria columns to ai_config

Revision ID: 0014
Revises: 0013
Create Date: 2026-05-22

Lets the operator describe — per deployment / market — what counts as an
opportunity and what counts as a risk. The assessment prompt template
substitutes these into the system message instead of relying on hard-coded
pathway lists baked into prompts.py.
"""

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


DEFAULT_OPPORTUNITY = """\
- Viral products, trending categories, or consumer behaviour shifts the business should react to in assortment / marketing
- Emerging trends within categories we sell (e.g. health, sustainability, premiumisation)
- New consumer segments or demographic shifts that expand our addressable market
- Competitor moves, exits, or whitespace we can capture
- New routes, sites, or channels that expand our footprint or audience"""

DEFAULT_RISK = """\
- Supply chain disruptions affecting our core categories or key suppliers
- Geopolitical events, wars, sanctions, or trade restrictions impacting our markets
- Natural disasters, weather events, or health crises (pandemics, outbreaks) affecting demand or operations
- Regulatory changes (taxation, product bans, safety mandates, packaging or labelling rules)
- Reputational / ESG threats relevant to our brand, categories, or social licence
- Macro shocks that change customer footfall, basket size, or category mix"""


def upgrade() -> None:
    op.add_column("ai_config", sa.Column("opportunity_criteria", sa.Text(), nullable=True))
    op.add_column("ai_config", sa.Column("risk_criteria", sa.Text(), nullable=True))

    op.execute(
        sa.text(
            "UPDATE ai_config SET opportunity_criteria = :opp, risk_criteria = :risk "
            "WHERE key = 'default'"
        ).bindparams(opp=DEFAULT_OPPORTUNITY, risk=DEFAULT_RISK)
    )


def downgrade() -> None:
    op.drop_column("ai_config", "risk_criteria")
    op.drop_column("ai_config", "opportunity_criteria")
