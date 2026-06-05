"""
Claude tool definitions for the macro RAG chat system.
Claude autonomously selects which tools to call based on question intent.
"""

TOOLS = [
    {
        "name": "search_key_points",
        "description": (
            "Search key points extracted from sell-side macro research emails. "
            "Best for: analyst opinions, sentiment, topic views, cross-bank comparisons, "
            "structured intelligence about economies, central banks, markets. "
            "Uses hybrid semantic + BM25 search with pre-filtering. "
            "Returns key points ranked by relevance with source bank, date, sentiment, topics, "
            "citation (verbatim quote from original email), and context."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The semantic search query describing what you're looking for.",
                },
                "source_orgs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by bank shortcodes e.g. ['GS', 'JPM', 'UBS']. Use approved shortforms from source_orgs reference.",
                },
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by approved topic names e.g. ['Inflation', 'China', 'Labor Market'].",
                },
                "geographies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by geography codes e.g. ['US', 'CHN', 'EM', 'EMEA'].",
                },
                "sentiment": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["very bearish", "bearish", "neutral", "bullish", "very bullish"]},
                    "description": "Filter by sentiment. Can specify multiple to get a range.",
                },
                "date_from": {
                    "type": "string",
                    "description": "ISO date string e.g. '2026-05-01'. Filter emails sent on or after this date.",
                },
                "date_to": {
                    "type": "string",
                    "description": "ISO date string e.g. '2026-05-31'. Filter emails sent on or before this date.",
                },
                "time_reference": {
                    "type": "string",
                    "enum": ["past", "present", "future"],
                    "description": "Filter by whether the key point refers to past, present, or future conditions.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of results to return. Default 20, max 50.",
                    "default": 20,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_trade_ideas",
        "description": (
            "Search trade ideas extracted from sell-side macro research emails. "
            "Best for: specific trade recommendations, asset class views, positioning ideas, "
            "long/short calls with entry/exit levels. "
            "Returns trade ideas with legs (instrument, direction), target/stop prices, "
            "asset class, time horizon, and source citation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The semantic search query describing the trade or market view.",
                },
                "source_orgs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by bank shortcodes e.g. ['GS', 'MS'].",
                },
                "asset_classes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by asset class e.g. ['Rates', 'FX', 'Equities', 'Credit', 'Commodities'].",
                },
                "geographies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by geography codes e.g. ['US', 'CHN', 'EM'].",
                },
                "date_from": {"type": "string", "description": "ISO date string."},
                "date_to": {"type": "string", "description": "ISO date string."},
                "top_k": {"type": "integer", "default": 20},
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_emails",
        "description": (
            "Search the raw email content (chunked). Best for: finding specific emails, "
            "locating passages not captured by key-point extraction, "
            "'find the email about X', broad coverage queries. "
            "Returns matched email chunks + full parent email body + all key points and "
            "trade ideas extracted from that same email (linked via email_content_hash). "
            "Use this when the user asks to 'find emails about' something or when "
            "key point search returns insufficient results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The semantic search query. Can be a topic, person, event, or phrase.",
                },
                "source_orgs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by bank shortcodes.",
                },
                "date_from": {"type": "string", "description": "ISO date string."},
                "date_to": {"type": "string", "description": "ISO date string."},
                "top_k": {
                    "type": "integer",
                    "description": "Number of unique emails to return. Default 5.",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_disagreements",
        "description": (
            "Retrieve validated cross-bank sentiment disagreements on macro topics. "
            "Best for: 'which banks disagree on X', 'where is there debate about Y', "
            "contrarian views, divergent positioning. "
            "Only returns disagreements confirmed as non-false-positive by the validation pipeline. "
            "Includes bank positions with their sentiment and supporting evidence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by topic e.g. ['Inflation', 'China'].",
                },
                "geographies": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter by geography codes.",
                },
                "scale": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["High", "Medium", "Low"]},
                    "description": "Filter by disagreement intensity.",
                },
                "date_from": {"type": "string", "description": "ISO date string."},
                "date_to": {"type": "string", "description": "ISO date string."},
                "limit": {"type": "integer", "default": 10},
            },
            "required": [],
        },
    },
    {
        "name": "get_topic_summary",
        "description": (
            "Retrieve pre-computed daily topic summaries — bullet-point digests of "
            "what sell-side analysts said about a macro topic during a time window. "
            "Best for: 'summarise what banks said about inflation this week', daily briefings. "
            "Each bullet has [N] footnote labels that map to specific key_point_ids for citation. "
            "More concise than raw key points — good for high-level overviews."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Exact topic name e.g. 'Inflation', 'China', 'Labor Market'.",
                },
                "date": {
                    "type": "string",
                    "description": "ISO date string. Returns summaries whose window covers this date.",
                },
                "limit": {"type": "integer", "default": 5},
            },
            "required": [],
        },
    },
    {
        "name": "get_stats",
        "description": (
            "Run SQL aggregations over the macro data. Best for: quantitative questions, "
            "distributions, counts, rankings. "
            "Examples: 'which bank published the most bearish views?', "
            "'sentiment breakdown by topic', 'trade idea count by asset class', "
            "'how many disagreements per topic'. Returns structured numbers you can narrate."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "enum": [
                        "count_by_bank",
                        "sentiment_distribution",
                        "topic_frequency",
                        "asset_class_breakdown",
                        "disagreement_by_topic",
                    ],
                    "description": "Which aggregation to run.",
                },
                "filters": {
                    "type": "object",
                    "description": "Optional filters: {source_org, topic, geography, sentiment, date_from, date_to}",
                    "properties": {
                        "source_org": {"type": "string"},
                        "topic": {"type": "string"},
                        "geography": {"type": "string"},
                        "sentiment": {"type": "string"},
                        "date_from": {"type": "string"},
                        "date_to": {"type": "string"},
                    },
                },
            },
            "required": ["metric"],
        },
    },
]
