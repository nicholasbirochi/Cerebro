#!/usr/bin/env python3
"""Small, cost-aware router for one bounded auxiliary inference."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import ssl
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

OLLAMA = "http://localhost:11434"
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


def local_inventory():
    tags = request(OLLAMA + "/api/tags").get("models", [])
    ps = request(OLLAMA + "/api/ps").get("models", [])
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


def family(name):
    m = re.search(r"(?<!\d)(7|14|30)b(?:[-:]|$)", name.lower())
    return int(m.group(1)) if m else 0


def choose(tipo, installed, loaded, has_key):
    desired = "qwen2.5-coder:7b" if tipo == "mecanica" else "qwen2.5-coder:14b"
    if tipo == "analise" and has_key:
        return "nemotron", REMOTE_MODEL
    if loaded:
        candidates = [m for m in loaded if family(m) in (7, 14, 30)]
        preferred = (7, 14, 30) if tipo == "mecanica" else (14, 30, 7)
        for size in preferred:
            match = next((m for m in candidates if family(m) == size), None)
            if match:
                return "ollama", match
        if has_key:
            return "nemotron", REMOTE_MODEL
        raise RouterError("Há outro modelo local carregado e nenhum modelo adequado residente; valide o acesso gratuito NVIDIA ou libere o Ollama.")
    match = next((m for m in installed if m == desired or m.startswith(desired + "-")), None)
    if match:
        return "ollama", match
    if has_key:
        return "nemotron", REMOTE_MODEL
    raise RouterError("Modelo local necessário indisponível e acesso NVIDIA não configurado ou não validado.")


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
    data = request(OLLAMA + "/api/generate", {
        "model": model, "prompt": prompt, "system": SYSTEM, "stream": False,
        "keep_alive": "2m", "options": {"num_ctx": 8192, "num_predict": MAX_OUTPUT},
    })
    return data.get("response", ""), data.get("prompt_eval_count"), data.get("eval_count")


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
    parser.add_argument("--provedor", choices=("auto", "ollama", "nemotron"), default="auto")
    args = parser.parse_args(argv)
    prompt = sys.stdin.read(MAX_INPUT + 1)
    try:
        validate_prompt(prompt)
        key = nvidia_key()
        if args.provedor == "nemotron":
            if not key:
                raise RouterError("NVIDIA_API_KEY não configurada.")
            provider, model = "nemotron", REMOTE_MODEL
        else:
            try:
                installed, loaded = local_inventory()
            except Exception:
                installed, loaded = [], []
            provider, model = choose(args.tipo, installed, loaded, bool(key) and remote_enabled() and args.provedor == "auto")
        started = time.monotonic()
        if provider == "ollama":
            lock = os.open("/tmp/cerebro-ollama-" + str(os.getuid()) + ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise RouterError("Outro auxiliar já está usando o Ollama; não iniciei inferência.")
                installed, loaded = local_inventory()
                provider, model = choose(args.tipo, installed, loaded, False)
                response, input_tokens, output_tokens = infer_local(model, prompt)
            finally:
                os.close(lock)
        else:
            response, input_tokens, output_tokens = infer_remote(prompt, key)
        if not isinstance(response, str) or not response.strip():
            raise RouterError("O modelo retornou uma resposta vazia; resultado não validado.")
        result = {"provider": provider, "model": model, "response": response,
                  "input_tokens": input_tokens, "output_tokens": output_tokens,
                  "elapsed_seconds": round(time.monotonic() - started, 3)}
        if provider == "nemotron":
            result["via"] = "opencode"
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
