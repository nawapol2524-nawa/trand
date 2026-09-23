"""
Explicit AI Error Classifications — Phase L requirement.
Every failure mode is categorized distinctly. No generic swallowing of errors.
"""
from __future__ import annotations


class AIError(Exception):
    """Base exception for all AI layer errors."""
    def __init__(self, message: str, code: str = "UNKNOWN_ERROR", details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


class NetworkError(AIError):
    """Network connection failure or DNS resolution error."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="NETWORK_ERROR", details=details)


class TimeoutError(AIError):
    """AI invocation exceeded AI_TIMEOUT_SECONDS."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="TIMEOUT", details=details)


class RateLimit429Error(AIError):
    """HTTP 429: Rate limit or credit quota exhaustion."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="429_RATE_LIMIT", details=details)


class Provider5xxError(AIError):
    """HTTP 5xx: Upstream provider server error."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="5XX_PROVIDER_ERROR", details=details)


class AuthError(AIError):
    """HTTP 401/403: Invalid API key, unauthorized, or forbidden."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="AUTH_ERROR", details=details)


class InvalidResponseError(AIError):
    """Provider response body is not valid JSON or completely empty."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="INVALID_RESPONSE", details=details)


class SchemaError(AIError):
    """JSON response does not adhere to required TradeProposal schema."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="SCHEMA_ERROR", details=details)


class ModelError(AIError):
    """Provider returned a model execution error or refusal."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="MODEL_ERROR", details=details)


class StaleResponseError(AIError):
    """AI proposal arrived after the candle period or market context expired."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="STALE_RESPONSE", details=details)


class UnknownError(AIError):
    """Unclassified failure."""
    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message, code="UNKNOWN_ERROR", details=details)
