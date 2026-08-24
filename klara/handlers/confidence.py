"""Klara AI escalation confidence thresholds.

Implements the confidence-based escalation policy documented in
.loki/security/escalation-thresholds.md (T8.11).

Usage example::

    from klara.handlers.confidence import should_escalate

    escalate, reason = should_escalate(
        confidence=0.72,
        regulated=True,
        regulated_vertical="healthcare",
    )
    if escalate:
        await escalate_to_anthony(reason=reason, ...)
"""

# ---------------------------------------------------------------------------
# Confidence thresholds
# ---------------------------------------------------------------------------

THRESHOLD_AUTONOMOUS = 0.85          # standard: respond without flag
THRESHOLD_DEFERRED_REVIEW = 0.70     # standard: respond + async flag to Anthony
# Below 0.70: synchronous escalation

# Regulated-context floors (confidence must meet or exceed to respond autonomously)
REGULATED_FLOORS: dict[str, float] = {
    "standard": THRESHOLD_AUTONOMOUS,
    "hipaa": 0.90,
    "healthcare": 0.90,
    "soc2": 0.90,
    "iso27001": 0.90,
    "financial": 0.95,
    "finra": 0.95,
    "sec": 0.95,
    "legal": 0.95,
}


def should_escalate(
    confidence: float,
    regulated: bool = False,
    has_citations: bool = True,
    is_security_incident: bool = False,
    explicit_human_request: bool = False,
    regulated_vertical: str = "standard",
) -> tuple[bool, str]:
    """Determine whether this interaction should be escalated to a human.

    Parameters
    ----------
    confidence:
        KB match confidence, 0.0–1.0. Produced by the citation layer.
    regulated:
        True if the client is a regulated-context client (HIPAA, legal,
        financial). When True, the autonomous threshold is raised per
        ``regulated_vertical``.
    has_citations:
        False if the KB returned 0 citation results. Confidence is treated
        as 0.0 when this is False regardless of the ``confidence`` argument.
    is_security_incident:
        True if a security incident keyword was detected in the message
        (breach, ransomware, hacked, data leak, locked out of all systems).
    explicit_human_request:
        True if the user explicitly requested a human ("I want to talk to
        Anthony", "get me a human", "speak to someone").
    regulated_vertical:
        One of: "standard", "healthcare", "hipaa", "soc2", "iso27001",
        "financial", "finra", "sec", "legal". Controls the autonomous
        confidence floor when ``regulated=True``.

    Returns
    -------
    tuple[bool, str]
        ``(should_escalate, reason)`` — reason is a human-readable string
        explaining why escalation was (or was not) triggered.

    Examples
    --------
    >>> should_escalate(0.90)
    (False, 'confidence 0.90 >= threshold 0.85; autonomous response')

    >>> should_escalate(0.72)
    (False, 'confidence 0.72 in deferred-review zone [0.70, 0.85); flag for async review')

    >>> should_escalate(0.60)
    (True, 'confidence 0.60 < synchronous-escalation threshold 0.70')

    >>> should_escalate(0.90, regulated=True, regulated_vertical='healthcare')
    (True, 'regulated context (healthcare): confidence 0.90 < regulated floor 0.90')

    >>> should_escalate(0.95, regulated=True, regulated_vertical='healthcare')
    (False, 'confidence 0.95 >= regulated floor 0.90; autonomous response')

    >>> should_escalate(0.95, is_security_incident=True)
    (True, 'hard trigger: active security incident — always escalate')

    >>> should_escalate(0.95, explicit_human_request=True)
    (True, 'hard trigger: explicit human/Anthony request')

    >>> should_escalate(0.95, has_citations=False)
    (True, 'hard trigger: KB returned 0 citations — confidence treated as 0.0')
    """
    # ------------------------------------------------------------------
    # Hard triggers — override all confidence logic
    # ------------------------------------------------------------------

    if is_security_incident:
        return True, "hard trigger: active security incident — always escalate"

    if explicit_human_request:
        return True, "hard trigger: explicit human/Anthony request"

    if not has_citations:
        return True, "hard trigger: KB returned 0 citations — confidence treated as 0.0"

    # ------------------------------------------------------------------
    # Clamp confidence to [0.0, 1.0]
    # ------------------------------------------------------------------
    c = max(0.0, min(1.0, float(confidence)))

    # ------------------------------------------------------------------
    # Regulated-context threshold
    # ------------------------------------------------------------------
    if regulated:
        vertical = regulated_vertical.lower() if regulated_vertical else "standard"
        floor = REGULATED_FLOORS.get(vertical, REGULATED_FLOORS["standard"])
        if c < floor:
            return (
                True,
                f"regulated context ({vertical}): confidence {c:.2f} < regulated floor {floor:.2f}",
            )
        return (
            False,
            f"confidence {c:.2f} >= regulated floor {floor:.2f}; autonomous response",
        )

    # ------------------------------------------------------------------
    # Standard thresholds
    # ------------------------------------------------------------------
    if c < THRESHOLD_DEFERRED_REVIEW:
        return (
            True,
            f"confidence {c:.2f} < synchronous-escalation threshold {THRESHOLD_DEFERRED_REVIEW:.2f}",
        )

    if c < THRESHOLD_AUTONOMOUS:
        # Deferred-review zone — respond but flag for Anthony async review
        return (
            False,
            (
                f"confidence {c:.2f} in deferred-review zone "
                f"[{THRESHOLD_DEFERRED_REVIEW:.2f}, {THRESHOLD_AUTONOMOUS:.2f}); "
                "flag for async review"
            ),
        )

    return (
        False,
        f"confidence {c:.2f} >= threshold {THRESHOLD_AUTONOMOUS:.2f}; autonomous response",
    )


def is_deferred_review_zone(confidence: float) -> bool:
    """Return True if confidence is in the 70–84% deferred-review zone.

    Use this after ``should_escalate`` returns False to decide whether to
    append the deferred-review disclaimer to Klara AI's response.

    Parameters
    ----------
    confidence:
        KB match confidence, 0.0–1.0.
    """
    c = max(0.0, min(1.0, float(confidence)))
    return THRESHOLD_DEFERRED_REVIEW <= c < THRESHOLD_AUTONOMOUS
