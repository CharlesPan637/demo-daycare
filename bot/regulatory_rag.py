"""Dynamic regulatory retrieval for daycare licensing compliance."""


def _split_keywords(raw: str) -> list[str]:
    """Split comma/pipe/semicolon-separated keyword strings."""
    if not raw:
        return []
    normalized = str(raw).replace("|", ",").replace(";", ",")
    return [part.strip().lower() for part in normalized.split(",") if part.strip()]


def search_dynamic_regulations(query: str, dynamic_rules: list[dict]) -> list[dict]:
    """Score ingested regulatory rules from Grist rows and return top 3."""
    query_lower = query.lower()
    scored: list[tuple[float, dict]] = []

    for row in dynamic_rules:
        fields = row.get("fields", {})
        title = str(fields.get("title", ""))
        summary = str(fields.get("summary", ""))
        rule_text = str(fields.get("rule_text", ""))
        category = str(fields.get("category", ""))
        jurisdiction = str(fields.get("jurisdiction", ""))
        keywords = _split_keywords(str(fields.get("keywords", "")))
        score = 0.0

        for kw in keywords:
            if kw and kw in query_lower:
                score += 1.5
        for token in str(title).lower().split():
            if len(token) > 3 and token in query_lower:
                score += 0.7
        for token in str(category).lower().split():
            if len(token) > 3 and token in query_lower:
                score += 0.6
        if jurisdiction and jurisdiction.lower() in query_lower:
            score += 1.0
        if summary and any(term in query_lower for term in str(summary).lower().split() if len(term) > 4):
            score += 0.5
        if rule_text and any(term in query_lower for term in str(rule_text).lower().split() if len(term) > 5):
            score += 0.2

        if score > 0:
            scored.append((score, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in scored[:3]]


def get_regulatory_answer(query: str, dynamic_rules: list[dict] | None = None) -> str | None:
    """Return formatted regulatory answer from ingested rules only."""
    if dynamic_rules:
        matches = search_dynamic_regulations(query, dynamic_rules)
        if matches:
            best = matches[0].get("fields", {})
            category = best.get("category", "Compliance")
            title = best.get("title", "Regulatory Guidance")
            summary = best.get("summary") or best.get("rule_text") or "No summary available."
            version = best.get("version", "n/a")
            jurisdiction = best.get("jurisdiction", "state")
            source_url = str(best.get("source_url", "")).strip()
            response = f"📋 *{category}*\n\n*{title}*\n{summary}\n\n_Source: {jurisdiction} · v{version}_"
            if source_url:
                response += f"\n{source_url}"
            if len(matches) > 1:
                extras = []
                for extra in matches[1:]:
                    f = extra.get("fields", {})
                    extras.append(str(f.get("title") or f.get("category") or f.get("rule_key") or "related rule"))
                response += f"\n\n_Also relevant: {', '.join(extras)}_"
            return response
    return None
