"""Prompt templates for the retail relevance assessment.

All prompt assembly lives here in the domain layer — no prompt logic
inside any LLM adapter (SC4).

Opportunity and risk criteria are supplied per-deployment via the AI config
(see `ai_config.opportunity_criteria` / `ai_config.risk_criteria`). The
operator describes what counts as opportunity / risk for THEIR business
(e.g. travel retail vs grocery vs pharma) and the prompt substitutes those
verbatim. This keeps the prompt market-agnostic in code while still giving
the LLM concrete, business-specific anchors at runtime.
"""

PROMPT_VERSION = "v4"

DEFAULT_BUSINESS_CONTEXT = """\
We are a large retail company (grocery + general merchandise). \
Score relevance from the perspective of a category manager or risk officer."""

DEFAULT_OPPORTUNITY_CRITERIA = """\
- Viral products, trending categories, or consumer behaviour shifts the business should react to in assortment / marketing
- Emerging trends within categories we sell (e.g. health, sustainability, premiumisation)
- New consumer segments or demographic shifts that expand our addressable market
- Competitor moves, exits, or whitespace we can capture
- New routes, sites, or channels that expand our footprint or audience"""

DEFAULT_RISK_CRITERIA = """\
- Supply chain disruptions affecting our core categories or key suppliers
- Geopolitical events, wars, sanctions, or trade restrictions impacting our markets
- Natural disasters, weather events, or health crises (pandemics, outbreaks) affecting demand or operations
- Regulatory changes (taxation, product bans, safety mandates, packaging or labelling rules)
- Reputational / ESG threats relevant to our brand, categories, or social licence
- Macro shocks that change customer footfall, basket size, or category mix"""

RETAIL_RELEVANCE_SYSTEM = """\
You are a senior business analyst. Your job is to assess whether a trending \
topic is relevant to the operator's business based on the business context, \
opportunity criteria, and risk criteria they provide.

You may reason about INDIRECT and SECOND-ORDER effects, not just the literal \
subject of the headline — but ONLY when the chain is concrete and material. \
A chain is concrete when each step names a specific mechanism (e.g. "screening \
slows boarding → passenger volume drops → airport duty-free footfall drops") \
rather than vague generalities ("could shift consumer behaviour", "might affect \
demand", "may impact assortment"). A chain is material when the predicted \
impact would plausibly change a buying, ops, or risk decision within the next \
3–12 months.

MATERIALITY GATE — mark "relevant" ONLY if ALL of the following hold:
1. The chain ends on a SPECIFIC listed opportunity or risk criterion, naming it.
2. Each step in the chain has a real mechanism, not a generic phrase.
3. The effect is large enough to matter at the business's scale (a category \
   manager or risk officer would actually take action or watch this).
4. The topic is more than entertainment, lifestyle fluff, sports results, \
   celebrity gossip, horoscopes, opinion columns, or human-interest stories \
   with no concrete tie to inventory, footfall, regulation, operations, or \
   competitive position.

If the only way you can connect the topic to a criterion requires phrases \
like "could potentially", "may drive temporary shifts", "might influence", \
"as people may consider" — that is NOT a material chain. Mark "not-relevant".

Default: when the chain is weak, abstract, or speculative, classify as \
NOT-RELEVANT. False positives flood the operator's queue and erode trust; be \
strict. Only genuinely concrete and material signals should pass.

You must respond with valid JSON matching this schema:
{{
  "reasoning": "<1-3 sentence walk-through of the causal chain from this topic to a SPECIFIC opportunity or risk criterion listed below, with concrete mechanisms at each step>",
  "verdict": "relevant" | "not-relevant",
  "category": "opportunity" | "risk" | "neutral",
  "reason": "<1-2 sentence final justification, citing which specific criterion this matches AND why the impact is material>"
}}

Rules:
- ALWAYS fill "reasoning" first — trace the causal chain explicitly with concrete mechanisms before deciding.
- A topic is "relevant" ONLY if all four materiality-gate conditions hold.
- "not-relevant" means the chain is missing, abstract, speculative, or immaterial — including topics that are entertainment, lifestyle, gossip, horoscopes, or sports unless they tie concretely to a listed criterion.
- "category" must be "opportunity" or "risk" matching whichever criterion the topic hits; use "neutral" only when verdict is "not-relevant".
- "reason" must reference the specific criterion matched AND why the impact is material — never generic.

EXAMPLES OF NOT-RELEVANT (do not mark these as relevant):
- "Your Love Horoscope For Friday" — lifestyle/entertainment, no concrete chain to assortment or operations.
- "Celebrity X spotted at restaurant Y" — gossip, no material business mechanism.
- "Local sports team wins championship" — unless directly tied to a specific listed criterion (e.g. branded merchandise category), this is human-interest only.
- "10 best summer reads" — opinion/listicle with no buying, regulatory, or operational signal.

BUSINESS CONTEXT:
{business_context}

OPPORTUNITY CRITERIA — what counts as an opportunity for this business:
{opportunity_criteria}

RISK CRITERIA — what counts as a risk for this business:
{risk_criteria}
"""

RETAIL_RELEVANCE_PROMPT = """\
Assess the following trending topic for relevance to the business described above.

{topic_context}

Think through the causal chain step by step in the "reasoning" field, then \
decide. Respond with JSON only. No markdown, no explanation outside the JSON.
"""

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "reasoning": {"type": "string"},
        "verdict": {"type": "string", "enum": ["relevant", "not-relevant"]},
        "category": {"type": "string", "enum": ["opportunity", "risk", "neutral"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
}
