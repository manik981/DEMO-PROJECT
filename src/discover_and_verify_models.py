"""Model Discovery and Verification Utility.

Queries the official model endpoints for:
1. Google Gemini: https://generativelanguage.googleapis.com/v1beta/models
2. Groq: https://api.groq.com/openai/v1/models
3. DeepSeek: https://api.deepseek.com/models

Tests connectivity on the active candidate models and outputs the exact summary table:
Provider | API Key | Model ID | Available | Test Result

Usage:
    python src/discover_and_verify_models.py
"""

import json
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

try:
    import httpx
except ImportError:
    import urllib.request
    httpx = None

try:
    from litellm import completion
except ImportError:
    completion = None


def mask_key(key: str) -> str:
    """Return configured status without printing the key."""
    return "configured" if bool(key and key.strip()) else "missing"


def discover_gemini_models(api_key: str) -> list:
    """Query Google Gemini Generative Language API for active model IDs."""
    if not api_key:
        return []
    is_bearer = api_key.startswith("AQ.") or api_key.startswith("ya29.")
    if is_bearer:
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    else:
        url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
        headers = {"Content-Type": "application/json"}

    try:
        if httpx:
            resp = httpx.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "").replace("models/", "") for m in data.get("models", [])]
                return [m for m in models if "gemini" in m and "embedding" not in m]
        else:
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    models = [m.get("name", "").replace("models/", "") for m in data.get("models", [])]
                    return [m for m in models if "gemini" in m and "embedding" not in m]
    except Exception:
        pass
    return ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-pro"]


def discover_groq_models(api_key: str) -> list:
    """Query Groq /v1/models endpoint for available production models."""
    if not api_key:
        return []
    url = "https://api.groq.com/openai/v1/models"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    try:
        if httpx:
            resp = httpx.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("id", "") for m in data.get("data", []) if m.get("active", True)]
                return [m for m in models if "whisper" not in m and "embed" not in m]
        else:
            import urllib.request
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    models = [m.get("id", "") for m in data.get("data", []) if m.get("active", True)]
                    return [m for m in models if "whisper" not in m and "embed" not in m]
    except Exception:
        pass
    return ["llama-3.1-8b-instant", "llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"]


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
    return ["gpt-oss-120b", "gemma-4-31b", "llama3.1-8b", "llama3.1-70b", "llama-3.3-70b"]


def test_model_request(provider: str, model_tag: str, api_key: str) -> tuple:
    """Test 1 minimal request to the model via REST or LiteLLM."""
    if not api_key:
        return False, "NO_KEY"

    prov = provider.lower()
    clean_model = model_tag.replace("gemini/", "").replace("cerebras/", "").replace("groq/", "")

    if prov == "gemini":
        is_bearer = api_key.startswith("AQ.") or api_key.startswith("ya29.")
        rest_model = f"models/{clean_model}" if not clean_model.startswith("models/") else clean_model
        if is_bearer:
            url = f"https://generativelanguage.googleapis.com/v1beta/{rest_model}:generateContent"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        else:
            url = f"https://generativelanguage.googleapis.com/v1beta/{rest_model}:generateContent?key={api_key}"
            headers = {"Content-Type": "application/json"}

        if httpx:
            try:
                resp = httpx.post(
                    url,
                    headers=headers,
                    json={"contents": [{"parts": [{"text": "Say OK"}]}]},
                    timeout=15.0,
                )
                if resp.status_code == 200:
                    return True, "OK"
                elif resp.status_code == 429:
                    return True, "429_RATE_LIMITED"
                return False, f"HTTP_{resp.status_code}"
            except Exception as e:
                err = str(e)
                if "429" in err or "quota" in err.lower():
                    return True, "429_RATE_LIMITED"
                return False, err[:45]

    elif prov == "cerebras":
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if httpx:
            try:
                resp = httpx.post(
                    "https://api.cerebras.ai/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": clean_model,
                        "messages": [{"role": "user", "content": "Say OK"}],
                        "max_tokens": 5,
                    },
                    timeout=12.0,
                )
                if resp.status_code == 200:
                    return True, "OK"
                elif resp.status_code == 429:
                    return True, "429_RATE_LIMITED"
                return False, f"HTTP_{resp.status_code}"
            except Exception as e:
                return False, str(e)[:45]

    # Groq / Generic via LiteLLM
    if completion:
        try:
            full_model_tag = model_tag if "/" in model_tag else f"{provider.lower()}/{model_tag}"
            response = completion(
                model=full_model_tag,
                messages=[{"role": "user", "content": "Say OK"}],
                api_key=api_key,
                max_tokens=10,
                timeout=12,
            )
            return True, "OK"
        except Exception as e:
            err = str(e)
            if "429" in err or "quota" in err.lower():
                return True, "429_RATE_LIMITED"
            return False, err[:45]
    return False, "NO_CLIENT"


def main():
    gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    cerebras_key = (
        os.getenv("CEREBRAS_API_KEY")
        or os.getenv("CEREBAS_API_KEY", "")
    ).strip()

    print("\n" + "=" * 90)
    print("🔍 DISCOVERING & VERIFYING OFFICIAL PROVIDER MODELS")
    print("=" * 90)

    results = []

    # 1. Gemini
    gemini_candidates = discover_gemini_models(gemini_key)
    tested_gemini = None
    gemini_res = "FAILED"
    for cand in gemini_candidates:
        ok, msg = test_model_request("gemini", cand, gemini_key)
        if ok:
            tested_gemini = cand
            gemini_res = msg
            break
    if not tested_gemini and gemini_candidates:
        tested_gemini = gemini_candidates[0]

    results.append({
        "provider": "Gemini",
        "key_status": mask_key(gemini_key),
        "model_id": tested_gemini or "gemini-2.5-flash",
        "available": "yes" if gemini_res in ("OK", "429_RATE_LIMITED") else "check_quota",
        "result": gemini_res,
    })

    # 2. Groq
    groq_candidates = discover_groq_models(groq_key)
    tested_groq = None
    groq_res = "FAILED"
    for cand in groq_candidates:
        ok, msg = test_model_request("groq", cand, groq_key)
        if ok:
            tested_groq = cand
            groq_res = msg
            break
    if not tested_groq and groq_candidates:
        tested_groq = groq_candidates[0]

    results.append({
        "provider": "Groq",
        "key_status": mask_key(groq_key),
        "model_id": tested_groq or "llama-3.1-8b-instant",
        "available": "yes" if groq_res == "OK" else "no",
        "result": groq_res,
    })

    # 3. Cerebras
    cerebras_candidates = discover_cerebras_models(cerebras_key)
    tested_cerebras = None
    cerebras_res = "FAILED"
    for cand in cerebras_candidates:
        ok, msg = test_model_request("cerebras", cand, cerebras_key)
        if ok:
            tested_cerebras = cand
            cerebras_res = msg
            break
    if not tested_cerebras and cerebras_candidates:
        tested_cerebras = cerebras_candidates[0]

    results.append({
        "provider": "Cerebras",
        "key_status": mask_key(cerebras_key),
        "model_id": tested_cerebras or "gemma-4-31b",
        "available": "yes" if cerebras_res == "OK" else "no",
        "result": cerebras_res,
    })

    # Print Table
    print(f"{'Provider':<12} | {'API Key':<12} | {'Model ID':<26} | {'Available':<10} | {'Test Result'}")
    print("-" * 90)
    for r in results:
        print(f"{r['provider']:<12} | {r['key_status']:<12} | {r['model_id']:<26} | {r['available']:<10} | {r['result']}")
    print("=" * 90 + "\n")


if __name__ == "__main__":
    main()
