"""
Concrete AI Provider Implementations.
Includes:
  1. OpenAIProvider: Live LLM provider with JSON mode, bounded retries & timeout
  2. GroqProvider: Ultra-fast LLM provider (OpenAI-compatible endpoint)
  3. OfflineDeterministicAIProvider: Zero-cost rule-based provider for backtests and quota fallbacks
  4. MockAIProvider: Mockable provider for isolated unit tests
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from src.ai.base import BaseAIProvider
from src.ai.errors import (
    AIError,
    AuthError,
    InvalidResponseError,
    NetworkError,
    Provider5xxError,
    RateLimit429Error,
    SchemaError,
    TimeoutError,
    UnknownError,
)
from src.ai.schemas import (
    AIContext,
    HealthCheckResult,
    ProposalDecision,
    ProviderCapabilities,
    TradeProposal,
)
from src.core.models import Direction

AI_SYSTEM_PROMPT = """You are a quantitative market structure evaluator.
Evaluate the market context and generate a TradeProposal.
You must respond with ONLY a single JSON object matching this schema:
{
  "decision": "APPROVE" | "REJECT" | "PASS",
  "direction": "LONG" | "SHORT" | "FLAT",
  "confidence": 0.0 to 1.0,
  "invalidation": "string describing market invalidation level or event",
  "rationale": "string concise analytical thesis",
  "scenario": "BULLISH_CONTINUATION" | "BEARISH_CONTINUATION" | "REVERSAL" | "RANGE" | "BREAKOUT_FAILURE" | "NO_TRADE"
}
Never include markdown code fences or conversational text. Output pure JSON only."""


class OfflineDeterministicAIProvider(BaseAIProvider):
    """
    Offline Rule-Based AI Provider.
    Zero external dependencies, zero API costs, zero latency, zero non-determinism.
    Used for historical backtests, test suites, and fallback when live API quota is exhausted.
    """

    def __init__(self, name: str = "offline_rules"):
        self._name = name

    @property
    def provider_name(self) -> str:
        return self._name

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            is_llm=False,
            supports_structured_output=True,
            supports_chat=False,
            supports_streaming=False,
            token_limits=0,
            default_timeout=0.01,
            api_category="OFFLINE_RULES",
        )

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(
            is_healthy=True,
            latency_ms=0.1,
            message="Offline deterministic provider ready",
        )

    def analyze(self, context: AIContext, trace_id: Optional[str] = None) -> TradeProposal:
        tid = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        now = datetime.now(tz=timezone.utc)

        # Deterministic context evaluation
        if context.news_state.get("high_impact_soon", False):
            return TradeProposal(
                decision=ProposalDecision.REJECT,
                direction=Direction.FLAT,
                symbol=context.symbol,
                confidence=1.0,
                entry_context=context.to_dict(),
                invalidation="High-impact news event window active",
                rationale="Deterministic rule: blackout window preceding high-impact news",
                scenario="NO_TRADE",
                timestamp=now,
                model_provider=self.provider_name,
                trace_id=tid,
            )

        if context.market_structure == "BOS_LONG" and context.trend == "BULLISH":
            return TradeProposal(
                decision=ProposalDecision.APPROVE,
                direction=Direction.LONG,
                symbol=context.symbol,
                confidence=0.85,
                entry_context=context.to_dict(),
                invalidation=f"Close below ATR trailing level ({context.price - context.atr * 1.5:.5f})",
                rationale="Confirmed bullish market structure with trend alignment and BOS",
                scenario="BULLISH_CONTINUATION",
                timestamp=now,
                model_provider=self.provider_name,
                trace_id=tid,
            )

        if context.market_structure == "BOS_SHORT" and context.trend == "BEARISH":
            return TradeProposal(
                decision=ProposalDecision.APPROVE,
                direction=Direction.SHORT,
                symbol=context.symbol,
                confidence=0.85,
                entry_context=context.to_dict(),
                invalidation=f"Close above ATR trailing level ({context.price + context.atr * 1.5:.5f})",
                rationale="Confirmed bearish market structure with trend alignment and BOS",
                scenario="BEARISH_CONTINUATION",
                timestamp=now,
                model_provider=self.provider_name,
                trace_id=tid,
            )

        # Reversal checks
        if context.rsi > 70.0 and context.market_structure != "BOS_LONG":
            return TradeProposal(
                decision=ProposalDecision.PASS,
                direction=Direction.FLAT,
                symbol=context.symbol,
                confidence=0.60,
                entry_context=context.to_dict(),
                invalidation="RSI overbought without confirmed breakdown",
                rationale="Overbought condition in ranging regime — awaiting confirmed structure",
                scenario="RANGE",
                timestamp=now,
                model_provider=self.provider_name,
                trace_id=tid,
            )

        return TradeProposal(
            decision=ProposalDecision.PASS,
            direction=Direction.FLAT,
            symbol=context.symbol,
            confidence=0.50,
            entry_context=context.to_dict(),
            invalidation="No structural catalyst present",
            rationale="No high-probability structural trigger identified",
            scenario="RANGE",
            timestamp=now,
            model_provider=self.provider_name,
            trace_id=tid,
        )


class OpenAIProvider(BaseAIProvider):
    """
    OpenAI Chat Completion Provider.
    Implements JSON mode with bounded retries, timeout, and explicit error taxonomy.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        base_url: str = "https://api.openai.com/v1",
        timeout_seconds: float = 5.0,
        max_retries: int = 2,
    ):
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    @property
    def provider_name(self) -> str:
        return f"openai/{self._model}"

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            is_llm=True,
            supports_structured_output=True,
            supports_chat=True,
            supports_streaming=True,
            token_limits=128000,
            default_timeout=self._timeout,
            api_category="LLM",
        )

    def health_check(self) -> HealthCheckResult:
        if not self._api_key or self._api_key.startswith("YOUR_"):
            return HealthCheckResult(False, 0.0, "API key not configured", code="NO_KEY")

        url = f"{self._base_url}/models"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {self._api_key}"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                elapsed = (time.perf_counter() - t0) * 1000.0
                return HealthCheckResult(True, round(elapsed, 2), "OpenAI models endpoint reached")
        except urllib.error.HTTPError as e:
            elapsed = (time.perf_counter() - t0) * 1000.0
            if e.code in (401, 403):
                return HealthCheckResult(False, elapsed, f"Auth Error ({e.code})", code="AUTH_ERROR")
            elif e.code == 429:
                return HealthCheckResult(False, elapsed, "Quota/Rate Limit (429)", code="RATE_LIMIT")
            return HealthCheckResult(False, elapsed, f"HTTP {e.code}", code="HTTP_ERROR")
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000.0
            return HealthCheckResult(False, elapsed, str(e), code="CONN_ERROR")

    def analyze(self, context: AIContext, trace_id: Optional[str] = None) -> TradeProposal:
        tid = trace_id or f"trace_{uuid.uuid4().hex[:12]}"
        now = datetime.now(tz=timezone.utc)

        if not self._api_key or self._api_key.startswith("YOUR_"):
            raise AuthError("OpenAI API key missing or unconfigured")

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": AI_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(context.to_dict())},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1,
            "max_tokens": 250,
        }

        data_bytes = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self._base_url}/chat/completions",
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
        )

        last_error: Optional[AIError] = None
        for attempt in range(1, self._max_retries + 2):
            try:
                with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    choice = resp_data["choices"][0]["message"]["content"]
                    parsed = json.loads(choice)

                    return TradeProposal(
                        decision=ProposalDecision(parsed["decision"]),
                        direction=Direction(parsed["direction"]),
                        symbol=context.symbol,
                        confidence=float(parsed.get("confidence", 0.0)),
                        entry_context=context.to_dict(),
                        invalidation=str(parsed.get("invalidation", "")),
                        rationale=str(parsed.get("rationale", "")),
                        scenario=str(parsed.get("scenario", "RANGE")),
                        timestamp=now,
                        model_provider=self.provider_name,
                        trace_id=tid,
                        raw_response=choice,
                    )

            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                if e.code == 429:
                    raise RateLimit429Error(f"OpenAI 429: {err_body}", details={"code": 429})
                elif e.code in (401, 403):
                    raise AuthError(f"OpenAI Auth failure ({e.code}): {err_body}", details={"code": e.code})
                elif 500 <= e.code < 600:
                    last_error = Provider5xxError(f"OpenAI 5xx error ({e.code}): {err_body}")
                else:
                    raise UnknownError(f"OpenAI HTTP {e.code}: {err_body}")

            except urllib.error.URLError as e:
                if "timed out" in str(e).lower():
                    last_error = TimeoutError(f"OpenAI request timed out after {self._timeout}s")
                else:
                    last_error = NetworkError(f"OpenAI network error: {e}")

            except (json.JSONDecodeError, KeyError) as e:
                raise SchemaError(f"Invalid response schema from OpenAI: {e}")

            except Exception as e:
                raise UnknownError(f"Unexpected OpenAI error: {e}")

            # Exponential backoff for retryable errors
            if attempt <= self._max_retries:
                time.sleep(0.5 * attempt)

        if last_error:
            raise last_error
        raise UnknownError("Exhausted retries without response")


class MockAIProvider(BaseAIProvider):
    """Mock Provider for deterministic unit tests."""

    def __init__(
        self,
        name: str = "mock_provider",
        canned_proposal: Optional[TradeProposal] = None,
        exception_to_raise: Optional[AIError] = None,
    ):
        self._name = name
        self.canned_proposal = canned_proposal
        self.exception_to_raise = exception_to_raise

    @property
    def provider_name(self) -> str:
        return self._name

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            is_llm=True,
            supports_structured_output=True,
            supports_chat=True,
            supports_streaming=False,
            token_limits=4096,
            default_timeout=1.0,
            api_category="MOCK",
        )

    def health_check(self) -> HealthCheckResult:
        return HealthCheckResult(True, 1.0, "Mock provider operational")

    def analyze(self, context: AIContext, trace_id: Optional[str] = None) -> TradeProposal:
        if self.exception_to_raise:
            raise self.exception_to_raise
        if self.canned_proposal:
            return self.canned_proposal

        return TradeProposal(
            decision=ProposalDecision.APPROVE,
            direction=Direction.LONG,
            symbol=context.symbol,
            confidence=0.9,
            entry_context=context.to_dict(),
            invalidation="Below 1.1400",
            rationale="Mock validation approved",
            scenario="BULLISH_CONTINUATION",
            timestamp=datetime.now(tz=timezone.utc),
            model_provider=self.provider_name,
            trace_id=trace_id or "mock_trace",
        )
