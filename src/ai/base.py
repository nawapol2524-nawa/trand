"""
Universal AI Provider Base Interface — Phase D requirement.
Decouples all strategy, risk, and backtesting layers from concrete AI backends.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.ai.schemas import AIContext, HealthCheckResult, ProviderCapabilities, TradeProposal


class BaseAIProvider(ABC):
    """
    Abstract AI Provider Interface.
    Must be implemented by any concrete AI backend (OpenAI, Groq, Offline, etc.)
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier for the provider (e.g. 'openai', 'groq', 'offline_rules')."""
        ...

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Return provider capabilities (LLM vs ML vs rules, token limits, timeouts)."""
        ...

    @abstractmethod
    def health_check(self) -> HealthCheckResult:
        """Perform an active connectivity and authentication health probe."""
        ...

    @abstractmethod
    def analyze(self, context: AIContext, trace_id: Optional[str] = None) -> TradeProposal:
        """
        Evaluate normalized context and produce a structured TradeProposal.
        Must raise specific AIError subclasses on failure.
        Never executes orders.
        """
        ...
