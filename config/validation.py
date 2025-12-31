"""Validation and error handling utilities for agent workflows."""
import time
from typing import Dict, Any, Optional, Callable, TypeVar
from functools import wraps
from config.models import InvestigationReport, JudgmentDecision

T = TypeVar('T')


class AgentValidationError(Exception):
    """Raised when agent output validation fails."""
    pass


class ToolCallError(Exception):
    """Raised when a required tool call fails or is missing."""
    pass


def validate_investigation_completeness(investigation: InvestigationReport) -> None:
    """Validate that investigation contains all required tool data.

    Args:
        investigation: The investigation report to validate

    Raises:
        ToolCallError: If required tool data is missing
    """
    errors = []

    # Check user_profile (from user_history tool)
    if not investigation.user_profile.user_id:
        errors.append("Missing user_id from user_history tool")

    # Check beneficiary_analysis (from beneficiary tool)
    if not investigation.beneficiary_analysis.account_id:
        errors.append("Missing account_id from beneficiary_risk tool")

    # Check session_analysis (from session_context tool)
    if not investigation.session_analysis.transaction_id:
        errors.append("Missing transaction_id from session_context tool")

    if errors:
        raise ToolCallError(
            f"Investigation incomplete - missing required tool data: {'; '.join(errors)}"
        )


def validate_judgment_policy(judgment: JudgmentDecision, investigation: InvestigationReport) -> None:
    """Validate that judgment correctly applied policies.

    This function compares the LLM's judgment against the rule-based policy engine
    to detect inconsistencies.

    Args:
        judgment: The judgment decision from Judge agent
        investigation: The investigation that informed the judgment

    Raises:
        AgentValidationError: If policy application is critically inconsistent
    """
    from config.policy_engine import get_policy_engine

    warnings = []

    # Get the policy engine's decision for comparison
    engine = get_policy_engine()
    expected_decision = engine.make_decision(investigation)

    # Compare decisions
    if judgment.decision != expected_decision.decision:
        warnings.append(
            f"Decision mismatch: Judge decided {judgment.decision.value}, "
            f"but policy engine expects {expected_decision.decision.value}"
        )

    # Compare policy numbers
    if judgment.policy_applied != expected_decision.policy_applied:
        warnings.append(
            f"Policy mismatch: Judge applied policy #{judgment.policy_applied}, "
            f"but policy engine expects policy #{expected_decision.policy_applied}"
        )

    # Policy-specific validation
    # Policy 1: CRITICAL FRAUD - active call or CRITICAL risk
    if (investigation.security_flags.get('active_voice_call', False) or
        investigation.risk_level.value == "CRITICAL"):
        if judgment.decision.value != "BLOCK":
            warnings.append(
                f"Policy 1 violation: CRITICAL fraud should BLOCK, got {judgment.decision.value}"
            )
        if judgment.policy_applied != 1:
            warnings.append(
                f"Policy 1 should be applied, but got policy #{judgment.policy_applied}"
            )
        if judgment.human_override_allowed is True:
            warnings.append(
                "Policy 1 violation: CRITICAL fraud should NOT allow human override"
            )

    # Policy 2: REPEAT OFFENDERS
    if investigation.user_profile.previous_violations >= 1:
        if judgment.decision.value != "BLOCK" and judgment.policy_applied not in [1]:
            # Allow if Policy 1 (higher priority) triggered
            warnings.append(
                f"Policy 2 violation: Repeat offender should BLOCK, got {judgment.decision.value}"
            )

    # Log warnings but don't raise - LLM may have valid reasoning
    for warning in warnings:
        print(f"⚠️ Policy validation warning: {warning}")

    # If there are critical mismatches, log the comparison
    if warnings:
        print(f"📊 Policy Engine Recommendation:")
        print(f"   Decision: {expected_decision.decision.value}")
        print(f"   Policy: #{expected_decision.policy_applied}")
        print(f"   Reasoning: {expected_decision.reasoning[:100]}...")


def retry_on_failure(
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
    exceptions: tuple = (Exception,)
):
    """Decorator to retry a function on failure with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_seconds: Initial backoff time in seconds
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Decorator function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = backoff_seconds * (2 ** attempt)
                        print(f"⚠️ Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                        time.sleep(wait_time)
                    else:
                        print(f"❌ All {max_retries} retries exhausted")

            raise last_exception

        return wrapper
    return decorator


async def retry_on_failure_async(
    max_retries: int = 3,
    backoff_seconds: float = 1.0,
    exceptions: tuple = (Exception,)
):
    """Async version of retry_on_failure decorator.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_seconds: Initial backoff time in seconds
        exceptions: Tuple of exception types to catch and retry

    Returns:
        Decorator function
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            import asyncio
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait_time = backoff_seconds * (2 ** attempt)
                        print(f"⚠️ Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                        await asyncio.sleep(wait_time)
                    else:
                        print(f"❌ All {max_retries} retries exhausted")

            raise last_exception

        return wrapper
    return decorator


def create_error_investigation(transaction_id: str, error_msg: str) -> Dict[str, Any]:
    """Create a fallback investigation report when Detective fails.

    Args:
        transaction_id: The transaction ID
        error_msg: The error message

    Returns:
        A minimal investigation dict for error handling
    """
    return {
        "transaction_id": transaction_id,
        "error": error_msg,
        "risk_score": 100,
        "risk_level": "CRITICAL",
        "recommendation": "BLOCK",
        "reasoning": f"Investigation failed due to error: {error_msg}"
    }


def create_error_judgment(transaction_id: str, error_msg: str) -> Dict[str, Any]:
    """Create a fallback judgment when Judge fails.

    Args:
        transaction_id: The transaction ID
        error_msg: The error message

    Returns:
        A minimal judgment dict for error handling
    """
    return {
        "transaction_id": transaction_id,
        "decision": "BLOCK",
        "policy_applied": 1,
        "reasoning": f"Judgment failed due to error: {error_msg}. Blocking as precaution.",
        "action_required": "Manual review required due to system error",
        "human_override_allowed": True,
        "confidence": 0,
        "risk_score": 100
    }


# ====================
# Output Validation Correction Examples
# ====================

COMMON_VALIDATION_ERRORS = {
    "missing_transaction_id": {
        "error": "Field 'transaction_id' is required",
        "bad_example": '{"user_profile": {...}, "risk_score": 85}',
        "good_example": '{"transaction_id": "tx_123", "user_profile": {...}, "risk_score": 85}',
        "correction": "Always include the transaction_id field from the input"
    },
    "invalid_risk_level": {
        "error": "Field 'risk_level' must be one of: LOW, MEDIUM, HIGH, CRITICAL",
        "bad_example": '{"risk_level": "Moderate", ...}',
        "good_example": '{"risk_level": "MEDIUM", ...}',
        "correction": "Use exact values: LOW, MEDIUM, HIGH, or CRITICAL"
    },
    "invalid_decision": {
        "error": "Field 'decision' must be one of: SAFE, BLOCK, ESCALATE_TO_HUMAN",
        "bad_example": '{"decision": "Deny", ...}',
        "good_example": '{"decision": "BLOCK", ...}',
        "correction": "Use exact values: SAFE, BLOCK, or ESCALATE_TO_HUMAN"
    },
    "missing_security_flags": {
        "error": "Field 'security_flags' is required and must be a dict",
        "bad_example": '{"risk_score": 85, "reasoning": "..."}',
        "good_example": '{"risk_score": 85, "security_flags": {"active_voice_call": true, ...}}',
        "correction": "Include all security_flags: active_voice_call, suspect_device, new_beneficiary, rushed_session, high_velocity, unusual_time, unusual_location"
    },
    "short_reasoning": {
        "error": "Field 'reasoning' must be at least 5 words",
        "bad_example": '{"reasoning": "High risk"}',
        "good_example": '{"reasoning": "High risk due to active call and new beneficiary account"}',
        "correction": "Provide detailed reasoning (1-2 sentences)"
    },
    "risk_score_out_of_range": {
        "error": "Field 'risk_score' must be between 0 and 100",
        "bad_example": '{"risk_score": 150, ...}',
        "good_example": '{"risk_score": 95, ...}',
        "correction": "Risk score must be an integer from 0 to 100"
    },
    "confidence_out_of_range": {
        "error": "Field 'confidence' must be between 0 and 100",
        "bad_example": '{"confidence": 200, ...}',
        "good_example": '{"confidence": 95, ...}',
        "correction": "Confidence must be an integer from 0 to 100"
    },
    "invalid_policy_number": {
        "error": "Field 'policy_applied' must be between 1 and 6",
        "bad_example": '{"policy_applied": 0, ...}',
        "good_example": '{"policy_applied": 1, ...}',
        "correction": "Policy number must be 1, 2, 3, 4, 5, or 6"
    },
}


def get_validation_hint(error_msg: str) -> Optional[str]:
    """Get a helpful hint for common validation errors.

    Args:
        error_msg: The validation error message

    Returns:
        A hint string, or None if no specific hint is available
    """
    error_lower = error_msg.lower()

    for error_type, info in COMMON_VALIDATION_ERRORS.items():
        if any(keyword in error_lower for keyword in error_type.split('_')):
            return f"""
Validation Error Hint:
----------------------
Error: {info['error']}

❌ Bad Example:
{info['bad_example']}

✅ Good Example:
{info['good_example']}

💡 Correction: {info['correction']}
"""

    return None


def validate_and_suggest(data: Dict[str, Any], model_class) -> Optional[Any]:
    """Validate data against a model and provide helpful suggestions on failure.

    Args:
        data: The data dictionary to validate
        model_class: The Pydantic model class to validate against

    Returns:
        The validated model instance, or None if validation fails
    """
    from pydantic import ValidationError

    try:
        return model_class(**data)
    except ValidationError as e:
        print(f"❌ Validation failed for {model_class.__name__}:")
        print(f"   {e}")

        # Try to provide hints for each error
        for error in e.errors():
            field = error.get('loc', ['unknown'])[0]
            error_type = error.get('type', '')
            msg = error.get('msg', '')

            hint = get_validation_hint(f"{field} {error_type} {msg}")
            if hint:
                print(hint)

        return None
