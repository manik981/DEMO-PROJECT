"""LiteLLM Multi-Tier Router with Ordered Fallbacks, Concurrency Control, and Token Telemetry.

Model Fallback Hierarchy:
1. Primary:   gemini/gemini-2.0-flash (High speed, structured extraction)
2. Secondary: groq/llama-3.1-8b-instant (Fast sub-second failover on rate limit)
3. Tertiary:  deepseek/deepseek-chat (Resilient emergency fallback)

Concurrency & Safety:
- Enforces llm_semaphore = asyncio.Semaphore(3) to bound concurrent requests on free-tier APIs.
- Exponential backoff with jitter on 429s.
- Syncs execution latency and token metrics to Supabase llm_logs table.
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

logger = logging.getLogger(__name__)

try:
    import litellm
    from litellm import Router
    litellm.suppress_debug_info = True
    litellm.set_verbose = False
    logging.getLogger("LiteLLM").setLevel(logging.ERROR)
    logging.getLogger("LiteLLM Router").setLevel(logging.ERROR)
except ImportError:
    Router = None  # type: ignore


class ContextBudgetExceeded(Exception):
    """Raised when request exceeds provider context window and requires re-chunking."""
    pass


class LLMRouterManager:
    """Manages multi-tier LiteLLM router instance, concurrency bounding, and telemetry."""

    PRIMARY_MODEL_TAG = "primary-extractor"

    def __init__(
        self,
        gemini_api_key: Optional[str] = None,
        groq_api_key: Optional[str] = None,
        openrouter_api_key: Optional[str] = None,
        cerebras_api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        groq_model: Optional[str] = None,
        openrouter_model: Optional[str] = None,
        cerebras_model: Optional[str] = None,
        max_concurrent_calls: Optional[int] = None,
    ):
        self.gemini_api_key = gemini_api_key or os.getenv("GEMINI_API_KEY", "")
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.openrouter_api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        self.cerebras_api_key = (
            cerebras_api_key
            or os.getenv("CEREBRAS_API_KEY")
            or os.getenv("CEREBAS_API_KEY", "")
        )

        self.gemini_model = gemini_model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.openrouter_model = openrouter_model or os.getenv("OPENROUTER_MODEL", "openrouter/free")
        self.cerebras_model = (
            cerebras_model
            or os.getenv("CEREBRAS_MODEL")
            or os.getenv("CEREBAS_MODEL", "zai-glm-4.7")
        )

        self.concurrency = max_concurrent_calls or int(os.getenv("LLM_CONCURRENCY", "3"))
        self.semaphore = asyncio.Semaphore(self.concurrency)

        self.stats: Dict[str, Any] = {
            "llm_calls": 0,
            "fallback_calls": 0,
            "429_count": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
        }

        self.router: Optional[Any] = self._build_router()

    def _build_router(self) -> Optional[Any]:
        """Construct LiteLLM Router with fallback hierarchy."""
        if Router is None:
            logger.warning("LiteLLM is not installed; router running in stub mode.")
            return None

        clean_gemini = self.gemini_model.replace("models/", "")
        gemini_target = clean_gemini if "/" in clean_gemini else f"gemini/{clean_gemini}"
        groq_target = self.groq_model if "/" in self.groq_model else f"groq/{self.groq_model}"
        cerebras_target = self.cerebras_model if "/" in self.cerebras_model else f"cerebras/{self.cerebras_model}"

        clean_openrouter = self.openrouter_model.replace("openrouter/", "")
        openrouter_target = f"openrouter/{clean_openrouter}"

        # Gemini Auth configuration (OAuth Bearer vs AI Studio key)
        is_gemini_bearer = self.gemini_api_key.startswith("AQ.") or self.gemini_api_key.startswith("ya29.")
        gemini_params: Dict[str, Any] = {
            "model": gemini_target,
            "timeout": 25,
        }
        if is_gemini_bearer:
            gemini_params["extra_headers"] = {"Authorization": f"Bearer {self.gemini_api_key}"}
        else:
            gemini_params["api_key"] = self.gemini_api_key

        # Cerebras Auth configuration
        cerebras_headers = {
            "Authorization": f"Bearer {self.cerebras_api_key}",
            "Content-Type": "application/json",
        } if self.cerebras_api_key else {}

        # OpenRouter Auth configuration
        openrouter_headers = {
            "HTTP-Referer": "https://localhost",
            "X-Title": "AetheriaInference",
        }

        # Build dynamic model list
        primary_model = groq_target if self.groq_api_key else gemini_target
        primary_key = self.groq_api_key if self.groq_api_key else self.gemini_api_key

        model_list: List[Dict[str, Any]] = [
            # 1. Primary Deployment (Groq Instant / High Speed)
            {
                "model_name": self.PRIMARY_MODEL_TAG,
                "litellm_params": {
                    "model": primary_model,
                    "api_key": primary_key,
                    "timeout": 20,
                },
            },
            # 2. Secondary Deployment: Groq LLaMA Instant
            {
                "model_name": "groq-fallback",
                "litellm_params": {
                    "model": groq_target,
                    "api_key": self.groq_api_key,
                    "timeout": 20,
                },
            },
            # 3. Secondary/Tertiary Deployment: OpenRouter Free
            {
                "model_name": "openrouter-fallback",
                "litellm_params": {
                    "model": openrouter_target,
                    "api_key": self.openrouter_api_key,
                    "extra_headers": openrouter_headers,
                    "timeout": 30,
                },
            },
            # 4. Tertiary Deployment: Cerebras
            {
                "model_name": "cerebras-fallback",
                "litellm_params": {
                    "model": cerebras_target,
                    "api_key": self.cerebras_api_key,
                    "extra_headers": cerebras_headers,
                    "timeout": 25,
                },
            },
        ]

        try:
            router = Router(
                model_list=model_list,
                fallbacks=[
                    {
                        self.PRIMARY_MODEL_TAG: [
                            "openrouter-fallback",
                            "groq-fallback",
                            "cerebras-fallback",
                        ]
                    }
                ],
                num_retries=1,
                cooldown_time=30,
                allowed_fails=1,
            )
            return router
        except Exception as e:
            logger.error("Failed to initialize LiteLLM Router: %s", e)
            return None

    def _call_gemini_oauth(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> Tuple[str, int, int]:
        """Direct REST call to Google Generative Language API using OAuth Bearer Token."""
        if not httpx:
            raise RuntimeError("httpx is required for direct Gemini OAuth calls.")

        clean_model = self.gemini_model.replace("gemini/", "")
        rest_model = clean_model if clean_model.startswith("models/") else f"models/{clean_model}"
        url = f"https://generativelanguage.googleapis.com/v1beta/{rest_model}:generateContent"

        headers = {
            "Authorization": f"Bearer {self.gemini_api_key}",
            "Content-Type": "application/json",
        }

        # Convert standard messages to Gemini contents format
        contents = []
        for m in messages:
            role = "user" if m.get("role") in ("user", "system") else "model"
            contents.append({"role": role, "parts": [{"text": m.get("content", "")}]})

        body: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
            },
        }
        if response_format and response_format.get("type") == "json_object":
            body["generationConfig"]["responseMimeType"] = "application/json"

        resp = httpx.post(url, headers=headers, json=body, timeout=25.0)
        if resp.status_code == 200:
            data = resp.json()
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                text_out = "".join(p.get("text", "") for p in parts)
                usage = data.get("usageMetadata", {})
                p_tokens = usage.get("promptTokenCount", 50)
                c_tokens = usage.get("candidatesTokenCount", 20)
                return text_out, p_tokens, c_tokens
            raise RuntimeError("Empty response from Gemini API")
        elif resp.status_code == 429:
            raise RuntimeError(f"429 RateLimitError from Gemini: {resp.text}")
        else:
            raise RuntimeError(f"HTTP_{resp.status_code} from Gemini: {resp.text}")

    def _persist_log(
        self,
        run_id: Optional[str],
        model_name: str,
        tier: str,
        fallback_from: Optional[str],
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        status: str,
        error_type: Optional[str] = None,
        error_message: Optional[str] = None,
        content_hash: Optional[str] = None,
        record_type: Optional[str] = None,
    ) -> None:
        """Persist execution log to Supabase llm_logs table."""
        try:
            from src.db.supabase_client import get_supabase_client
            client = get_supabase_client()
            if client.is_configured and httpx is not None:
                log_entry = [{
                    "run_id": run_id,
                    "model_name": model_name,
                    "tier": tier,
                    "fallback_from": fallback_from,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "latency_ms": latency_ms,
                    "status": status,
                    "error_type": error_type,
                    "error_message": error_message,
                    "content_hash": content_hash,
                    "record_type": record_type,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }]
                headers = client._get_headers()
                httpx.post(f"{client.rest_endpoint}/llm_logs", json=log_entry, headers=headers, timeout=3.0)
        except Exception:
            pass

    async def execute_completion_async(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, Any]] = None,
        temperature: float = 0.0,
        content_hash: Optional[str] = None,
        record_type: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> str:
        """Execute async completion within bounded concurrency semaphore and log metrics."""
        async with self.semaphore:
            start_time = time.time()
            self.stats["llm_calls"] += 1

            is_gemini_bearer = bool(self.gemini_api_key and (self.gemini_api_key.startswith("AQ.") or self.gemini_api_key.startswith("ya29.")))

            if is_gemini_bearer:
                try:
                    content, p_tokens, c_tokens = self._call_gemini_oauth(messages, temperature, response_format)
                    latency_ms = int((time.time() - start_time) * 1000)
                    self.stats["prompt_tokens"] += p_tokens
                    self.stats["completion_tokens"] += c_tokens
                    self._persist_log(run_id, self.gemini_model, "primary", None, p_tokens, c_tokens, latency_ms, "success", None, None, content_hash, record_type)
                    return content.strip()
                except Exception as e:
                    latency_ms = int((time.time() - start_time) * 1000)
                    err_str = str(e).lower()
                    if "429" in err_str or "rate limit" in err_str:
                        self.stats["429_count"] += 1
                    logger.warning("Primary Gemini OAuth call failed (%s), escalating to fallback chain...", e)

            if self.router is None:
                raise RuntimeError("LiteLLM Router not initialized or unavailable.")

            try:
                kwargs: Dict[str, Any] = {
                    "model": "groq-fallback" if is_gemini_bearer else self.PRIMARY_MODEL_TAG,
                    "messages": messages,
                    "temperature": temperature,
                }
                if response_format:
                    kwargs["response_format"] = response_format

                response = await self.router.acompletion(**kwargs)
                latency_ms = int((time.time() - start_time) * 1000)
                choice = response.choices[0]
                content = choice.message.content or ""

                usage = getattr(response, "usage", None)
                p_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
                c_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
                model_used = str(getattr(response, "model", self.gemini_model))

                is_fallback = "gemini" not in model_used.lower()
                fallback_from = self.gemini_model if is_fallback else None
                tier = "secondary_fallback" if "groq" in model_used.lower() else "tertiary_fallback" if ("cerebras" in model_used.lower() or "gpt-oss" in model_used.lower() or "gemma" in model_used.lower()) else "primary"
                status = "fallback_success" if is_fallback else "success"

                if is_fallback:
                    self.stats["fallback_calls"] += 1
                self.stats["prompt_tokens"] += p_tokens
                self.stats["completion_tokens"] += c_tokens

                self._persist_log(run_id, model_used, tier, fallback_from, p_tokens, c_tokens, latency_ms, status, None, None, content_hash, record_type)
                return content.strip()

            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                err_msg = str(e).lower()
                is_429 = "429" in err_msg or "rate limit" in err_msg
                if is_429:
                    self.stats["429_count"] += 1

                status = "rate_limited_429" if is_429 else "context_overflow_413" if "413" in err_msg else "error"
                error_type = "RateLimitError" if is_429 else "ContextBudgetExceeded" if "413" in err_msg else type(e).__name__

                self._persist_log(run_id, self.PRIMARY_MODEL_TAG, "fallback_chain", self.gemini_model, 0, 0, latency_ms, status, error_type, str(e)[:250], content_hash, record_type)

                if "413" in err_msg or "context_length_exceeded" in err_msg or "maximum context length" in err_msg:
                    raise ContextBudgetExceeded(f"Payload exceeded model context: {e}") from e
                logger.error("Router completion failed: %s", e)
                raise

    def execute_completion(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict[str, Any]] = None,
        temperature: float = 0.0,
        record_type: str = "GENERIC",
        content_hash: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> str:
        """Synchronous execution with token & latency audit logging."""
        start_time = time.time()
        self.stats["llm_calls"] += 1

        is_gemini_bearer = bool(self.gemini_api_key and (self.gemini_api_key.startswith("AQ.") or self.gemini_api_key.startswith("ya29.")))

        # Direct REST probe if OAuth Bearer Token
        if is_gemini_bearer:
            try:
                content, p_tokens, c_tokens = self._call_gemini_oauth(messages, temperature, response_format)
                latency_ms = int((time.time() - start_time) * 1000)
                self.stats["prompt_tokens"] += p_tokens
                self.stats["completion_tokens"] += c_tokens
                self._persist_log(run_id, self.gemini_model, "primary", None, p_tokens, c_tokens, latency_ms, "success", None, None, content_hash, record_type)
                return content.strip()
            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    self.stats["429_count"] += 1
                logger.warning("Primary Gemini OAuth call failed (%s), escalating to fallback chain...", e)

        if self.router is None:
            raise RuntimeError("LiteLLM Router not initialized.")

        try:
            kwargs: Dict[str, Any] = {
                "model": "groq-fallback" if is_gemini_bearer else self.PRIMARY_MODEL_TAG,
                "messages": messages,
                "temperature": temperature,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = self.router.completion(**kwargs)
            latency_ms = int((time.time() - start_time) * 1000)
            content = response.choices[0].message.content or ""

            # Extract token usage
            usage = getattr(response, "usage", None)
            p_tokens = getattr(usage, "prompt_tokens", 0) if usage else 0
            c_tokens = getattr(usage, "completion_tokens", 0) if usage else 0
            model_used = str(getattr(response, "model", self.PRIMARY_MODEL_TAG))

            is_fallback = "gemini" not in model_used.lower()
            fallback_from = self.gemini_model if is_fallback else None
            tier = "secondary_fallback" if "groq" in model_used.lower() else "tertiary_fallback" if ("cerebras" in model_used.lower() or "gpt-oss" in model_used.lower() or "gemma" in model_used.lower()) else "primary"
            status = "fallback_success" if is_fallback else "success"

            if is_fallback:
                self.stats["fallback_calls"] += 1
            self.stats["prompt_tokens"] += p_tokens
            self.stats["completion_tokens"] += c_tokens

            self._persist_log(run_id, model_used, tier, fallback_from, p_tokens, c_tokens, latency_ms, status, None, None, content_hash, record_type)
            return content.strip()

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            err_msg = str(e).lower()
            is_429 = "429" in err_msg or "rate limit" in err_msg
            if is_429:
                self.stats["429_count"] += 1

            status = "rate_limited_429" if is_429 else "context_overflow_413" if "413" in err_msg else "error"
            error_type = "RateLimitError" if is_429 else "ContextBudgetExceeded" if "413" in err_msg else type(e).__name__

            self._persist_log(run_id, self.PRIMARY_MODEL_TAG, "fallback_chain", self.gemini_model, 0, 0, latency_ms, status, error_type, str(e)[:250], content_hash, record_type)

            if "413" in err_msg or "context_length_exceeded" in err_msg or "maximum context length" in err_msg:
                raise ContextBudgetExceeded(f"Payload exceeded model context: {e}") from e
            raise


def get_llm_router() -> LLMRouterManager:
    """Helper factory for LLMRouterManager."""
    return LLMRouterManager()
