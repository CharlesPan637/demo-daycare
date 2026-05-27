"""Regulatory knowledge base for daycare licensing compliance.

Each entry maps to a section of state daycare licensing regulations.
In production, this would be a vector store with embeddings from real state regs.
For the demo, we use keyword-matched retrieval with pre-cached responses.
"""

REGULATIONS = [
    {
        "id": "ratio_infant",
        "category": "Staff-Child Ratios",
        "keywords": ["ratio", "infant", "baby", "0-18", "how many staff", "staff per child"],
        "question_examples": [
            "What's the staff ratio for infants?",
            "How many staff do we need for the infant room?",
            "What's the required ratio for babies?",
        ],
        "rule": "1:4 ratio for infants (0-18 months). Maximum group size: 8 infants.",
        "response": "Per state licensing, the infant room (0-18 months) requires a 1:4 staff-to-child ratio. "
                    "Maximum group size is 8 infants. Our Infant Room currently meets this requirement.",
    },
    {
        "id": "ratio_toddler",
        "category": "Staff-Child Ratios",
        "keywords": ["ratio", "toddler", "18-36", "2 year", "toddler room"],
        "question_examples": [
            "What's the toddler ratio?",
            "How many staff for toddlers?",
        ],
        "rule": "1:6 ratio for toddlers (18-36 months). Maximum group size: 12 toddlers.",
        "response": "The toddler room (18-36 months) requires a 1:6 staff-to-child ratio. "
                    "Maximum group size is 12 toddlers. Our Toddler Room currently has 2 enrolled with 1 staff member.",
    },
    {
        "id": "ratio_preschool",
        "category": "Staff-Child Ratios",
        "keywords": ["ratio", "preschool", "3-4", "preschool room", "3 year"],
        "question_examples": [
            "What's the preschool ratio?",
            "How many staff for preschoolers?",
        ],
        "rule": "1:10 ratio for preschool (3-4 years). Maximum group size: 20 children.",
        "response": "The preschool room (3-4 years) requires a 1:10 staff-to-child ratio. "
                    "Maximum group size is 20 children. Our Preschool Room has 4 enrolled with 1 staff member.",
    },
    {
        "id": "ratio_prek",
        "category": "Staff-Child Ratios",
        "keywords": ["ratio", "pre-k", "prek", "4-5", "4 year", "5 year"],
        "question_examples": [
            "What's the Pre-K ratio?",
            "How many staff for Pre-K?",
        ],
        "rule": "1:12 ratio for Pre-K (4-5 years). Maximum group size: 24 children.",
        "response": "The Pre-K room (4-5 years) requires a 1:12 staff-to-child ratio. "
                    "Maximum group size is 24 children. Our Pre-K Room has 2 enrolled with 1 staff member.",
    },
    {
        "id": "allergy_policy",
        "category": "Health & Safety",
        "keywords": ["allergy", "allergies", "peanut", "dairy", "egg", "gluten", "food", "epipen"],
        "question_examples": [
            "What's our peanut allergy policy?",
            "How do we handle food allergies?",
            "What's the allergy procedure?",
        ],
        "rule": "All known food allergies must be documented, posted in classroom and kitchen, "
                "and all staff trained. EpiPen must be on-site for severe allergies. "
                "Kitchen must provide allergen-free substitutions.",
        "response": "Sunshine Sprouts is a peanut-aware center. All food allergies are documented in Grist "
                    "and posted in each classroom and the kitchen. We have 4 children with allergies: "
                    "Liam (peanut, severe — EpiPen on site), Sophia (dairy), Ava (egg), Isabella (gluten). "
                    "All staff complete annual food allergy training. The kitchen maintains documented "
                    "substitutions for all allergen-restricted children.",
    },
    {
        "id": "staff_qualifications",
        "category": "Staffing Requirements",
        "keywords": ["qualification", "training", "certification", "degree", "background check", "cpr"],
        "question_examples": [
            "What qualifications do staff need?",
            "What certifications are required?",
            "Do staff need background checks?",
        ],
        "rule": "Lead teachers: CDA or equivalent + 2 years experience. "
                "All staff: CPR/First Aid, background check, 24 hours annual training. "
                "Director: Bachelor's + 3 years experience.",
        "response": "Per state licensing:\n"
                    "• Lead Teachers: CDA credential (or equivalent) + 2 years experience\n"
                    "• All Staff: Current CPR/First Aid certification, cleared background check, "
                    "24 hours of annual professional development\n"
                    "• Director: Bachelor's degree in ECE or related field + 3 years experience\n\n"
                    "Our staff: Maria Gonzalez (Lead, 8 yrs exp), David Kim (Lead, CDA, bilingual), "
                    "Sarah Chen (Director, M.Ed in Early Childhood).",
    },
    {
        "id": "nap_requirements",
        "category": "Daily Operations",
        "keywords": ["nap", "sleep", "rest", "quiet time", "crib", "cot"],
        "question_examples": [
            "What are the nap time requirements?",
            "How long should naps be?",
            "What are safe sleep rules?",
        ],
        "rule": "Children under 5 must have a supervised rest period. "
                "Infants: individual schedules, placed on back in crib. "
                "Toddlers/Preschool: cots/mats, 1-2 hour quiet period.",
        "response": "State licensing requires a supervised rest period for all children under 5:\n"
                    "• Infants: Individual sleep schedules, always placed on back in a safety-approved crib "
                    "with no blankets, bumpers, or toys\n"
                    "• Toddlers & Preschool: 1-2 hour quiet rest period on individual cots/mats "
                    "with sanitized linens\n"
                    "• Pre-K: Quiet time with quiet activities (books, puzzles) — nap optional\n\n"
                    "Our nap time is 12:30 PM – 2:30 PM daily.",
    },
    {
        "id": "outdoor_play",
        "category": "Daily Operations",
        "keywords": ["outside", "outdoor", "playground", "recess", "weather", "play"],
        "question_examples": [
            "Is there outdoor play today?",
            "When do kids go outside?",
            "What's the outdoor play policy?",
        ],
        "rule": "Minimum 60 minutes outdoor play daily, weather permitting. "
                "Cancel if: temp below 25°F, above 95°F, lightning, or air quality index > 150.",
        "response": "State licensing requires a minimum of 60 minutes of outdoor play daily, weather permitting. "
                    "We go outside twice daily (10:00 AM and 3:00 PM).\n\n"
                    "Outdoor play is canceled if:\n"
                    "• Temperature below 25°F or above 95°F\n"
                    "• Active precipitation (rain, snow)\n"
                    "• Lightning within 10 miles\n"
                    "• Air Quality Index above 150\n\n"
                    "Check /activity for today's schedule. On bad weather days, we use the indoor gross motor room.",
    },
    {
        "id": "incident_reporting",
        "category": "Compliance",
        "keywords": ["incident", "injury", "report", "accident", "documentation", "parent notify"],
        "question_examples": [
            "How do we report an incident?",
            "What's the injury reporting procedure?",
            "When do we notify parents of incidents?",
        ],
        "rule": "All incidents must be documented within 24 hours. "
                "Parents must be notified immediately for any injury requiring medical attention. "
                "Minor incidents: notify parent at pick-up. "
                "Serious incidents: notify licensing within 24 hours.",
        "response": "Per state licensing incident reporting requirements:\n"
                    "• All incidents documented in Grist within 24 hours\n"
                    "• Minor injuries: Parent notified at pick-up (documented in incident record)\n"
                    "• Injuries requiring medical attention: Parent notified immediately\n"
                    "• Serious incidents (hospitalization, emergency services): Notify state licensing within 24 hours\n"
                    "• Incident records must include: date, time, description, action taken, "
                    "staff involved, and parent notification time\n\n"
                    "Use /observe command for minor notes or log incidents in the Grist Incidents table.",
    },
    {
        "id": "subsidy_compliance",
        "category": "Subsidies & Billing",
        "keywords": ["subsidy", "subsidies", "ccap", "head start", "reauthorization", "renewal"],
        "question_examples": [
            "How do subsidies work?",
            "What's the reauthorization process?",
            "When do subsidies need to be renewed?",
        ],
        "rule": "CCAP reauthorization: annually with updated income verification. "
                "Head Start: annual recertification. "
                "All subsidy documentation must be maintained for 5 years per state audit requirements.",
        "response": "Subsidy compliance requirements:\n"
                    "• CCAP State Subsidy: Annual reauthorization with updated income verification. "
                    "Currently 3 families enrolled ($850/mo each).\n"
                    "• Head Start (Federal): Annual recertification. 1 family enrolled ($1,100/mo).\n"
                    "• All documentation must be retained for 5 years per state audit requirements.\n"
                    "• Case worker contact info must be maintained in Grist.\n\n"
                    "Use /subsidies to check current subsidy status and upcoming deadlines. "
                    "⚠ Isabella Brown's CCAP reauthorization is due June 5 — 9 days from now.",
    },
]


def search_regulations(query: str) -> list:
    """Score regulations by keyword and question-example overlap with *query*. Returns top 3."""
    query_lower = query.lower()
    scored = []
    for reg in REGULATIONS:
        score = 0
        for kw in reg["keywords"]:
            if kw in query_lower:
                score += 1
        # Bonus for question matches
        for q in reg["question_examples"]:
            if any(word in query_lower for word in q.lower().split() if len(word) > 3):
                score += 0.5
        if score > 0:
            scored.append((score, reg))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [reg for score, reg in scored[:3]]


def get_regulatory_answer(query: str) -> str | None:
    """Return the best formatted regulatory response for *query*, or None if no match."""
    matches = search_regulations(query)
    if not matches:
        return None
    best = matches[0]
    response = f"📋 *{best['category']}*\n\n{best['response']}"
    if len(matches) > 1:
        response += f"\n\n_Also relevant: {', '.join(m['category'] for m in matches[1:])}_"
    return response
