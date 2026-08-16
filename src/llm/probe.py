"""Live Provider Probe for AI Intelligence Ingestion Pipeline.

Performs exactly ONE minimal verification request per configured provider:
1. Gemini: gemini-2.5-flash
2. Groq: llama-3.1-8b-instant
3. Cerebras: gpt-oss-120b (or active available Cerebras model)

Outputs clean status table without exposing any secret keys:
| Provider | Model | Configured | Result |

Usage:
    python -m src.llm.probe
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

try:
    import httpx
except ImportError:
    httpx = None

try:
    from litellm import completion
except ImportError:
    completion = None


def mask_key(key: str) -> str:
    """Return yes/no configuration status without exposing credentials."""
    return "yes" if bool(key and key.strip()) else "no"


def discover_cerebras_models(api_key: str) -> list:
    """Query Cerebras /v1/models endpoint for available production models."""
    if not api_key:
        return []
    url = "https://api.cerebras.ai/v1/models"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        if httpx:
            resp = httpx.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id", "") for m in data.get("data", [])]
                if models:
                    return models
        else:
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    models = [m.get("id", "") for m in data.get("data", [])]
                    if models:
                        return models
    except Exception:
        pass
    return ["gpt-oss-120b", "llama3.1-8b", "llama3.1-70b", "llama-3.3-70b"]


def execute_single_probe(provider: str, model_tag: str, api_key: str) -> tuple:
    """Execute exactly ONE tiny test request (Reply 'OK') with correct auth headers."""
    if not api_key:
        return False, "NOT_CONFIGURED"

    prov = provider.lower()
    clean_model = model_tag.strip()

    # 1. Gemini with OAuth Bearer Token vs API Key
    if prov == "gemini":
        model_name = clean_model
        if model_name.startswith("gemini/"):
            model_name = model_name.replace("gemini/", "")
        if not model_name.startswith("models/"):
            rest_model = f"models/{model_name}"
        else:
            rest_model = model_name

        is_bearer = api_key.startswith("AQ.") or api_key.startswith("ya29.")

        # REST direct probe
        if httpx:
            try:
                if is_bearer:
                    url = f"https://generativelanguage.googleapis.com/v1beta/{rest_model}:generateContent"
                    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
                else:
                    url = f"https://generativelanguage.googleapis.com/v1beta/{rest_model}:generateContent?key={api_key}"
                    headers = {"Content-Type": "application/json"}

                resp = httpx.post(
                    url,
                    headers=headers,
                    json={"contents": [{"parts": [{"text": "Reply only with OK"}]}]},
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    return True, "OK"
                elif resp.status_code == 429:
                    return True, "429_RATE_LIMITED"
                elif resp.status_code == 404:
                    return False, f"FAIL (404_MODEL_NOT_FOUND)"
                else:
                    return False, f"FAIL (HTTP_{resp.status_code})"
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    return True, "429_RATE_LIMITED"

        # Fallback to LiteLLM
        if completion:
            try:
                extra_headers = {"Authorization": f"Bearer {api_key}"} if is_bearer else None
                litellm_model = f"gemini/{model_name.replace('models/', '')}"
                kwargs = {
                    "model": litellm_model,
                    "messages": [{"role": "user", "content": "Reply only with OK"}],
                    "max_tokens": 5,
                    "timeout": 15,
                }
                if is_bearer:
                    kwargs["extra_headers"] = extra_headers
                else:
                    kwargs["api_key"] = api_key
                response = completion(**kwargs)
                return True, "OK"
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    return True, "429_RATE_LIMITED"
                return False, f"FAIL ({type(e).__name__})"

    # 2. Cerebras with Authorization: Bearer {CEREBRAS_API_KEY}
    elif prov == "cerebras":
        model_id = clean_model.replace("cerebras/", "")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # Try LiteLLM first
        if completion:
            try:
                response = completion(
                    model=f"cerebras/{model_id}",
                    messages=[{"role": "user", "content": "Reply only with OK"}],
                    api_key=api_key,
                    extra_headers=headers,
                    max_tokens=5,
                    timeout=15,
                )
                return True, "OK"
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    return True, "429_RATE_LIMITED"

        # Direct REST fallback
        if httpx:
            try:
                resp = httpx.post(
                    "https://api.cerebras.ai/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": model_id,
                        "messages": [{"role": "user", "content": "Reply only with OK"}],
                        "max_tokens": 5,
                    },
                    timeout=12.0,
                )
                if resp.status_code == 200:
                    return True, "OK"
                elif resp.status_code == 429:
                    return True, "429_RATE_LIMITED"
                return False, f"FAIL (HTTP_{resp.status_code})"
            except Exception as e:
                return False, f"FAIL ({type(e).__name__})"

    # 3. Groq (OpenAI-compatible)
    elif prov == "groq":
        model_id = clean_model.replace("groq/", "")
        if completion:
            try:
                response = completion(
                    model=f"groq/{model_id}",
                    messages=[{"role": "user", "content": "Reply only with OK"}],
                    api_key=api_key,
                    max_tokens=5,
                    timeout=15,
                )
                return True, "OK"
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    return True, "429_RATE_LIMITED"
                return False, f"FAIL ({type(e).__name__})"

    # 4. OpenRouter (OpenAI-compatible)
    elif prov == "openrouter":
        model_id = clean_model.replace("openrouter/", "")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "HTTP-Referer": "https://localhost",
            "X-Title": "AetheriaInference",
            "Content-Type": "application/json",
        }
        if httpx:
            try:
                resp = httpx.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": model_id if model_id else "openrouter/free",
                        "messages": [{"role": "user", "content": "Reply only with OK"}],
                        "max_tokens": 5,
                    },
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    return True, "OK"
                elif resp.status_code == 429:
                    return True, "429_RATE_LIMITED"
                return False, f"FAIL (HTTP_{resp.status_code})"
            except Exception as e:
                return False, f"FAIL ({type(e).__name__})"

        if completion:
            try:
                full_model = f"openrouter/{model_id}" if not model_id.startswith("openrouter/") else model_id
                response = completion(
                    model=full_model,
                    messages=[{"role": "user", "content": "Reply only with OK"}],
                    api_key=api_key,
                    extra_headers=headers,
                    max_tokens=5,
                    timeout=15,
                )
                return True, "OK"
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    return True, "429_RATE_LIMITED"
                return False, f"FAIL ({type(e).__name__})"

    return False, "NO_CLIENT"


def run_probe():
    """Run verification for configured fallback chain providers."""
    print("\n" + "=" * 80)
    print("🚀 AETHERIA // LIVE PROVIDER PROBE")
    print("=" * 80)

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    cerebras_key = (
        os.getenv("CEREBRAS_API_KEY")
        or os.getenv("CEREBAS_API_KEY", "")
    ).strip()

    groq_model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
    openrouter_model = os.getenv("OPENROUTER_MODEL", "openrouter/free")
    gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    cerebras_model = (
        os.getenv("CEREBRAS_MODEL")
        or os.getenv("CEREBAS_MODEL", "zai-glm-4.7")
    )

    results = []

    # 1. Groq (Primary High-Speed Provider)
    gr_ok, gr_res = test_single_probe("groq", groq_model, groq_key)
    results.append({
        "provider": "Groq",
        "model": groq_model,
        "configured": mask_key(groq_key),
        "result": gr_res,
    })

    # 2. OpenRouter (Secondary Resilient Fallback)
    or_ok, or_res = test_single_probe("openrouter", openrouter_model, openrouter_key)
    results.append({
        "provider": "OpenRouter",
        "model": openrouter_model,
        "configured": mask_key(openrouter_key),
        "result": or_res,
    })

    # 3. Gemini (if configured)
    if gemini_key:
        g_ok, g_res = test_single_probe("gemini", gemini_model, gemini_key)
        results.append({
            "provider": "Gemini",
            "model": gemini_model,
            "configured": mask_key(gemini_key),
            "result": g_res,
        })

    # 4. Cerebras (if configured)
    if cerebras_key:
        c_ok, c_res = test_single_probe("cerebras", cerebras_model, cerebras_key)
        results.append({
            "provider": "Cerebras",
            "model": cerebras_model,
            "configured": mask_key(cerebras_key),
            "result": c_res,
        })

    # Print Table Formatted
    print("\n| Provider | Model | Configured | Result |")
    print("| :--- | :--- | :--- | :--- |")
    for r in results:
        print(f"| {r['provider']:<12} | {r['model']:<28} | {r['configured']:<10} | {r['result']:<14} |")
    print("=" * 80 + "\n")

    return results


if __name__ == "__main__":
    run_probe()
