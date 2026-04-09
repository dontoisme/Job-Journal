"""Curated seed data for target companies across Don's focus sectors.

Sectors: AI/ML, Health-Tech, Growth/PLG, Dev Tools, Fintech, Austin-local.
Only includes companies with Greenhouse, Lever, or Ashby ATS (API-scannable).

URL format uses standard ATS domains so the slug extractor can derive the
company identifier for direct API calls. If a slug is wrong, the scanner
returns 0 jobs — no harm done.
"""

from jj.db import get_or_create_company


# fmt: off
TARGET_COMPANIES = [
    # =====================================================================
    # AI / ML / LLM
    # =====================================================================
    {"name": "Anthropic", "careers_url": "https://boards.greenhouse.io/anthropic", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "OpenAI", "careers_url": "https://jobs.ashbyhq.com/openai", "ats_type": "ashby", "industry": "AI"},
    {"name": "Cohere", "careers_url": "https://jobs.lever.co/cohere", "ats_type": "lever", "industry": "AI"},
    {"name": "Scale AI", "careers_url": "https://boards.greenhouse.io/scaleai", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Weights & Biases", "careers_url": "https://boards.greenhouse.io/wandb", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Runway", "careers_url": "https://boards.greenhouse.io/runwayml", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Writer", "careers_url": "https://boards.greenhouse.io/writer", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Glean", "careers_url": "https://boards.greenhouse.io/gleanwork", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Grammarly", "careers_url": "https://boards.greenhouse.io/grammarly", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Jasper", "careers_url": "https://boards.greenhouse.io/jasper", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Character AI", "careers_url": "https://boards.greenhouse.io/characterai", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Perplexity", "careers_url": "https://boards.greenhouse.io/perplexityai", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Harvey AI", "careers_url": "https://boards.greenhouse.io/harvey", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Sierra AI", "careers_url": "https://jobs.ashbyhq.com/sierra", "ats_type": "ashby", "industry": "AI"},
    {"name": "EvenUp", "careers_url": "https://boards.greenhouse.io/evenuplaw", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Cursor", "careers_url": "https://jobs.ashbyhq.com/anysphere", "ats_type": "ashby", "industry": "AI"},
    {"name": "Together AI", "careers_url": "https://boards.greenhouse.io/togetherai", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Mistral AI", "careers_url": "https://jobs.lever.co/mistral", "ats_type": "lever", "industry": "AI"},
    {"name": "Adept AI", "careers_url": "https://boards.greenhouse.io/adeptailabs", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Pinecone", "careers_url": "https://jobs.ashbyhq.com/pinecone", "ats_type": "ashby", "industry": "AI"},
    {"name": "Weaviate", "careers_url": "https://boards.greenhouse.io/weaviate", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "LangChain", "careers_url": "https://boards.greenhouse.io/langchain", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Stability AI", "careers_url": "https://boards.greenhouse.io/stabilityai", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Inflection AI", "careers_url": "https://boards.greenhouse.io/inflectionai", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Anyscale", "careers_url": "https://jobs.lever.co/anyscale", "ats_type": "lever", "industry": "AI"},
    {"name": "Modal", "careers_url": "https://jobs.ashbyhq.com/modal", "ats_type": "ashby", "industry": "AI"},
    {"name": "Fireworks AI", "careers_url": "https://boards.greenhouse.io/fireworksai", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Replit", "careers_url": "https://boards.greenhouse.io/replit", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Hebbia", "careers_url": "https://jobs.ashbyhq.com/hebbia", "ats_type": "ashby", "industry": "AI"},
    {"name": "Tome", "careers_url": "https://boards.greenhouse.io/tome", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Covariant", "careers_url": "https://jobs.lever.co/covariant", "ats_type": "lever", "industry": "AI"},
    {"name": "Imbue", "careers_url": "https://boards.greenhouse.io/imbue", "ats_type": "greenhouse", "industry": "AI"},
    {"name": "Cleanlab", "careers_url": "https://jobs.ashbyhq.com/cleanlab", "ats_type": "ashby", "industry": "AI"},

    # =====================================================================
    # Health-Tech / Digital Health
    # =====================================================================
    {"name": "Hims & Hers", "careers_url": "https://boards.greenhouse.io/himshers", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Ro", "careers_url": "https://jobs.lever.co/ro", "ats_type": "lever", "industry": "health-tech"},
    {"name": "Noom", "careers_url": "https://boards.greenhouse.io/noom", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Cityblock Health", "careers_url": "https://boards.greenhouse.io/cityblockhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Oscar Health", "careers_url": "https://boards.greenhouse.io/oscarhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Devoted Health", "careers_url": "https://boards.greenhouse.io/devoted", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Aledade", "careers_url": "https://boards.greenhouse.io/aledade", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Tempus AI", "careers_url": "https://boards.greenhouse.io/tempus", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Flatiron Health", "careers_url": "https://boards.greenhouse.io/flatironhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Veeva Systems", "careers_url": "https://jobs.lever.co/veeva", "ats_type": "lever", "industry": "health-tech"},
    {"name": "Health Catalyst", "careers_url": "https://boards.greenhouse.io/healthcatalyst", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Omada Health", "careers_url": "https://boards.greenhouse.io/omadahealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Spring Health", "careers_url": "https://boards.greenhouse.io/springhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Lyra Health", "careers_url": "https://boards.greenhouse.io/lyrahealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Modern Health", "careers_url": "https://boards.greenhouse.io/modernhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Sword Health", "careers_url": "https://boards.greenhouse.io/swordhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Virta Health", "careers_url": "https://boards.greenhouse.io/virtahealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Transcarent", "careers_url": "https://boards.greenhouse.io/transcarent", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Included Health", "careers_url": "https://boards.greenhouse.io/includedhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Carbon Health", "careers_url": "https://boards.greenhouse.io/carbonhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "GoodRx", "careers_url": "https://boards.greenhouse.io/goodrx", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Garner Health", "careers_url": "https://boards.greenhouse.io/garnerhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Alto Pharmacy", "careers_url": "https://boards.greenhouse.io/alto", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Headspace", "careers_url": "https://boards.greenhouse.io/headspace", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Talkspace", "careers_url": "https://boards.greenhouse.io/talkspace", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Cerebral", "careers_url": "https://boards.greenhouse.io/cerebral", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Hinge Health", "careers_url": "https://boards.greenhouse.io/hingehealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Viz.ai", "careers_url": "https://boards.greenhouse.io/vizai", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Thirty Madison", "careers_url": "https://boards.greenhouse.io/thirtymadison", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Color Health", "careers_url": "https://boards.greenhouse.io/colorhealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Quartet Health", "careers_url": "https://boards.greenhouse.io/quartethealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Turquoise Health", "careers_url": "https://boards.greenhouse.io/turquoisehealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Bicycle Health", "careers_url": "https://boards.greenhouse.io/bicyclehealth", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Wellthy", "careers_url": "https://boards.greenhouse.io/wellthy", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Accolade", "careers_url": "https://boards.greenhouse.io/accolade", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Zocdoc", "careers_url": "https://boards.greenhouse.io/zocdoc", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Headway", "careers_url": "https://boards.greenhouse.io/headway", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Alma", "careers_url": "https://boards.greenhouse.io/alma", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Wheel Health", "careers_url": "https://boards.greenhouse.io/wheel", "ats_type": "greenhouse", "industry": "health-tech"},
    {"name": "Commure", "careers_url": "https://jobs.lever.co/commure", "ats_type": "lever", "industry": "health-tech"},
    {"name": "Elation Health", "careers_url": "https://jobs.lever.co/elationhealth", "ats_type": "lever", "industry": "health-tech"},
    {"name": "Abridge", "careers_url": "https://jobs.ashbyhq.com/Abridge", "ats_type": "ashby", "industry": "health-tech"},

    # =====================================================================
    # Growth / PLG / Analytics / Experimentation
    # =====================================================================
    {"name": "Amplitude", "careers_url": "https://boards.greenhouse.io/amplitude", "ats_type": "greenhouse", "industry": "analytics"},
    {"name": "LaunchDarkly", "careers_url": "https://boards.greenhouse.io/launchdarkly", "ats_type": "greenhouse", "industry": "experimentation"},
    {"name": "Pendo", "careers_url": "https://boards.greenhouse.io/pendo", "ats_type": "greenhouse", "industry": "analytics"},
    {"name": "FullStory", "careers_url": "https://boards.greenhouse.io/fullstory", "ats_type": "greenhouse", "industry": "analytics"},
    {"name": "Braze", "careers_url": "https://boards.greenhouse.io/braze", "ats_type": "greenhouse", "industry": "growth"},
    {"name": "Iterable", "careers_url": "https://boards.greenhouse.io/iterable", "ats_type": "greenhouse", "industry": "growth"},
    {"name": "Customer.io", "careers_url": "https://boards.greenhouse.io/customerio", "ats_type": "greenhouse", "industry": "growth"},
    {"name": "Mixpanel", "careers_url": "https://boards.greenhouse.io/mixpanel", "ats_type": "greenhouse", "industry": "analytics"},
    {"name": "Heap", "careers_url": "https://boards.greenhouse.io/heap", "ats_type": "greenhouse", "industry": "analytics"},
    {"name": "PostHog", "careers_url": "https://boards.greenhouse.io/posthog", "ats_type": "greenhouse", "industry": "analytics"},
    {"name": "Optimizely", "careers_url": "https://boards.greenhouse.io/optimizely", "ats_type": "greenhouse", "industry": "experimentation"},
    {"name": "Statsig", "careers_url": "https://boards.greenhouse.io/statsig", "ats_type": "greenhouse", "industry": "experimentation"},
    {"name": "Eppo", "careers_url": "https://boards.greenhouse.io/eppo", "ats_type": "greenhouse", "industry": "experimentation"},
    {"name": "Segment", "careers_url": "https://boards.greenhouse.io/segment", "ats_type": "greenhouse", "industry": "analytics"},
    {"name": "OneSignal", "careers_url": "https://boards.greenhouse.io/onesignal", "ats_type": "greenhouse", "industry": "growth"},
    {"name": "Appcues", "careers_url": "https://boards.greenhouse.io/appcues", "ats_type": "greenhouse", "industry": "growth"},
    {"name": "WalkMe", "careers_url": "https://boards.greenhouse.io/walkme", "ats_type": "greenhouse", "industry": "growth"},

    # =====================================================================
    # Developer Tools / Infrastructure
    # =====================================================================
    {"name": "Vercel", "careers_url": "https://boards.greenhouse.io/vercel", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Netlify", "careers_url": "https://boards.greenhouse.io/netlify", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Supabase", "careers_url": "https://boards.greenhouse.io/supabase", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "PlanetScale", "careers_url": "https://boards.greenhouse.io/planetscale", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Neon", "careers_url": "https://jobs.ashbyhq.com/neon", "ats_type": "ashby", "industry": "dev-tools"},
    {"name": "Railway", "careers_url": "https://jobs.ashbyhq.com/railway", "ats_type": "ashby", "industry": "dev-tools"},
    {"name": "Fly.io", "careers_url": "https://jobs.ashbyhq.com/fly-io", "ats_type": "ashby", "industry": "dev-tools"},
    {"name": "Datadog", "careers_url": "https://boards.greenhouse.io/datadog", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Grafana Labs", "careers_url": "https://boards.greenhouse.io/grafanalabs", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "HashiCorp", "careers_url": "https://boards.greenhouse.io/hashicorp", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Snyk", "careers_url": "https://boards.greenhouse.io/snyk", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "CircleCI", "careers_url": "https://boards.greenhouse.io/circleci", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Linear", "careers_url": "https://boards.greenhouse.io/linear", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Figma", "careers_url": "https://boards.greenhouse.io/figma", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Notion", "careers_url": "https://boards.greenhouse.io/notion", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Miro", "careers_url": "https://boards.greenhouse.io/miro", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Retool", "careers_url": "https://boards.greenhouse.io/retool", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Airtable", "careers_url": "https://boards.greenhouse.io/airtable", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Dbt Labs", "careers_url": "https://boards.greenhouse.io/dbtlabsinc", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Fivetran", "careers_url": "https://boards.greenhouse.io/fivetran", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Temporal", "careers_url": "https://boards.greenhouse.io/temporal", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Convex", "careers_url": "https://jobs.ashbyhq.com/convex", "ats_type": "ashby", "industry": "dev-tools"},
    {"name": "Pulumi", "careers_url": "https://boards.greenhouse.io/pulumi", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Sourcegraph", "careers_url": "https://boards.greenhouse.io/sourcegraph91", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "GitLab", "careers_url": "https://boards.greenhouse.io/gitlab", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Webflow", "careers_url": "https://boards.greenhouse.io/webflow", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Loom", "careers_url": "https://boards.greenhouse.io/loom", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Coda", "careers_url": "https://boards.greenhouse.io/coda", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "ClickUp", "careers_url": "https://boards.greenhouse.io/clickup", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "Asana", "careers_url": "https://boards.greenhouse.io/asana", "ats_type": "greenhouse", "industry": "dev-tools"},

    # =====================================================================
    # Fintech / Payments
    # =====================================================================
    {"name": "Stripe", "careers_url": "https://boards.greenhouse.io/stripe", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Plaid", "careers_url": "https://boards.greenhouse.io/plaid", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Mercury", "careers_url": "https://jobs.ashbyhq.com/mercury", "ats_type": "ashby", "industry": "fintech"},
    {"name": "Ramp", "careers_url": "https://jobs.ashbyhq.com/ramp", "ats_type": "ashby", "industry": "fintech"},
    {"name": "Brex", "careers_url": "https://boards.greenhouse.io/brex", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Carta", "careers_url": "https://boards.greenhouse.io/carta", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Gusto", "careers_url": "https://boards.greenhouse.io/gusto", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Rippling", "careers_url": "https://boards.greenhouse.io/rippling", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Navan", "careers_url": "https://boards.greenhouse.io/navan", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Deel", "careers_url": "https://jobs.ashbyhq.com/deel", "ats_type": "ashby", "industry": "fintech"},
    {"name": "Remote.com", "careers_url": "https://boards.greenhouse.io/remotecom", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Marqeta", "careers_url": "https://boards.greenhouse.io/marqeta", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Modern Treasury", "careers_url": "https://boards.greenhouse.io/moderntreasury", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Alloy", "careers_url": "https://boards.greenhouse.io/alloy", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Persona", "careers_url": "https://boards.greenhouse.io/persona", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Unit", "careers_url": "https://boards.greenhouse.io/unit", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Column", "careers_url": "https://boards.greenhouse.io/column", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Sardine", "careers_url": "https://boards.greenhouse.io/sardine", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "Melio", "careers_url": "https://boards.greenhouse.io/melio", "ats_type": "greenhouse", "industry": "fintech"},

    # =====================================================================
    # Enterprise SaaS / Productivity
    # =====================================================================
    {"name": "Canva", "careers_url": "https://boards.greenhouse.io/canva", "ats_type": "greenhouse", "industry": "productivity"},
    {"name": "Monday.com", "careers_url": "https://boards.greenhouse.io/mondaycom", "ats_type": "greenhouse", "industry": "productivity"},
    {"name": "Calendly", "careers_url": "https://boards.greenhouse.io/calendly", "ats_type": "greenhouse", "industry": "productivity"},
    {"name": "Typeform", "careers_url": "https://boards.greenhouse.io/typeform", "ats_type": "greenhouse", "industry": "productivity"},
    {"name": "Zapier", "careers_url": "https://boards.greenhouse.io/zapier", "ats_type": "greenhouse", "industry": "productivity"},
    {"name": "PandaDoc", "careers_url": "https://boards.greenhouse.io/pandadoc", "ats_type": "greenhouse", "industry": "productivity"},
    {"name": "Vanta", "careers_url": "https://boards.greenhouse.io/vanta", "ats_type": "greenhouse", "industry": "security"},
    {"name": "Drata", "careers_url": "https://boards.greenhouse.io/drata", "ats_type": "greenhouse", "industry": "security"},
    {"name": "1Password", "careers_url": "https://boards.greenhouse.io/1password", "ats_type": "greenhouse", "industry": "security"},
    {"name": "Ironclad", "careers_url": "https://boards.greenhouse.io/ironclad", "ats_type": "greenhouse", "industry": "legal-tech"},
    {"name": "Lattice", "careers_url": "https://boards.greenhouse.io/lattice", "ats_type": "greenhouse", "industry": "HR-tech"},
    {"name": "HubSpot", "careers_url": "https://boards.greenhouse.io/hubspot", "ats_type": "greenhouse", "industry": "CRM"},
    {"name": "Attentive", "careers_url": "https://boards.greenhouse.io/attentive", "ats_type": "greenhouse", "industry": "marketing"},
    {"name": "Klaviyo", "careers_url": "https://boards.greenhouse.io/klaviyo", "ats_type": "greenhouse", "industry": "marketing"},

    # =====================================================================
    # Austin-based / Texas
    # =====================================================================
    {"name": "WP Engine", "careers_url": "https://boards.greenhouse.io/wpengine", "ats_type": "greenhouse", "industry": "dev-tools"},
    {"name": "BigCommerce", "careers_url": "https://boards.greenhouse.io/bigcommerce", "ats_type": "greenhouse", "industry": "e-commerce"},
    {"name": "Q2", "careers_url": "https://boards.greenhouse.io/q2ebanking", "ats_type": "greenhouse", "industry": "fintech"},
    {"name": "AlertMedia", "careers_url": "https://boards.greenhouse.io/alertmedia", "ats_type": "greenhouse", "industry": "enterprise"},
    {"name": "Homeward", "careers_url": "https://boards.greenhouse.io/homeward", "ats_type": "greenhouse", "industry": "real-estate"},
    {"name": "CrowdStrike", "careers_url": "https://boards.greenhouse.io/crowdstrike", "ats_type": "greenhouse", "industry": "security"},
    {"name": "Procore", "careers_url": "https://boards.greenhouse.io/procore", "ats_type": "greenhouse", "industry": "construction-tech"},
    {"name": "Bazaarvoice", "careers_url": "https://boards.greenhouse.io/bazaarvoice", "ats_type": "greenhouse", "industry": "e-commerce"},
    {"name": "Digital Turbine", "careers_url": "https://boards.greenhouse.io/digitalturbine", "ats_type": "greenhouse", "industry": "ad-tech"},
    {"name": "CS Disco", "careers_url": "https://boards.greenhouse.io/csdisco", "ats_type": "greenhouse", "industry": "legal-tech"},

    # =====================================================================
    # Consumer / Marketplace
    # =====================================================================
    {"name": "Airbnb", "careers_url": "https://boards.greenhouse.io/airbnb", "ats_type": "greenhouse", "industry": "marketplace"},
    {"name": "DoorDash", "careers_url": "https://boards.greenhouse.io/doordash", "ats_type": "greenhouse", "industry": "marketplace"},
    {"name": "Instacart", "careers_url": "https://boards.greenhouse.io/instacart", "ats_type": "greenhouse", "industry": "marketplace"},
    {"name": "Reddit", "careers_url": "https://boards.greenhouse.io/reddit", "ats_type": "greenhouse", "industry": "social"},
    {"name": "Discord", "careers_url": "https://boards.greenhouse.io/discord", "ats_type": "greenhouse", "industry": "social"},
    {"name": "Bumble", "careers_url": "https://boards.greenhouse.io/bumble", "ats_type": "greenhouse", "industry": "social"},
    {"name": "Duolingo", "careers_url": "https://boards.greenhouse.io/duolingo", "ats_type": "greenhouse", "industry": "education"},
    {"name": "Coursera", "careers_url": "https://boards.greenhouse.io/coursera", "ats_type": "greenhouse", "industry": "education"},
    {"name": "Thumbtack", "careers_url": "https://boards.greenhouse.io/thumbtack", "ats_type": "greenhouse", "industry": "marketplace"},
    {"name": "Nextdoor", "careers_url": "https://boards.greenhouse.io/nextdoor", "ats_type": "greenhouse", "industry": "social"},
]
# fmt: on


def seed_target_companies() -> dict[str, int]:
    """Upsert target companies from seed data.

    Uses get_or_create_company which deduplicates on normalized name.
    Returns {'created': N, 'updated': N, 'skipped': N}.
    """
    from jj.db import get_connection

    created = 0
    updated = 0
    skipped = 0

    for company in TARGET_COMPANIES:
        name = company["name"]
        careers_url = company.get("careers_url")
        ats_type = company.get("ats_type")
        industry = company.get("industry")

        # Check if company already exists
        company_id = get_or_create_company(name)

        # Check if it was just created (no careers_url yet) or already existed
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT careers_url, ats_type FROM companies WHERE id = ?",
                (company_id,),
            )
            row = cursor.fetchone()

        existing_url = row["careers_url"] if row else None
        existing_ats = row["ats_type"] if row else None

        # Update if we have better data — prefer scannable ATS URLs over generic career pages
        _scannable_domains = ("greenhouse.io", "lever.co", "ashbyhq.com")
        existing_is_scannable = existing_url and any(d in existing_url for d in _scannable_domains)
        new_is_scannable = careers_url and any(d in careers_url for d in _scannable_domains)

        updates = {}
        if careers_url and (not existing_url or (new_is_scannable and not existing_is_scannable)):
            updates["careers_url"] = careers_url
        if ats_type and (not existing_ats or existing_ats.lower() not in ("greenhouse", "lever", "ashby")):
            updates["ats_type"] = ats_type
        if industry:
            updates["industry"] = industry

        if updates:
            with get_connection() as conn:
                cursor = conn.cursor()
                set_clause = ", ".join(f"{k} = ?" for k in updates)
                cursor.execute(
                    f"UPDATE companies SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (*updates.values(), company_id),
                )
                conn.commit()
            if existing_url:
                updated += 1
            else:
                created += 1
        else:
            skipped += 1

    return {"created": created, "updated": updated, "skipped": skipped}
