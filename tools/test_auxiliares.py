import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import auxiliares as a

KEYCHAIN_REAL = a.keychain_key


class RoutingTests(unittest.TestCase):
    def setUp(self):
        # The public tests use an isolated fixture, never a private OpenCode profile.
        profile = tempfile.TemporaryDirectory()
        self.addCleanup(profile.cleanup)
        root = Path(profile.name)
        (root / 'opencode').mkdir()
        (root / 'opencode/opencode.json').write_text('{}')
        location = patch.object(a, '__file__', str(root / 'auxiliares.py'))
        location.start(); self.addCleanup(location.stop)
        # Never touch the real Keychain in tests.
        patcher = patch.object(a, "keychain_key", return_value="")
        patcher.start(); self.addCleanup(patcher.stop)
        copilot = patch.object(a, "copilot_available", return_value=False)
        copilot.start(); self.addCleanup(copilot.stop)

    def test_missing_remote_profile_fails_before_subprocess(self):
        (Path(a.__file__).parent / 'opencode/opencode.json').unlink()
        with patch.object(a.subprocess, 'run') as invoke:
            with self.assertRaisesRegex(a.RouterError, 'Perfil'):
                a.infer_remote('pergunta', 'fake-key')
        invoke.assert_not_called()
    def test_routing_by_task(self):
        for kind, model in (("mecanica", "qwen2.5-coder:7b"), ("codigo", "qwen2.5-coder:14b")):
            with self.subTest(kind=kind):
                self.assertEqual(a.choose(kind, [model], [], False), ("ollama", model))
        self.assertEqual(a.choose("analise", ["qwen2.5-coder:14b"], [], False), ("ollama", "qwen2.5-coder:14b"))
        self.assertEqual(a.choose("analise", [], [], True), ("nemotron", a.REMOTE_MODEL))

    def test_missing_credentials_and_models(self):
        with self.assertRaisesRegex(a.RouterError, "NVIDIA"):
            a.choose("codigo", [], [], False)

    def test_loaded_model_avoids_loading_another_large_model(self):
        self.assertEqual(a.choose("codigo", ["qwen2.5-coder:14b"], ["qwen2.5-coder:7b"], False),
                         ("ollama", "qwen2.5-coder:7b"))
        with self.assertRaisesRegex(a.RouterError, "outro modelo local"):
            a.choose("codigo", ["qwen2.5-coder:14b"], ["llama3:8b"], False)

    def test_prompt_validation(self):
        for prompt in ("", " \n", "x" * 12001, "use " + "sk-" + "abcdefghijklmnopqrstuvwxyz", "password=topsecret",
                       "-----BEGIN PRIVATE KEY-----"):
            with self.subTest(prompt=prompt[:30]), self.assertRaises(a.RouterError):
                a.validate_prompt(prompt)
        a.validate_prompt("resuma esta função")

    def test_inventory_and_payload_endpoints(self):
        calls = []

        def fake(url, data=None, headers=None):
            calls.append((url, data, headers))
            if url.endswith("/api/tags"):
                return {"models": [{"name": "qwen2.5-coder:14b"}]}
            if url.endswith("/api/ps"):
                return {"models": []}
            return {"response": "feito", "prompt_eval_count": 4, "eval_count": 3}

        with patch.object(a, "request", side_effect=fake):
            installed, loaded = a.local_inventory()
            provider, model = a.choose("codigo", installed, loaded, False)
            response, inp, out = a.infer_local(model, "faça uma revisão")
        self.assertEqual([c[0] for c in calls[:2]], [a.OLLAMA + "/api/tags", a.OLLAMA + "/api/ps"])
        url, payload, _ = calls[2]
        self.assertEqual(url, a.OLLAMA + "/api/generate")
        self.assertEqual((payload["options"]["num_ctx"], payload["options"]["num_predict"], payload["keep_alive"]), (8192, 1024, "2m"))
        self.assertEqual((provider, model, response, inp, out), ("ollama", "qwen2.5-coder:14b", "feito", 4, 3))

    def test_opencode_uses_stdin_isolated_profile_and_recorded_tokens(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            database = home / '.local/share/opencode/opencode.db'
            database.parent.mkdir(parents=True)
            with sqlite3.connect(database) as db:
                db.execute('CREATE TABLE session_message (session_id TEXT, type TEXT, data TEXT)')
                db.execute('INSERT INTO session_message VALUES (?, ?, ?)', ('session', 'assistant', json.dumps({
                    'model': {'providerID':'nvidia', 'id':'nemotron-3-ultra-550b-a55b', 'variant':'default'},
                    'tokens': {'input':12, 'output':3}})))
            event = {'type':'text', 'sessionID':'session', 'part':{'text':'ok'}}
            run = SimpleNamespace(returncode=0, stdout=json.dumps(event), stderr='')
            with patch.object(Path, 'home', return_value=home), patch.object(a.subprocess, 'run', return_value=run) as invoke, \
                 patch.dict(os.environ, {'OPENCODE_CONFIG_CONTENT':'untrusted override'}):
                self.assertEqual(a.infer_remote('pergunta', 'fake-key'), ('ok', 12, 3))
            args, kwargs = invoke.call_args
            self.assertIn('--standalone', args[0])
            self.assertIn('nvidia/nemotron-3-ultra-550b-a55b', args[0])
            self.assertNotIn('fake-key', ' '.join(args[0]))
            self.assertEqual(kwargs['input'], 'pergunta')
            self.assertEqual(kwargs['env']['NVIDIA_API_KEY'], 'fake-key')
            self.assertNotIn('OPENCODE_CONFIG_CONTENT', kwargs['env'])
            self.assertEqual(kwargs['env']['PWD'], kwargs['cwd'])

    def test_opencode_errors_are_not_retried_or_exposed(self):
        for result in (SimpleNamespace(returncode=1, stdout='', stderr='private fake credential'),
                       SimpleNamespace(returncode=0, stdout='{"type":"error"}', stderr='')):
            with self.subTest(result=result.returncode), patch.object(a.subprocess, 'run', return_value=result) as run:
                with self.assertRaises(a.RouterError) as err:
                    a.infer_remote('pergunta', 'fake-key')
                run.assert_called_once()
                self.assertNotIn('private', str(err.exception))
        with patch.object(a.subprocess, 'run', side_effect=subprocess.TimeoutExpired('opencode',100)) as run:
            with self.assertRaisesRegex(a.RouterError, 'tempo'):
                a.infer_remote('pergunta', 'fake-key')
            run.assert_called_once()

    def test_opencode_requires_one_identified_session(self):
        event = {'type':'text', 'sessionID':'one', 'part':{'text':'ok'}}
        second = dict(event, sessionID='two')
        for stdout in ('', json.dumps(event)+'\n'+json.dumps(second)):
            with self.subTest(stdout=stdout), patch.object(a.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=stdout)):
                with self.assertRaisesRegex(a.RouterError, 'sessão'):
                    a.infer_remote('pergunta', 'fake-key')

    def test_inference_error_is_not_retried(self):
        calls = []
        def fake(url, data=None, headers=None):
            calls.append(url)
            if url.endswith("/api/tags"):
                return {"models": [{"name": "qwen2.5-coder:14b"}]}
            if url.endswith("/api/ps"):
                return {"models": []}
            raise RuntimeError("inference failed")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(a, "request", side_effect=fake), patch.dict(os.environ, {}, clear=True), \
             patch("sys.stdin", io.StringIO("prompt")), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = a.main([])
        self.assertEqual(status, 1)
        self.assertEqual(calls.count(a.OLLAMA + "/api/generate"), 1)
        self.assertNotIn(a.NVIDIA, calls)

    def test_cli_rejects_bad_prompt_before_network(self):
        for prompt in ("", "x" * 12001, "nvapi-" + "abcdefghijklmnopqrstuvwxyz"):
            with self.subTest(prompt=prompt[:20]):
                with patch.object(a, "request") as req, patch("sys.stdin", io.StringIO(prompt)), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(a.main([]), 1)
                req.assert_not_called()

    def test_explicit_local_does_not_ignore_inventory_or_use_remote(self):
        with patch.object(a, "local_inventory", return_value=([], [])), patch.object(a, "infer_remote") as remote, \
             patch.object(a, "infer_local") as local, patch.dict(os.environ, {"NVIDIA_API_KEY": "fake"}), \
             patch("sys.stdin", io.StringIO("prompt")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.main(["--provedor", "ollama"]), 1)
        remote.assert_not_called()
        local.assert_not_called()

    def test_redirect_does_not_forward_credentials(self):
        req = a.urllib.request.Request(a.NVIDIA, headers={"Authorization": "Bearer fake"})
        self.assertIsNone(a.NoRedirect().redirect_request(req, None, 302, "Found", {}, "https://other.example/paid"))

    def test_busy_local_worker_does_not_infer(self):
        with patch.object(a, "local_inventory", return_value=(["qwen2.5-coder:7b"], [])), \
             patch.object(a, "infer_local") as infer, patch.object(a.fcntl, "flock", side_effect=BlockingIOError), \
             patch.dict(os.environ, {}, clear=True), patch("sys.stdin", io.StringIO("prompt")), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.main(["--tipo", "mecanica"]), 1)
        infer.assert_not_called()

    def test_saved_key_wins_over_stale_desktop_environment(self):
        from pathlib import Path
        with patch.object(Path, "read_text", return_value='{"env":{"NVIDIA_API_KEY":"saved-fake-key"}}'), \
             patch.dict(os.environ, {"NVIDIA_API_KEY":"old-fake-key"}):
            self.assertEqual(a.nvidia_key(), "saved-fake-key")

    def test_key_falls_back_to_environment_if_private_config_unavailable(self):
        from pathlib import Path
        for effect in (FileNotFoundError(), ValueError()):
            with self.subTest(error=type(effect).__name__), patch.object(Path, "read_text", side_effect=effect), \
                 patch.dict(os.environ, {"NVIDIA_API_KEY":"env-fake-key"}):
                self.assertEqual(a.nvidia_key(), "env-fake-key")

    def test_keychain_wins_over_saved_key_and_environment(self):
        with patch.object(a, "keychain_key", return_value="keychain-fake-key"), \
             patch.dict(os.environ, {"NVIDIA_API_KEY": "env-fake-key"}):
            self.assertEqual(a.nvidia_key(), "keychain-fake-key")

    def test_keychain_lookup_is_fixed_quiet_and_fails_closed(self):
        ok = subprocess.CompletedProcess([], 0, stdout="kc-fake-key\n", stderr="")
        with patch.object(a.subprocess, "run", return_value=ok) as run:
            self.assertEqual(KEYCHAIN_REAL(), "kc-fake-key")
        args, kwargs = run.call_args
        self.assertEqual(args[0][:2], ["/usr/bin/security", "find-generic-password"])
        self.assertIn("-w", args[0]); self.assertTrue(kwargs["capture_output"]); self.assertNotIn("shell", kwargs)
        missing = subprocess.CompletedProcess([], 44, stdout="", stderr="not found")
        for effect in (dict(return_value=missing), dict(side_effect=OSError()), dict(side_effect=subprocess.TimeoutExpired("security", 5))):
            with self.subTest(effect=str(effect)), patch.object(a.subprocess, "run", **effect):
                self.assertEqual(KEYCHAIN_REAL(), "")

    def test_remote_eligibility_fails_closed(self):
        from pathlib import Path
        for content in ('{}', '{"nemotron_habilitado": false}', '{"nemotron_habilitado": "true"}', 'invalid'):
            with self.subTest(content=content), patch.object(Path, "read_text", return_value=content):
                self.assertFalse(a.remote_enabled())
        with patch.object(Path, "read_text", return_value='{"nemotron_habilitado": true}'):
            self.assertTrue(a.remote_enabled())
        with patch.object(Path, "read_text", side_effect=FileNotFoundError):
            self.assertFalse(a.remote_enabled())

    def test_disabled_remote_never_called_even_with_key(self):
        with patch.object(a, "remote_enabled", return_value=False), \
             patch.object(a, "local_inventory", return_value=([], [])), patch.object(a, "infer_remote") as remote, \
             patch.dict(os.environ, {"NVIDIA_API_KEY": "fake"}), patch("sys.stdin", io.StringIO("prompt")), \
             contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.main(["--tipo", "analise"]), 1)
        remote.assert_not_called()

    def test_empty_model_response_is_not_success(self):
        with patch.dict(os.environ, {"NVIDIA_API_KEY": "fake"}), patch.object(a, "infer_remote", return_value=("", 1, 0)), \
             patch("sys.stdin", io.StringIO("prompt")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.main(["--provedor", "nemotron"]), 1)


class CopilotRoutingTests(unittest.TestCase):
    def test_third_destination_and_local_mechanical_work(self):
        self.assertEqual(a.choose("codigo", [], [], False, True), ("copilot", "auto"))
        self.assertEqual(a.choose("analise", [], [], True, True), ("nemotron", a.REMOTE_MODEL))
        self.assertEqual(a.choose("analise", [], [], False, True), ("copilot", "auto"))
        self.assertEqual(a.choose("mecanica", ["qwen2.5-coder:7b"], [], True, True),
                         ("ollama", "qwen2.5-coder:7b"))

    def test_quota_gate_requires_included_balance_and_disabled_overage(self):
        for quota, expected in [
            ({"remaining": 184, "overage_permitted": False}, True),
            ({"remaining": 29, "overage_permitted": False}, False),
            ({"remaining": 184, "overage_permitted": True}, False),
            ({"remaining": 184}, False), ({"remaining": "184", "overage_permitted": False}, False),
        ]:
            run = SimpleNamespace(returncode=0, stdout=json.dumps({"quota_snapshots": {"chat": quota}}))
            with self.subTest(quota=quota), patch.object(a.shutil, "which", return_value="tool"), \
                 patch.object(Path, "read_text", return_value='{"copilot_habilitado":true}'), \
                 patch.object(a.subprocess, "run", return_value=run):
                self.assertEqual(a.copilot_available(), expected)

    def test_copilot_isolated_no_tools_stdin_and_no_inherited_provider(self):
        events = [{"type": "assistant.turn_start"},
                  {"type": "assistant.message", "data": {"content": "4", "toolRequests": []}}]
        runs = [SimpleNamespace(returncode=0, stdout="fake-login-token"),
                SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, events)))]
        usage = json.dumps({"totalUserRequests":1,"modelMetrics":{"model":{"requests":{"count":1}}},
                            "currentModel":"model", "lastCallInputTokens":4,"lastCallOutputTokens":1})
        with patch.object(a.subprocess, "run", side_effect=runs) as invoke, \
             patch.object(Path, "read_text", return_value=usage), \
             patch.dict(os.environ, {"COPILOT_ALLOW_ALL": "true", "COPILOT_PROVIDER_BASE_URL": "paid", "NVIDIA_API_KEY": "private-fake"}):
            self.assertEqual(a.infer_copilot("2+2"), ("4", 4, 1, "model"))
        args, kwargs = invoke.call_args
        self.assertTrue(kwargs["input"].endswith("2+2"))
        self.assertNotIn("--prompt", args[0])
        self.assertIn("--available-tools=__cerebro_no_tools__", args[0])
        self.assertNotIn("fake-login-token", " ".join(args[0]))
        self.assertNotIn("2+2", " ".join(args[0]))
        self.assertNotIn("COPILOT_PROVIDER_BASE_URL", kwargs["env"])
        self.assertNotIn("COPILOT_ALLOW_ALL", kwargs["env"])
        self.assertNotIn("NVIDIA_API_KEY", kwargs["env"])

    def test_copilot_rejects_tools_and_additional_turns_without_retry(self):
        for extra in [{"type": "tool.execution_start"}, {"type": "assistant.turn_start"}]:
            events = [{"type": "assistant.turn_start"}, extra]
            runs = [SimpleNamespace(returncode=0, stdout="fake-login-token"),
                    SimpleNamespace(returncode=0, stdout="\n".join(map(json.dumps, events)))]
            with self.subTest(extra=extra), patch.object(a.subprocess, "run", side_effect=runs) as invoke:
                with self.assertRaises(a.RouterError): a.infer_copilot("pergunta pública")
                self.assertEqual(invoke.call_count, 2)

    def test_explicit_copilot_without_quota_never_infers(self):
        with patch.object(a, "copilot_available", return_value=False), \
             patch.object(a, "infer_copilot") as infer, patch.object(a, "nvidia_key") as key, \
             patch("sys.stdin", io.StringIO("2+2")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.main(["--provedor", "copilot"]), 1)
        infer.assert_not_called(); key.assert_not_called()

    def test_auto_code_uses_copilot_and_error_has_no_fallback(self):
        with patch.object(a, "copilot_available", return_value=True), \
             patch.object(a, "local_inventory", return_value=([], [])), \
             patch.object(a, "nvidia_key") as key, \
             patch.object(a, "infer_copilot", side_effect=a.RouterError("falha")) as infer, \
             patch.object(a, "infer_local") as local, patch.object(a, "infer_remote") as remote, \
             patch("sys.stdin", io.StringIO("2+2")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(a.main(["--tipo", "codigo"]), 1)
        infer.assert_called_once(); local.assert_not_called(); remote.assert_not_called(); key.assert_not_called()



if __name__ == "__main__":
    unittest.main()
