"""Input guardrails — run before any text reaches the LLM."""

import re

from servewell.models.schemas import GuardrailResult

PHONE_RE = re.compile(r"\+?\d{1,3}[-\s]?\d{5}[-\s]?\d{5}\b|\b\d{10}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")

NON_IT_TERMS = [
    "salary", "payroll", "payslip", "pay slip", "leave balance", "leave request", "hr ",
    "personal card", "my card", "reimbursement", "shift swap", "appraisal", "bonus",
]

INJECTION_PATTERNS = [
    r"ignore (all|any|previous|the above) (instructions|rules)",
    r"you are now",
    r"system prompt",
    r"disregard .* (policy|instructions)",
    r"act as (an? )?(admin|administrator|developer)",
]

PRINTER_TERMS = [
    "printer", "print", "receipt", "epson", "tm-t88", "star mc", "starmc", "paper jam",
    "kitchen ticket", "kot", "thermal", "spooler",
]


def mask_pii(text: str) -> tuple[str, int]:
    count = 0
    for regex, token in ((EMAIL_RE, "[EMAIL]"), (CARD_RE, "[CARD]"), (PHONE_RE, "[PHONE]")):
        text, n = regex.subn(token, text)
        count += n
    return text, count


def non_it_signals(text: str) -> list[str]:
    lower = f" {text.lower()} "
    return [t.strip() for t in NON_IT_TERMS if t in lower]


def injection_signals(text: str) -> list[str]:
    return [p for p in INJECTION_PATTERNS if re.search(p, text, re.IGNORECASE)]


def printer_signal(text: str) -> int:
    lower = text.lower()
    return sum(1 for t in PRINTER_TERMS if t in lower)


def run_input_checks(subject: str, description: str) -> tuple[str, str, list[GuardrailResult], dict]:
    """Returns masked subject/description, check results, and raw signals for later nodes."""
    subj, n1 = mask_pii(subject)
    desc, n2 = mask_pii(description)
    text = f"{subject}\n{description}"
    non_it = non_it_signals(text)
    injection = injection_signals(text)
    results = [
        GuardrailResult(name="PII masking", passed=True,
                        detail=f"{n1 + n2} PII value(s) masked before LLM call" if n1 + n2 else "No PII found"),
        GuardrailResult(name="Prompt-injection scan", passed=not injection,
                        detail=f"Suspicious patterns: {injection}" if injection else "Clean"),
        GuardrailResult(name="Non-IT intent scan", passed=not non_it,
                        detail=f"Non-IT terms found: {non_it}" if non_it else "No non-IT terms"),
    ]
    return subj, desc, results, {"non_it_terms": non_it, "injection": injection,
                                 "printer_signal": printer_signal(text)}
