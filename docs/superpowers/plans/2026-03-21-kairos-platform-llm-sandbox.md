# Kairos Platform: LLM + Sandbox — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the LLM provider abstraction (Ollama + OpenAI-compat) and Sandbox (path isolation + capability enforcement) as `kplatform/llm` and `kplatform/sandbox`.

**Architecture:** LLM module defines a `Provider` protocol with two implementations: `OllamaProvider` (for local models via `/api/generate`) and `OpenAIProvider` (for LM Studio, Claude API, Bedrock via `/v1/chat/completions`). Sandbox provides path-safe file operations and subprocess execution with capability grants.

**Tech Stack:** Python 3.12+, urllib (Ollama), httpx (OpenAI-compat), subprocess, no heavy deps

**Spec:** `docs/superpowers/specs/2026-03-21-kairos-platform-design.md`

---

## File Structure

```
kplatform/
  llm/
    __init__.py               -- exports: Provider, OllamaProvider, OpenAIProvider, LLMResponse
    provider.py               -- Protocol + response dataclass
    ollama.py                 -- Ollama /api/generate provider
    openai_compat.py          -- OpenAI-compat /v1/chat/completions provider
  sandbox/
    __init__.py               -- exports: Sandbox, ToolResult, CapabilityGrant
    sandbox.py                -- path isolation + subprocess execution
    capabilities.py           -- capability grant definitions + validation
tests/
  platform/
    llm/
      __init__.py
      test_ollama.py          -- availability, generate, fail-open
      test_openai_compat.py   -- health check, chat completion (mocked)
      test_provider.py        -- protocol conformance
    sandbox/
      __init__.py
      test_sandbox.py         -- path traversal, file ops, code execution
      test_capabilities.py    -- grant validation, blocklist
```

---

### Task 1: LLM Provider Protocol + Response

**Files:**
- Create: `kplatform/llm/__init__.py`
- Create: `kplatform/llm/provider.py`
- Create: `tests/platform/llm/__init__.py`
- Create: `tests/platform/llm/test_provider.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/platform/llm/test_provider.py
from kplatform.llm.provider import LLMResponse


def test_llm_response_basic():
    r = LLMResponse(content="hello", model="test", provider="test")
    assert r.content == "hello"
    assert r.prompt_tokens == 0
    assert r.completion_tokens == 0


def test_llm_response_with_tokens():
    r = LLMResponse(
        content="world", model="qwen", provider="ollama",
        prompt_tokens=10, completion_tokens=5,
    )
    assert r.total_tokens == 15


def test_llm_response_tool_calls():
    r = LLMResponse(
        content=None, model="test", provider="test",
        tool_calls=[{"id": "1", "name": "read_file", "arguments": {"path": "x"}}],
    )
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0]["name"] == "read_file"
```

- [ ] **Step 2: Write provider.py**

```python
# kplatform/llm/provider.py
"""LLM provider protocol and response types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class LLMResponse:
    """Response from an LLM provider."""
    content: str | None
    model: str
    provider: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    tool_calls: list[dict] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@runtime_checkable
class Provider(Protocol):
    """Protocol for LLM providers."""

    def is_available(self) -> bool:
        """Check if provider is reachable."""
        ...

    def generate(self, prompt: str, *, system: str | None = None,
                 temperature: float = 0.7, max_tokens: int = 4096) -> LLMResponse:
        """Generate a text completion."""
        ...

    def chat(self, messages: list[dict], *, temperature: float = 0.7,
             max_tokens: int = 4096, tools: list[dict] | None = None) -> LLMResponse:
        """Chat completion with message history."""
        ...
```

- [ ] **Step 3: Write __init__.py**

```python
# kplatform/llm/__init__.py
"""LLM provider abstraction — Ollama, OpenAI-compat, Bedrock."""

from kplatform.llm.provider import Provider, LLMResponse

__all__ = ["Provider", "LLMResponse"]
```

- [ ] **Step 4: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/platform/llm/test_provider.py -v
git add kplatform/llm/ tests/platform/llm/
git commit -m "feat(llm): provider protocol and response types"
```

---

### Task 2: Ollama Provider

**Files:**
- Create: `kplatform/llm/ollama.py`
- Create: `tests/platform/llm/test_ollama.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/platform/llm/test_ollama.py
from kplatform.llm.ollama import OllamaProvider
from kplatform.llm.provider import Provider, LLMResponse


def test_implements_protocol():
    p = OllamaProvider(base_url="http://localhost:99999")
    assert isinstance(p, Provider)


def test_unavailable_returns_false():
    p = OllamaProvider(base_url="http://localhost:99999", timeout=1)
    assert p.is_available() is False


def test_generate_when_unavailable():
    p = OllamaProvider(base_url="http://localhost:99999", timeout=1)
    result = p.generate("hello")
    assert result.content is None
    assert result.provider == "ollama"


def test_chat_when_unavailable():
    p = OllamaProvider(base_url="http://localhost:99999", timeout=1)
    result = p.chat([{"role": "user", "content": "hello"}])
    assert result.content is None
```

- [ ] **Step 2: Write ollama.py**

```python
# kplatform/llm/ollama.py
"""Ollama provider via /api/generate and /api/chat."""

from __future__ import annotations

import json
import urllib.request
import urllib.error

from kplatform.llm.provider import LLMResponse, Provider


class OllamaProvider:
    """Local LLM via Ollama HTTP API."""

    def __init__(
        self, *,
        base_url: str = "http://localhost:11434",
        model: str = "qwen3.5:27b",
        timeout: int = 120,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request(
                f"{self._base_url}/api/tags",
                method="GET",
            )
            urllib.request.urlopen(req, timeout=min(self._timeout, 5))
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def generate(
        self, prompt: str, *, system: str | None = None,
        temperature: float = 0.7, max_tokens: int = 4096,
    ) -> LLMResponse:
        body: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if system:
            body["system"] = system

        data = self._post("/api/generate", body)
        if data is None:
            return LLMResponse(content=None, model=self._model, provider="ollama")

        return LLMResponse(
            content=data.get("response"),
            model=self._model,
            provider="ollama",
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
        )

    def chat(
        self, messages: list[dict], *, temperature: float = 0.7,
        max_tokens: int = 4096, tools: list[dict] | None = None,
    ) -> LLMResponse:
        body: dict = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            body["tools"] = tools

        data = self._post("/api/chat", body)
        if data is None:
            return LLMResponse(content=None, model=self._model, provider="ollama")

        msg = data.get("message", {})
        return LLMResponse(
            content=msg.get("content"),
            model=self._model,
            provider="ollama",
            prompt_tokens=data.get("prompt_eval_count", 0),
            completion_tokens=data.get("eval_count", 0),
            tool_calls=msg.get("tool_calls", []),
        )

    def _post(self, path: str, body: dict) -> dict | None:
        try:
            req = urllib.request.Request(
                f"{self._base_url}{path}",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=self._timeout)
            return json.loads(resp.read())
        except Exception:
            return None
```

- [ ] **Step 3: Update __init__.py**

Add to `kplatform/llm/__init__.py`:
```python
from kplatform.llm.ollama import OllamaProvider
__all__.append("OllamaProvider")
```

- [ ] **Step 4: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/platform/llm/ -v
git add kplatform/llm/ tests/platform/llm/
git commit -m "feat(llm): Ollama provider with generate and chat"
```

---

### Task 3: OpenAI-Compatible Provider

**Files:**
- Create: `kplatform/llm/openai_compat.py`
- Create: `tests/platform/llm/test_openai_compat.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/platform/llm/test_openai_compat.py
from kplatform.llm.openai_compat import OpenAICompatProvider
from kplatform.llm.provider import Provider


def test_implements_protocol():
    p = OpenAICompatProvider(base_url="http://localhost:99999")
    assert isinstance(p, Provider)


def test_unavailable_returns_false():
    p = OpenAICompatProvider(base_url="http://localhost:99999", timeout=1)
    assert p.is_available() is False


def test_generate_when_unavailable():
    p = OpenAICompatProvider(base_url="http://localhost:99999", timeout=1)
    result = p.generate("hello")
    assert result.content is None


def test_chat_when_unavailable():
    p = OpenAICompatProvider(base_url="http://localhost:99999", timeout=1)
    result = p.chat([{"role": "user", "content": "hi"}])
    assert result.content is None
```

- [ ] **Step 2: Write openai_compat.py**

```python
# kplatform/llm/openai_compat.py
"""OpenAI-compatible provider for LM Studio, vLLM, Claude API, Bedrock."""

from __future__ import annotations

import json
import urllib.request
import urllib.error

from kplatform.llm.provider import LLMResponse, Provider


class OpenAICompatProvider:
    """LLM provider using OpenAI-compatible /v1/chat/completions API."""

    def __init__(
        self, *,
        base_url: str = "http://localhost:1234",
        model: str = "default",
        api_key: str | None = None,
        timeout: int = 120,
    ):
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout
        self._available: bool | None = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            req = urllib.request.Request(
                f"{self._base_url}/v1/models",
                method="GET",
            )
            if self._api_key:
                req.add_header("Authorization", f"Bearer {self._api_key}")
            urllib.request.urlopen(req, timeout=min(self._timeout, 5))
            self._available = True
        except Exception:
            self._available = False
        return self._available

    def generate(
        self, prompt: str, *, system: str | None = None,
        temperature: float = 0.7, max_tokens: int = 4096,
    ) -> LLMResponse:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)

    def chat(
        self, messages: list[dict], *, temperature: float = 0.7,
        max_tokens: int = 4096, tools: list[dict] | None = None,
    ) -> LLMResponse:
        body: dict = {
            "model": self._model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            body["tools"] = tools

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            req = urllib.request.Request(
                f"{self._base_url}/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers=headers,
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=self._timeout)
            data = json.loads(resp.read())
        except Exception:
            return LLMResponse(content=None, model=self._model, provider="openai_compat")

        choice = data.get("choices", [{}])[0]
        msg = choice.get("message", {})
        usage = data.get("usage", {})

        tool_calls = []
        for tc in msg.get("tool_calls", []):
            tool_calls.append({
                "id": tc.get("id", ""),
                "name": tc.get("function", {}).get("name", ""),
                "arguments": json.loads(tc.get("function", {}).get("arguments", "{}")),
            })

        return LLMResponse(
            content=msg.get("content"),
            model=data.get("model", self._model),
            provider="openai_compat",
            prompt_tokens=usage.get("prompt_tokens", 0),
            completion_tokens=usage.get("completion_tokens", 0),
            tool_calls=tool_calls,
        )
```

- [ ] **Step 3: Update __init__.py**

```python
# kplatform/llm/__init__.py
"""LLM provider abstraction — Ollama, OpenAI-compat, Bedrock."""

from kplatform.llm.provider import Provider, LLMResponse
from kplatform.llm.ollama import OllamaProvider
from kplatform.llm.openai_compat import OpenAICompatProvider

__all__ = ["Provider", "LLMResponse", "OllamaProvider", "OpenAICompatProvider"]
```

- [ ] **Step 4: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/platform/llm/ -v
git add kplatform/llm/ tests/platform/llm/
git commit -m "feat(llm): OpenAI-compatible provider for LM Studio/Claude/Bedrock"
```

---

### Task 4: Sandbox

**Files:**
- Create: `kplatform/sandbox/__init__.py`
- Create: `kplatform/sandbox/sandbox.py`
- Create: `kplatform/sandbox/capabilities.py`
- Create: `tests/platform/sandbox/__init__.py`
- Create: `tests/platform/sandbox/test_sandbox.py`
- Create: `tests/platform/sandbox/test_capabilities.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/platform/sandbox/test_sandbox.py
import os
from pathlib import Path
from kplatform.sandbox import Sandbox, ToolResult


def test_write_and_read_file(tmp_path):
    sb = Sandbox(workspace=tmp_path)
    result = sb.execute("write_file", {"path": "test.txt", "content": "hello"})
    assert result.success
    result = sb.execute("read_file", {"path": "test.txt"})
    assert result.success
    assert result.output == "hello"


def test_path_traversal_blocked(tmp_path):
    sb = Sandbox(workspace=tmp_path)
    result = sb.execute("read_file", {"path": "../../../etc/passwd"})
    assert not result.success
    assert "traversal" in result.error.lower() or "blocked" in result.error.lower()


def test_path_traversal_via_symlink(tmp_path):
    # Create a symlink pointing outside workspace
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("secret")
    link = tmp_path / "sneaky"
    link.symlink_to(outside)
    sb = Sandbox(workspace=tmp_path)
    result = sb.execute("read_file", {"path": "sneaky"})
    assert not result.success


def test_run_code(tmp_path):
    sb = Sandbox(workspace=tmp_path)
    result = sb.execute("run_code", {"code": "print(2 + 2)"})
    assert result.success
    assert "4" in result.output


def test_run_code_timeout(tmp_path):
    sb = Sandbox(workspace=tmp_path)
    result = sb.execute("run_code", {"code": "import time; time.sleep(100)", "timeout": 1})
    assert not result.success
    assert "timeout" in result.error.lower() or "timed out" in result.error.lower()


def test_unknown_tool(tmp_path):
    sb = Sandbox(workspace=tmp_path)
    result = sb.execute("delete_everything", {})
    assert not result.success
    assert "unknown" in result.error.lower()


def test_write_nested_path(tmp_path):
    sb = Sandbox(workspace=tmp_path)
    result = sb.execute("write_file", {"path": "sub/dir/file.txt", "content": "nested"})
    assert result.success
    assert (tmp_path / "sub" / "dir" / "file.txt").read_text() == "nested"
```

```python
# tests/platform/sandbox/test_capabilities.py
from kplatform.sandbox.capabilities import CapabilityGrant, validate_grant


def test_default_grant():
    grant = CapabilityGrant(worker="atlas")
    assert "read_file" in grant.allowed_tools
    assert "write_file" in grant.allowed_tools


def test_restricted_grant():
    grant = CapabilityGrant(worker="observer", allowed_tools={"read_file"})
    assert "read_file" in grant.allowed_tools
    assert "write_file" not in grant.allowed_tools


def test_validate_grant_no_external():
    grant = CapabilityGrant(worker="test", allowed_paths=["/tmp/workspace"])
    errors = validate_grant(grant)
    assert not errors


def test_validate_grant_blocks_home():
    grant = CapabilityGrant(
        worker="test",
        allowed_paths=[str(Path.home())],
    )
    errors = validate_grant(grant)
    assert len(errors) > 0


def test_validate_grant_blocks_external_urls():
    grant = CapabilityGrant(
        worker="test",
        allowed_urls=["https://api.example.com"],
    )
    errors = validate_grant(grant)
    assert len(errors) > 0
```

Add `from pathlib import Path` to test_capabilities.py imports.

- [ ] **Step 2: Write sandbox.py**

```python
# kplatform/sandbox/sandbox.py
"""Path-isolated sandbox for worker execution."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ToolResult:
    """Result of a sandboxed tool execution."""
    success: bool
    output: str = ""
    error: str = ""


class Sandbox:
    """Execute tools within an isolated workspace directory."""

    BUILTIN_TOOLS = {"write_file", "read_file", "run_code", "run_tests"}

    def __init__(self, workspace: Path | str):
        self._workspace = Path(workspace).resolve()

    def execute(self, tool_name: str, arguments: dict) -> ToolResult:
        """Execute a tool by name. Returns ToolResult."""
        if tool_name not in self.BUILTIN_TOOLS:
            return ToolResult(success=False, error=f"Unknown tool: {tool_name}")

        dispatch = {
            "write_file": self._write_file,
            "read_file": self._read_file,
            "run_code": self._run_code,
            "run_tests": self._run_tests,
        }
        return dispatch[tool_name](arguments)

    def _safe_path(self, rel_path: str) -> Path | None:
        """Resolve a relative path safely within the workspace."""
        try:
            resolved = (self._workspace / rel_path).resolve()
            if not resolved.is_relative_to(self._workspace):
                return None
            return resolved
        except (ValueError, OSError):
            return None

    def _write_file(self, args: dict) -> ToolResult:
        path = self._safe_path(args.get("path", ""))
        if path is None:
            return ToolResult(success=False, error="Path traversal blocked")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(args.get("content", ""))
            return ToolResult(success=True, output=f"Wrote {path.name}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _read_file(self, args: dict) -> ToolResult:
        path = self._safe_path(args.get("path", ""))
        if path is None:
            return ToolResult(success=False, error="Path traversal blocked")
        try:
            if path.is_symlink():
                real = path.resolve()
                if not real.is_relative_to(self._workspace):
                    return ToolResult(success=False, error="Path traversal blocked via symlink")
            content = path.read_text()
            return ToolResult(success=True, output=content)
        except FileNotFoundError:
            return ToolResult(success=False, error=f"File not found: {args['path']}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _run_code(self, args: dict) -> ToolResult:
        code = args.get("code", "")
        timeout = args.get("timeout", 30)
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-c", code],
                capture_output=True, text=True,
                timeout=timeout,
                cwd=str(self._workspace),
            )
            if result.returncode == 0:
                return ToolResult(success=True, output=result.stdout.strip())
            else:
                return ToolResult(success=False, error=result.stderr.strip())
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

    def _run_tests(self, args: dict) -> ToolResult:
        test_path = args.get("path", ".")
        safe = self._safe_path(test_path)
        if safe is None:
            return ToolResult(success=False, error="Path traversal blocked")
        timeout = args.get("timeout", 60)
        try:
            result = subprocess.run(
                [sys.executable, "-I", "-m", "pytest", str(safe), "-v", "--tb=short"],
                capture_output=True, text=True,
                timeout=timeout,
                cwd=str(self._workspace),
            )
            output = result.stdout + result.stderr
            return ToolResult(success=result.returncode == 0, output=output.strip())
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, error="Test run timed out")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

- [ ] **Step 3: Write capabilities.py**

```python
# kplatform/sandbox/capabilities.py
"""Capability grants for worker sandbox isolation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Paths that should never be granted
_BLOCKED_PATHS = {
    str(Path.home()),
    "/etc",
    "/var",
    "/usr",
}

# URLs that should never be granted (external-facing = hard wall)
_BLOCKED_URL_PATTERNS = [
    "https://",
    "http://",
]
_ALLOWED_URL_PATTERNS = [
    "http://localhost",
    "http://127.0.0.1",
    "http://host.docker.internal",
]


@dataclass
class CapabilityGrant:
    """What a worker is allowed to do."""
    worker: str
    allowed_tools: set[str] = field(
        default_factory=lambda: {"write_file", "read_file", "run_code", "run_tests"}
    )
    allowed_paths: list[str] = field(default_factory=list)
    allowed_urls: list[str] = field(default_factory=list)
    allowed_bus_topics: list[str] = field(default_factory=lambda: ["*"])


def validate_grant(grant: CapabilityGrant) -> list[str]:
    """Validate a capability grant against the blocklist. Returns list of errors."""
    errors = []

    for path in grant.allowed_paths:
        resolved = str(Path(path).resolve())
        for blocked in _BLOCKED_PATHS:
            if resolved == blocked or resolved.startswith(blocked + "/"):
                errors.append(f"Path '{path}' is blocked (resolves to {resolved})")

    for url in grant.allowed_urls:
        is_local = any(url.startswith(p) for p in _ALLOWED_URL_PATTERNS)
        if not is_local:
            errors.append(f"URL '{url}' is external-facing (hard wall violation)")

    return errors
```

- [ ] **Step 4: Write __init__.py**

```python
# kplatform/sandbox/__init__.py
"""Sandbox execution with path isolation and capability grants."""

from kplatform.sandbox.sandbox import Sandbox, ToolResult
from kplatform.sandbox.capabilities import CapabilityGrant, validate_grant

__all__ = ["Sandbox", "ToolResult", "CapabilityGrant", "validate_grant"]
```

- [ ] **Step 5: Run tests, commit**

```bash
cd /Users/kairos/Projects/kairos
uv run pytest tests/platform/sandbox/ tests/platform/llm/ -v
git add kplatform/sandbox/ tests/platform/sandbox/
git commit -m "feat(sandbox): path-isolated execution with capability grants"
```

---

### Task 5: Full Platform Verification

- [ ] **Step 1: Run full suite**

```bash
cd /Users/kairos/Projects/kairos && uv run pytest tests/ -v --tb=short
```
Expected: All tests PASS (memory:53 + ledger:8 + bus:11 + llm:~11 + sandbox:~12 = ~95 tests)

- [ ] **Step 2: Verify all imports**

```bash
cd /Users/kairos/Projects/kairos && uv run python -c "
from kplatform.memory import Storage, Compressor, NomicEmbedProvider
from kplatform.bus import Bus, ScopedBus, create_bus
from kplatform.ledger import Ledger, LedgerCorruptionError
from kplatform.llm import Provider, LLMResponse, OllamaProvider, OpenAICompatProvider
from kplatform.sandbox import Sandbox, ToolResult, CapabilityGrant, validate_grant
print('All platform modules OK')
"
```

- [ ] **Step 3: Commit if needed**

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | LLM Provider protocol + response | 3 |
| 2 | Ollama provider | 4 |
| 3 | OpenAI-compat provider | 4 |
| 4 | Sandbox + capabilities | ~12 |
| 5 | Full platform verification | — |
| **Total** | **5 tasks** | **~23 tests** |

## Platform Complete After This Plan

All 6 platform modules will be done:
- memory (53 tests)
- bus (11 tests)
- ledger (8 tests)
- llm (~11 tests)
- sandbox (~12 tests)

Total: ~95 platform tests. Ready for Runtime layer.
