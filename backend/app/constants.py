# Source type weights for multi-source confidence (Phase 16)
SOURCE_WEIGHTS: dict[str, float] = {
    "official_blog": 1.0,
    "github_release": 0.95,
    "documentation": 0.9,
    "newsletter": 0.75,
    "personal_blog": 0.5,
    "web": 0.6,
    "github": 0.85,
}

VERIFICATION_LEVELS = (
    "verified",        # official + multiple sources
    "highly_likely",   # high confidence score + 3+ newsletters
    "reported",        # 1-2 newsletter sources
    "emerging",        # single source, low confidence
)

# Major companies for importance weighting
MAJOR_COMPANIES = frozenset({
    "OpenAI", "Anthropic", "Google", "Meta", "Microsoft", "Apple", "Amazon",
    "Nvidia", "Hugging Face", "Stability AI", "Mistral", "Cohere",
})

# Sidebar modes — keyword maps power chat filtering
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Fintech": [
        "fintech", "payments", "banking", "neobank", "lending", "insurtech",
        "stripe", "paypal", "visa", "mastercard", "upi", "wallet", "trading",
        "crypto", "defi", "regtech", "wealthtech", "bnpl",
    ],
    "Edtech": [
        "edtech", "education", "learning", "course", "university", "student",
        "lms", "elearning", "k-12", "curriculum", "tutoring", "mooc", "classroom",
    ],
    "AI Startups": [
        "ai startup", "startup", "founder", "seed round", "series a", "series b",
        "raised", "venture", "yc", "accelerator", "unicorn", "funding round",
    ],
    "AI Tools Launched": [
        "launch", "launched", "released", "announces", "new tool", "new product",
        "beta", "generally available", "introducing", "rollout", "ship", "debut",
    ],
    "Marketplace & Growth": [
        "marketplace", "market boom", "growth", "valuation", "ipo", "acquisition",
        "merger", "market share", "revenue", "gmv", "expansion", "scale-up",
    ],
    "Research & Updates": [
        "research", "paper", "study", "arxiv", "breakthrough", "findings",
        "published", "journal", "whitepaper", "benchmark", "experiment",
    ],
    "Cloud & Infrastructure": [
        "cloud", "aws", "azure", "gcp", "kubernetes", "docker", "serverless",
        "infrastructure", "datacenter", "gpu cluster", "cdn", "devops", "saas",
    ],
}

CATEGORIES = list(CATEGORY_KEYWORDS.keys())

TIMELINE_LABELS: dict[str, str] = {
    "24h": "today",
    "2d": "the last 2 days",
    "4d": "the last 4 days",
    "1w": "this week",
    "2w": "the last 2 weeks",
    "1m": "this month",
    "2m": "the last 2 months",
    "3m": "the last 3 months",
    "all": "all time",
}

TIMELINE_FILTERS: dict[str, int] = {
    "24h": 1,
    "2d": 2,
    "4d": 4,
    "1w": 7,
    "2w": 14,
    "1m": 30,
    "2m": 60,
    "3m": 90,
    "all": 36500,  # effectively unlimited
}

KNOWN_NEWSLETTER_DOMAINS = frozenset({
    "tldrnewsletter.com", "tldr.tech", "substack.com", "beehiiv.com",
    "mail.beehiiv.com", "convertkit.com", "ck.page", "mailchimp.com",
    "campaign-archive.com", "buttondown.email", "ghost.io", "mailerlite.com",
    "sendgrid.net", "mailgun.org", "sparkpostmail.com", "getrevue.co",
    "newsletter.co", "morningbrew.com", "theinformation.com",
    "therundown.ai", "bensbites.co", "alphasignal.ai",
})

# Gmail `from:` clauses for newsletters that may not match list-unsubscribe alone
GMAIL_NEWSLETTER_FROM_CLAUSES = (
    "substack.com OR beehiiv.com OR mailchimp.com OR buttondown.email OR "
    "ghost.io OR convertkit.com OR tldrnewsletter.com OR tldr.tech OR "
    "therundown.ai OR bensbites.co OR morningbrew.com"
)

# Friendly display names for known senders/domains
KNOWN_NEWSLETTER_LABELS: dict[str, str] = {
    "tldrnewsletter.com": "TLDR",
    "tldr.tech": "TLDR",
    "therundown.ai": "The Rundown AI",
    "bensbites.co": "Ben's Bites",
    "morningbrew.com": "Morning Brew",
}

NEWSLETTER_SENDER_PREFIXES = (
    "noreply@", "no-reply@", "newsletter@", "news@", "digest@",
    "updates@", "hello@", "team@", "mail@", "newsletters@",
)
