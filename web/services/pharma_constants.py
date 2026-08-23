"""
Pharmaceutical terminology constants for query expansion.

This module centralizes domain-specific term mappings used to expand
search queries with relevant synonyms, improving recall in the hybrid
search engine.
"""

# Mapping of core pharmaceutical terms to their synonyms / related phrases.
# Keys are matched as whole-word patterns in the query; values are appended
# to the query string to broaden lexical coverage.
PHARMA_TERMS_EXPANSION: dict[str, list[str]] = {
    "side effects": [
        "adverse events",
        "adverse reactions",
        "safety concerns",
        "undesirable effects",
    ],
    "dosage": [
        "dose",
        "administration",
        "regimen",
        "dosing schedule",
        "posology",
    ],
    "safety": [
        "toxicity",
        "contraindications",
        "warnings",
        "precautions",
        "safety profile",
    ],
    "monitoring": [
        "surveillance",
        "observation",
        "follow-up",
        "patient monitoring",
        "safety monitoring",
    ],
    "reporting": [
        "notification",
        "documentation",
        "submission",
        "adverse event reporting",
        "case reporting",
    ],
    "signal": [
        "alert",
        "indication",
        "warning signal",
        "safety signal",
        "potential risk",
    ],
    "risk": [
        "hazard",
        "danger",
        "exposure",
        "potential harm",
        "risk factor",
    ],
    "risk management": [
        "risk mitigation",
        "risk assessment",
        "risk control",
        "risk evaluation",
        "RMP",
        "risk management plan",
    ],
    "audit": [
        "compliance review",
        "internal audit",
        "regulatory audit",
        "process audit",
        "inspection readiness",
    ],
    "inspection": [
        "site visit",
        "regulatory inspection",
        "compliance check",
        "audit review",
        "facility inspection",
    ],
    "compliance": [
        "adherence",
        "conformity",
        "obedience",
        "compliance monitoring",
        "regulatory compliance",
    ],
    "pv": [
        "pharmacovigilance",
        "drug safety",
        "medicine surveillance",
        "post-marketing safety",
    ],
    "lack of efficacy": [
        "ineffectiveness",
        "insufficient response",
        "suboptimal efficacy",
        "treatment failure",
    ],
    "quality": [
        "good manufacturing practices",
        "GMP",
        "quality control",
        "QC",
        "quality assurance",
        "QA",
        "product quality",
    ],
    "adverse event": [
        "adverse reaction",
        "side effect",
        "negative reaction",
        "AE",
        "ADR",
        "undesired effect",
    ],
    "clinical trial": [
        "clinical study",
        "clinical research",
        "clinical investigation",
        "interventional study",
        "trial protocol",
    ],
    "drug interaction": [
        "medication interaction",
        "pharmaceutical interaction",
        "medicine interaction",
        "DDI",
    ],
    "registration": [
        "marketing authorization",
        "MA",
        "drug approval",
        "product license",
        "registration process",
    ],
    "labeling": [
        "SPC",
        "summary of product characteristics",
        "PIL",
        "patient information leaflet",
        "product label",
        "package insert",
    ],
    "variation": [
        "post-approval change",
        "variation application",
        "label update",
        "manufacturing change",
    ],
    "gmp": [
        "good manufacturing practices",
        "manufacturing standards",
        "quality systems",
        "facility compliance",
    ],
    "gvp": [
        "good pharmacovigilance practices",
        "pv system",
        "pharmacovigilance guidelines",
        "drug safety standards",
    ],
}
