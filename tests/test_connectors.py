"""Tests for Hugging Face and local LLM connectors."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.config import (
    get_default_config,
    get_local_runtime_credential,
    has_configured_provider,
    is_provider_ready,
    load_config,
    public_config,
    set_api_key,
    set_default_provider,
    set_local_runtime_credential,
)
from src.desktop.runtime import DesktopRuntime
from src.providers import PROVIDER_INFO, get_provider_class
from src.providers.connect_flow import save_provider_connection
from src.providers.huggingface_connect import (
    DEFAULT_HF_MODELS,
    HF_ROUTER,
    cache_huggingface_model,
    list_huggingface_models,
    verify_huggingface_token,
)
from src.providers.huggingface_provider import HuggingFaceProvider
from src.providers.local_endpoints import (
    RemoteEndpointError,
    assert_local_or_lan_url,
    list_local_models,
    scan_local_endpoints,
)
from src.providers.local_provider import LocalLLMProvider


class TestProviderRegistry(unittest.TestCase):
    def test_huggingface_and_local_are_first_class(self) -> None:
        self.assertIn("huggingface", PROVIDER_INFO)
        self.assertIn("local", PROVIDER_INFO)
        self.assertEqual(PROVIDER_INFO["huggingface"]["kind"], "huggingface")
        self.assertEqual(PROVIDER_INFO["local"]["kind"], "local")
        self.assertFalse(PROVIDER_INFO["local"]["requires_key"])
        self.assertEqual(get_provider_class("huggingface"), HuggingFaceProvider)
        self.assertEqual(get_provider_class("local"), LocalLLMProvider)

    def test_default_config_includes_new_slots(self) -> None:
        config = get_default_config()
        self.assertIn("huggingface", config["providers"])
        self.assertIn("local", config["providers"])
        self.assertEqual(config["providers"]["huggingface"]["base_url"], HF_ROUTER)
        self.assertEqual(config["providers"]["local"]["default_model"], "")


class TestLocalEndpoints(unittest.TestCase):
    def test_rejects_wan_hosts(self) -> None:
        with self.assertRaises(RemoteEndpointError):
            assert_local_or_lan_url("https://huggingface.co")
        with self.assertRaises(RemoteEndpointError):
            assert_local_or_lan_url("https://api.openai.com/v1")
        with self.assertRaises(RemoteEndpointError):
            assert_local_or_lan_url("http://8.8.8.8:11434/v1")

    def test_accepts_loopback_and_lan(self) -> None:
        self.assertTrue(assert_local_or_lan_url("http://127.0.0.1:11434/v1").endswith("/v1"))
        self.assertTrue(assert_local_or_lan_url("http://192.168.1.20:8000/v1"))
        self.assertTrue(assert_local_or_lan_url("http://10.0.0.8:1234/v1"))

    def test_scan_never_calls_huggingface(self) -> None:
        seen: list[str] = []

        def probe(url: str, timeout: float, headers: dict | None) -> tuple[int, object]:
            seen.append(url)
            if "11434" in url and url.endswith("/models"):
                return 200, {"data": [{"id": "llama3.2"}]}
            raise ConnectionError("offline")

        results = scan_local_endpoints(probe=probe, timeout=0.05)
        self.assertTrue(any(item["id"] == "ollama" and item["reachable"] for item in results))
        self.assertTrue(all("huggingface.co" not in url for url in seen))
        self.assertTrue(all(url.startswith("http://127.0.0.1") for url in seen))

    def test_list_models_openai_and_ollama(self) -> None:
        def probe(url: str, timeout: float, headers: dict | None) -> tuple[int, object]:
            if url.endswith("/api/tags"):
                return 200, {"models": [{"name": "llama3.2:latest"}]}
            raise ConnectionError("no")

        names = list_local_models("http://127.0.0.1:11434", probe=probe)
        self.assertEqual(names, ["llama3.2:latest"])

    def test_endpoint_credentials_are_scoped_and_not_public(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch("pathlib.Path.home", return_value=Path(tmp)):
            url = "http://127.0.0.1:11434/v1"
            set_local_runtime_credential(url, "test-local-secret", device_key="ssh-ed25519 test-public")
            self.assertEqual(get_local_runtime_credential(url)["api_key"], "test-local-secret")
            dumped = json.dumps(public_config())
            self.assertNotIn("test-local-secret", dumped)
            self.assertNotIn("test-public", dumped)


class TestHuggingFaceConnect(unittest.TestCase):
    def test_token_required(self) -> None:
        with self.assertRaises(ValueError):
            verify_huggingface_token("")

    def test_whoami_success(self) -> None:
        with patch("src.providers.huggingface_connect._request_json", return_value=(200, {"name": "ada"})):
            result = verify_huggingface_token("hf_testtoken")
        self.assertTrue(result["ok"])
        self.assertIn("ada", result["message"])
        self.assertEqual(result["router"], HF_ROUTER)

    def test_list_models_user_initiated(self) -> None:
        payload = [{"id": "Qwen/Qwen2.5-7B-Instruct", "downloads": 1, "pipeline_tag": "text-generation"}]
        with patch("src.providers.huggingface_connect._request_json", return_value=(200, payload)) as mocked:
            rows = list_huggingface_models("hf_testtoken", search="qwen")
        self.assertEqual(rows[0]["id"], "Qwen/Qwen2.5-7B-Instruct")
        self.assertTrue(mocked.called)

    def test_cache_uses_hub_and_local_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)

            def fake_download(**kwargs):
                return kwargs["local_dir"]

            fake_hub = type("hub", (), {"snapshot_download": staticmethod(fake_download)})
            with patch.dict("sys.modules", {"huggingface_hub": fake_hub}):
                result = cache_huggingface_model("Qwen/Qwen2.5-7B-Instruct", "hf_testtoken", home=home)
            self.assertTrue(result["ok"])
            self.assertIn("Qwen--Qwen2.5-7B-Instruct", result["path"])


class TestReadinessAndSwitching(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.home_patch = patch("src.config.Path.home", return_value=self.home)
        self.session_home = patch("src.agent.session.Path.home", return_value=self.home)
        self.home_patch.start()
        self.session_home.start()

    def tearDown(self) -> None:
        self.session_home.stop()
        self.home_patch.stop()
        self.tmp.cleanup()

    def test_local_ready_only_after_model_chosen(self) -> None:
        config = load_config()
        self.assertFalse(is_provider_ready("local", config["providers"]["local"]))
        self.assertFalse(has_configured_provider())
        save_provider_connection(
            "local",
            api_key="",
            base_url="http://127.0.0.1:11434/v1",
            default_model="llama3.2",
        )
        self.assertTrue(has_configured_provider())
        self.assertTrue(is_provider_ready("local", load_config()["providers"]["local"]))

    def test_switch_provider_without_reinstall(self) -> None:
        set_api_key("openai", "sk-test-aaaa-bbbb", default_model="gpt-4o-mini")
        set_default_provider("openai")
        save_provider_connection(
            "huggingface",
            api_key="hf_other",
            base_url=HF_ROUTER,
            default_model=DEFAULT_HF_MODELS[0],
        )
        config = load_config()
        self.assertEqual(config["default_provider"], "huggingface")
        self.assertTrue(config["providers"]["openai"]["api_key"])
        set_default_provider("openai")
        self.assertEqual(load_config()["default_provider"], "openai")

    def test_local_login_on_desktop(self) -> None:
        workspace = self.home / "ws"
        workspace.mkdir()
        with patch("src.desktop.runtime.discover_local_environment", return_value={
            "runtimes": [], "endpoints": [], "selected": None, "auto_started": False,
        }):
            runtime = DesktopRuntime(workspace=workspace)
        self.assertTrue(runtime.needs_setup())
        status = runtime.login("local", "", base_url="http://127.0.0.1:11434/v1", default_model="llama3.2")
        self.assertFalse(status["needs_setup"])
        self.assertEqual(status["provider"], "local")
        catalog = runtime.provider_catalog()
        self.assertIn("huggingface", catalog)
        self.assertIn("local", catalog)
        dumped = json.dumps(status)
        self.assertNotIn("hf_", dumped)


if __name__ == "__main__":
    unittest.main()
