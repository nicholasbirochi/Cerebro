#!/usr/bin/env python3
"""Small, cost-aware router for one bounded auxiliary inference."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

OLLAMA = "http://localhost:11434"
OLLAMA_RELAY = "http://127.0.0.1:11435"  # Codenotch relay: forwards to OLLAMA and records token usage.
NVIDIA = "https://integrate.api.nvidia.com/v1/chat/completions"
REMOTE_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
SYSTEM = "Responda de forma breve e objetiva. Não use ferramentas nem solicite acesso a arquivos."
MAX_INPUT = 12000
MAX_OUTPUT = 1024


class RouterError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward credentials or inference to a different endpoint.


def request(url, data=None, headers=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **(headers or {})}, method="GET" if data is None else "POST")
    context = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else ssl.create_default_context()
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=context), NoRedirect())
    with opener.open(req, timeout=5 if data is None else 90) as response:
        return json.loads(response.read())


_ollama_base = None


def ollama_base():
    """Prefer the local Codenotch relay so local tokens are counted; fall back to Ollama itself."""
    global _ollama_base
    if _ollama_base is None:
        try:
            request(OLLAMA_RELAY + "/api/version")
            _ollama_base = OLLAMA_RELAY
        except (urllib.error.URLError, OSError, ValueError):
            _ollama_base = OLLAMA
    return _ollama_base


def local_inventory():
    tags = request(ollama_base() + "/api/tags").get("models", [])
    ps = request(ollama_base() + "/api/ps").get("models", [])
    return [m.get("name", "") for m in tags], [m.get("name", "") for m in ps]


KEYCHAIN_SERVICE = "cerebro.nvidia-api-key"


def keychain_key():
    # macOS Keychain first: no secret in settings files, shell profiles or inherited environments.
    try:
        run = subprocess.run(["/usr/bin/security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
                             capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    return run.stdout.strip() if run.returncode == 0 else ""


def nvidia_key():
    key = keychain_key()
    if key:
        return key
    # Transition fallback. Desktop sessions can retain an old environment after a local key update.
    try:
        saved = json.loads((Path.home() / ".claude/settings.json").read_text()).get("env", {}).get("NVIDIA_API_KEY")
        if isinstance(saved, str) and saved.strip():
            return saved.strip()
    except (OSError, ValueError, AttributeError):
        pass
    return os.environ.get("NVIDIA_API_KEY", "")


def remote_enabled():
    try:
        config = json.loads(Path(__file__).with_name("auxiliares.json").read_text())
        return config.get("nemotron_habilitado") is True
    except (OSError, ValueError, AttributeError):
        return False


def copilot_available():
    """Only included balance with overage disabled; never alter billing."""
    if not shutil.which("copilot") or not shutil.which("gh"):
        return False
    try:
        config = json.loads(Path(__file__).with_name("auxiliares.json").read_text())
        if config.get("copilot_habilitado") is not True:
            return False
        run = subprocess.run(["gh", "api", "copilot_internal/user"],
                             capture_output=True, text=True, timeout=15)
        quota = json.loads(run.stdout)["quota_snapshots"]["chat"]
        return (run.returncode == 0 and quota.get("overage_permitted") is False
                and isinstance(quota.get("remaining"), (int, float))
                and quota["remaining"] >= 30)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False


def family(name):
    m = re.search(r"(?<!\d)(7|14|30)b(?:[-:]|$)", name.lower())
    return int(m.group(1)) if m else 0


# Local first: free, private and no Claude/GPT tokens. Each route is tried in order;
# a local model is used only if resident, or installed with nothing else loaded.
ROUTES = {
    "mecanica": ("qwen2.5-coder:7b", "qwen2.5-coder:14b", "nemotron", "copilot"),
    "codigo": ("qwen2.5-coder:14b", "qwen3-coder:30b", "qwen2.5-coder:7b", "copilot", "nemotron"),
    "analise": ("qwen3-coder:30b", "nemotron", "qwen2.5-coder:14b", "copilot"),
}
BIG_MODEL_MIN_FREE_GB = 20  # 30B (~18 GB) loads only when this much memory is reclaimable.


def free_memory_gb():
    """Free + inactive + speculative pages (macOS); 0 when unknown, so the 30B is never forced."""
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
        page = int(re.search(r"page size of (\d+)", out).group(1))
        pages = sum(int(re.search(name + r":\s+(\d+)", out).group(1))
                    for name in ("Pages free", "Pages inactive", "Pages speculative"))
        return pages * page / 1e9
    except (OSError, AttributeError, ValueError, subprocess.SubprocessError):
        return 0


def choose(tipo, installed, loaded, has_key, has_copilot=False, free_gb=0):
    for step in ROUTES[tipo]:
        if step == "nemotron":
            if has_key:
                return "nemotron", REMOTE_MODEL
        elif step == "copilot":
            if has_copilot:
                return "copilot", "auto"
        elif loaded:
            match = next((m for m in loaded if family(m) == family(step)), None)
            if match:
                return "ollama", match
        else:
            match = next((m for m in installed if m == step or m.startswith(step + "-")), None)
            if match and (family(match) != 30 or free_gb >= BIG_MODEL_MIN_FREE_GB):
                return "ollama", match
    if loaded:
        raise RouterError("Há outro modelo local carregado e nenhum modelo adequado residente; valide o acesso gratuito NVIDIA ou libere o Ollama.")
    raise RouterError("Modelo local necessário indisponível e acesso NVIDIA não configurado ou não validado.")


def log_usage(tipo, result):
    """Counts delegated work without prompts or responses; only where the private config exists."""
    if not Path(__file__).with_name("auxiliares.json").exists():
        return
    entry = {"data": time.strftime("%Y-%m-%dT%H:%M:%S"), "tipo": tipo,
             **{k: result.get(k) for k in ("provider", "model", "input_tokens", "output_tokens", "elapsed_seconds")}}
    try:
        with open(Path(__file__).with_name("uso-auxiliares.jsonl"), "a") as log:
            log.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def check_output(response, lines=None, pattern=None):
    """Return why the response breaks the requested shape, or None when it fits."""
    rows = [row.strip() for row in response.strip().splitlines() if row.strip()]
    problems = []
    if lines is not None and len(rows) != lines:
        problems.append(f"esperava {lines} linhas e vieram {len(rows)}")
    if pattern is not None:
        bad = [str(number) for number, row in enumerate(rows, 1) if not pattern.fullmatch(row)]
        if bad:
            problems.append(f"fora do padrão: linhas {', '.join(bad)}")
    return "; ".join(problems) or None


def validate_prompt(prompt):
    if not prompt.strip():
        raise RouterError("O prompt está vazio.")
    if len(prompt) > MAX_INPUT:
        raise RouterError("O prompt excede 12000 caracteres.")
    secret_patterns = (
        r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
        r"\b(?:sk-[A-Za-z0-9_-]{16,}|nvapi-[A-Za-z0-9_-]{16,})\b",
        r"\b(?:ghp_|github_pat_)[A-Za-z0-9_]{16,}\b",
        r"\bAKIA[0-9A-Z]{16}\b",
        r"(?i)\b(?:api[_ -]?key|secret[_ -]?key|password)\s*[:=]\s*\S+",
    )
    if any(re.search(pattern, prompt) for pattern in secret_patterns):
        raise RouterError("O prompt parece conter uma chave ou segredo; remova-o antes de continuar.")


def infer_local(model, prompt):
    data = request(ollama_base() + "/api/generate", {
        "model": model, "prompt": prompt, "system": SYSTEM, "stream": False,
        "keep_alive": "2m", "options": {"num_ctx": 8192, "num_predict": MAX_OUTPUT},
    })
    return data.get("response", ""), data.get("prompt_eval_count"), data.get("eval_count")


def infer_copilot(prompt):
    token_run = subprocess.run(["gh", "auth", "token", "--hostname", "github.com"],
                               capture_output=True, text=True, timeout=10)
    if token_run.returncode or not token_run.stdout.strip():
        raise RouterError("Login do Copilot indisponível; nenhuma inferência iniciada.")
    with tempfile.TemporaryDirectory(prefix="cerebro-copilot-aux-") as directory:
        home = Path(directory)
        (home / "config.json").write_text(json.dumps({
            "model": "auto", "autoTier": "efficiency", "continueOnAutoMode": False,
            "autoUpdate": False, "defaultMode": "interactive"}))
        env = {k: v for k, v in os.environ.items() if k in
               ("PATH", "HOME", "TMPDIR", "LANG", "LC_ALL")}
        env.update(COPILOT_HOME=directory, GH_TOKEN=token_run.stdout.strip(),
                   COPILOT_AUTO_UPDATE="false")
        # An empty allowlist enables defaults in CLI 1.0.92; an impossible name disables every tool.
        args = ["copilot", "--model", "auto", "--auto-tier", "efficiency",
                "--available-tools=__cerebro_no_tools__", "--disable-builtin-mcps",
                "--no-custom-instructions", "--no-auto-update", "--no-remote", "--no-remote-export",
                "--no-ask-user", "--no-experimental", "--no-color", "--stream", "off",
                "--max-ai-credits", "30", "--output-format", "json",
                "--usage-output-file", str(home / "usage.json")]
        try:
            # Piped stdin is the prompt; --prompt would replace it in this CLI.
            run = subprocess.run(args, input=SYSTEM + " Responda em até 1024 tokens.\n\n" + prompt,
                                 capture_output=True, text=True,
                                 cwd=directory, env=env, timeout=100)
        except subprocess.TimeoutExpired:
            raise RouterError("Copilot excedeu o tempo; sem nova tentativa ou fallback.") from None
        if run.returncode:
            raise RouterError("Copilot não concluiu; sem nova tentativa ou fallback. Confira o acesso incluído.")
        events = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
        if any(event.get("type") in ("tool.execution_start", "subagent.started", "session.error") for event in events):
            raise RouterError("Copilot tentou uma ação fora da resposta textual delimitada.")
        turns = [e for e in events if e.get("type") == "assistant.turn_start"]
        if len(turns) != 1:
            raise RouterError("Copilot não registrou exatamente um turno; sem nova tentativa.")
        messages = [e.get("data", {}) for e in events if e.get("type") == "assistant.message"]
        response = "".join(m.get("content", "") for m in messages)
        if any(m.get("toolRequests") for m in messages):
            raise RouterError("Copilot solicitou ferramentas; resultado recusado.")
        usage = json.loads((home / "usage.json").read_text())
        calls = sum(m.get("requests", {}).get("count", 0) for m in usage.get("modelMetrics", {}).values())
        if usage.get("totalUserRequests") != 1 or calls != 1:
            raise RouterError("Copilot registrou mais de uma inferência ou uso não verificável.")
        return response, usage.get("lastCallInputTokens"), usage.get("lastCallOutputTokens"), usage.get("currentModel")


def infer_remote(prompt, key):
    profile = Path(__file__).resolve().with_name("opencode")
    if not (profile / "opencode.json").is_file():
        raise RouterError("Perfil do OpenCode indisponível; não iniciei inferência.")
    env = dict({k: v for k, v in os.environ.items() if not k.startswith("OPENCODE_")},
               NVIDIA_API_KEY=key, OPENCODE_CONFIG_DIR=str(profile),
               OPENCODE_DISABLE_PROJECT_CONFIG="1", OPENCODE_DISABLE_MODELS_FETCH="1",
               XDG_DATA_HOME=str(Path.home() / ".local/share"))
    # A new standalone session avoids inherited server settings and project files.
    with tempfile.TemporaryDirectory(prefix="cerebro-aux-") as directory:
        env["PWD"] = directory
        try:
            run = subprocess.run([str(Path.home() / ".opencode/bin/opencode"), "run", "--standalone",
                                  "--model", "nvidia/nemotron-3-ultra-550b-a55b",
                                  "--agent", "cerebro-economico", "--format", "json", "--title", "Cérebro · auxiliar"],
                                 input=prompt, text=True, capture_output=True, cwd=directory, env=env, timeout=100)
        except subprocess.TimeoutExpired:
            raise RouterError("OpenCode excedeu o tempo; sem nova tentativa ou fallback.") from None
    if run.returncode:
        raise RouterError("OpenCode não concluiu a inferência; sem nova tentativa ou fallback. Confira o diagnóstico local do OpenCode.")
    events = [json.loads(line) for line in run.stdout.splitlines() if line.strip()]
    if any(event.get("type") == "error" for event in events):
        raise RouterError("OpenCode registrou erro; sem nova tentativa ou fallback.")
    texts = [event for event in events if event.get("type") == "text"]
    sessions = {event["sessionID"] for event in texts}
    if len(sessions) != 1:
        raise RouterError("Resposta do OpenCode sem uma sessão identificável.")
    database = Path.home() / ".local/share/opencode/opencode.db"
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as db:
        rows = db.execute("SELECT data FROM session_message WHERE session_id = ? AND type = 'assistant'",
                          (sessions.pop(),)).fetchall()
    if len(rows) != 1:
        raise RouterError("O OpenCode não registrou exatamente uma resposta; confira o histórico local.")
    data = json.loads(rows[0][0])
    recorded_model = data.get("model", {})
    if (recorded_model.get("providerID"), recorded_model.get("id")) != ("nvidia", "nemotron-3-ultra-550b-a55b"):
        raise RouterError("Modelo registrado diferente do Nemotron autorizado.")
    usage = data.get("tokens", {})
    return "".join(event["part"]["text"] for event in texts), usage.get("input"), usage.get("output")


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--tipo", choices=("mecanica", "codigo", "analise"), default="codigo")
    parser.add_argument("--provedor", choices=("auto", "ollama", "nemotron", "copilot"), default="auto")
    parser.add_argument("--saida", help="grava a resposta neste arquivo novo e omite o texto do JSON")
    parser.add_argument("--linhas", type=int, help="exige este número de linhas não vazias")
    parser.add_argument("--padrao", help="expressão regular que cada linha não vazia precisa seguir inteira")
    args = parser.parse_args(argv)
    prompt = sys.stdin.read(MAX_INPUT + 1)
    try:
        validate_prompt(prompt)
        try:
            pattern = re.compile(args.padrao) if args.padrao else None
        except re.error as exc:
            raise RouterError(f"Padrão inválido: {exc}.")
        draft = args.saida + ".rascunho" if args.saida else None
        if args.saida and (os.path.lexists(args.saida) or os.path.lexists(draft)):
            raise RouterError("O arquivo de saída ou o rascunho já existe; não sobrescrevo.")
        copilot = args.provedor in ("auto", "copilot") and copilot_available()
        key = "" if args.provedor == "copilot" or (args.tipo == "codigo" and copilot) else nvidia_key()
        if args.provedor == "copilot":
            if not copilot:
                raise RouterError("Copilot sem franquia incluída confirmada, margem de 30 créditos ou overage desativado; nenhuma inferência iniciada.")
            provider, model = "copilot", "auto"
        elif args.provedor == "nemotron":
            if not key:
                raise RouterError("NVIDIA_API_KEY não configurada.")
            provider, model = "nemotron", REMOTE_MODEL
        else:
            try:
                installed, loaded = local_inventory()
            except Exception:
                installed, loaded = [], []
            has_key = bool(key) and remote_enabled() and args.provedor == "auto"
            free_gb = free_memory_gb()
            provider, model = choose(args.tipo, installed, loaded, has_key, copilot, free_gb)
        started = time.monotonic()
        if provider == "ollama":
            lock = os.open("/tmp/cerebro-ollama-" + str(os.getuid()) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    installed, loaded = local_inventory()
                    provider, model = choose(args.tipo, installed, loaded, False, False, free_gb)
                    response, input_tokens, output_tokens = infer_local(model, prompt)
                except BlockingIOError:
                    # Ollama busy: take the next free remote step instead of waking Claude/GPT.
                    if args.provedor == "ollama":
                        raise RouterError("Outro auxiliar já está usando o Ollama; não iniciei inferência.")
                    provider, model = choose(args.tipo, [], [], has_key, copilot)
            finally:
                os.close(lock)
        if provider == "copilot":
            response, input_tokens, output_tokens, model = infer_copilot(prompt)
        elif provider == "nemotron":
            response, input_tokens, output_tokens = infer_remote(prompt, key)
        if not isinstance(response, str) or not response.strip():
            raise RouterError("O modelo retornou uma resposta vazia; resultado não validado.")
        result = {"provider": provider, "model": model, "response": response,
                  "input_tokens": input_tokens, "output_tokens": output_tokens,
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        if provider == "nemotron":
            result["via"] = "opencode"
        elif provider == "copilot":
            result["via"] = "copilot-cli"
            result["routing_profile"] = "efficiency"
        log_usage(args.tipo, result)
        problem = check_output(response, args.linhas, pattern)
        if problem:
            # One attempt only. The draft lets the principal fix just the listed lines instead of redoing all of them.
            if args.saida:
                with open(draft, "x", encoding="utf-8") as output:
                    output.write(response.strip() + "\n")
                raise RouterError(f"Resposta reprovada na validação ({problem}); {args.saida} não foi gravado, "
                                  f"rascunho em {draft}: corrija só essas linhas.")
            raise RouterError(f"Resposta reprovada na validação ({problem}); nada gravado.")
        if args.saida:
            with open(args.saida, "x", encoding="utf-8") as output:
                output.write(response.strip() + "\n")
            del result["response"]
            result["saida"] = args.saida
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
