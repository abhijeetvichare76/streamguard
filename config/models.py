"""Structured data models for agent communication.

These Pydantic models ensure type safety and validation across the agent workflow.
"""
from typing import Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator
from enum import Enum


class RiskLevel(str, Enum):
    """Risk assessment levels."""
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Recommendation(str, Enum):
    """Investigation recommendations."""
    APPROVE = "APPROVE"
    HOLD_FOR_REVIEW = "HOLD_FOR_REVIEW"
    BLOCK = "BLOCK"


class Decision(str, Enum):
    """Final judgment decisions."""
    APPROVE = "APPROVE"  # Deprecated - use SAFE instead
    SAFE = "SAFE"  # Transaction approved and safe to proceed
    BLOCK = "BLOCK"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


# Tool Result Models

class UserProfile(BaseModel):
    """User history profile from BigQuery."""
    user_id: str
    age_group: Optional[str] = None
    account_tenure_days: Optional[int] = None
    avg_transfer_amount: Optional[float] = None
    behavioral_segment: Optional[str] = None
    previous_violations: int = Field(default=0, description="Count of previous security violations")
    status: Optional[str] = None  # For error states like "not_found"


class BeneficiaryRisk(BaseModel):
    """Beneficiary account risk assessment."""
    account_id: str
    account_age_hours: Optional[float] = None
    risk_score: Optional[int] = Field(default=50, ge=0, le=100)
    linked_to_flagged_device: Optional[bool] = False
    status: Optional[str] = None


class SessionContext(BaseModel):
    """Mobile banking session behavioral context."""
    transaction_id: str
    user_id: str
    session_id: Optional[str] = None
    is_call_active: bool = False
    behavioral_metrics: Optional[Dict[str, Any]] = None
    device_context: Optional[Dict[str, Any]] = None
    risk_signals: Optional[Dict[str, Any]] = None
    status: Optional[str] = None


# Detective Output Model

class InvestigationReport(BaseModel):
    """Structured output from Detective Agent."""
    transaction_id: str
    user_profile: UserProfile
    beneficiary_analysis: BeneficiaryRisk
    session_analysis: SessionContext

    # Synthesized assessment
    risk_score: int = Field(ge=0, le=100, description="Overall risk score 0-100")
    risk_level: RiskLevel
    reasoning: str = Field(min_length=10, description="1-2 sentences explaining the assessment")
    recommendation: Recommendation

    # Key security flags
    security_flags: Dict[str, bool] = Field(
        default_factory=dict,
        description="Key security indicators like active_voice_call, suspect_device, etc."
    )

    @field_validator('reasoning')
    @classmethod
    def validate_reasoning(cls, v: str) -> str:
        """Ensure reasoning is substantive."""
        if len(v.split()) < 5:
            raise ValueError("Reasoning must be at least 5 words")
        return v

    def to_text_summary(self) -> str:
        """Generate human-readable summary for logging/display."""
        return f"""
INVESTIGATION REPORT
====================
Transaction ID: {self.transaction_id}
User Profile: {self.user_profile.behavioral_segment or 'Unknown'} (Tenure: {self.user_profile.account_tenure_days or 0} days)
Previous Violations: {self.user_profile.previous_violations}
Beneficiary Risk Score: {self.beneficiary_analysis.risk_score}/100
Session Flags: Call Active={self.session_analysis.is_call_active}
Risk Score: {self.risk_score}/100
Risk Level: {self.risk_level.value}
Reasoning: {self.reasoning}
Recommendation: {self.recommendation.value}
"""


# Judge Output Model

class JudgmentDecision(BaseModel):
    """Structured output from Judge Agent."""
    decision: Decision
    policy_applied: int = Field(ge=1, le=5, description="Policy number (1-5) that triggered this decision")
    reasoning: str = Field(min_length=10, description="Why this decision was made")
    action_required: str = Field(min_length=5, description="Specific next step")
    human_override_allowed: bool = Field(description="Whether a human can override this decision")
    confidence: int = Field(ge=0, le=100, description="Confidence in this decision (0-100%)")

    # Context from investigation
    transaction_id: str
    risk_score: int = Field(ge=0, le=100)

    @field_validator('reasoning')
    @classmethod
    def validate_reasoning(cls, v: str) -> str:
        """Ensure reasoning is substantive."""
        if len(v.split()) < 5:
            raise ValueError("Reasoning must be at least 5 words")
        return v

    def to_text_summary(self) -> str:
        """Generate human-readable summary for logging/display."""
        return f"""
JUDGMENT
========
Decision: {self.decision.value}
Policy Applied: #{self.policy_applied}
Reasoning: {self.reasoning}
Action Required: {self.action_required}
Human Override Allowed: {'YES' if self.human_override_allowed else 'NO'}
Confidence: {self.confidence}%
"""


# Tool Call Validation

class ToolCallResult(BaseModel):
    """Wrapper for validating tool call results."""
    tool_name: str
    success: bool
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    latency_ms: Optional[float] = None


class DetectiveToolCalls(BaseModel):
    """Validation that Detective called all required tools."""
    user_history: ToolCallResult
    beneficiary_risk: ToolCallResult
    session_context: ToolCallResult

    def all_succeeded(self) -> bool:
        """Check if all required tools succeeded."""
        return all([
            self.user_history.success,
            self.beneficiary_risk.success,
            self.session_context.success
        ])

    def get_failed_tools(self) -> list[str]:
        """Get list of failed tool names."""
        failed = []
        if not self.user_history.success:
            failed.append("user_history")
        if not self.beneficiary_risk.success:
            failed.append("beneficiary_risk")
        if not self.session_context.success:
            failed.append("session_context")
        return failed
