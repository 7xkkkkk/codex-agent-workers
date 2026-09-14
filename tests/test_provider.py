import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from providers import openai_compatible as provider


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "WORKER_BASE_URL": "https://api.example.com/v1",
            "WORKER_API_KEY": "test-placeholder",
            "WORKER_MODEL_FAST": "example-fast",
            "WORKER_MODEL_HARD": "example-hard",
            "WORKER_API_MODE": "chat_completions",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def propose(self, difficulty="fast"):
        return provider.propose_patch("Change value", "value = 1", "", [], difficulty)

    @patch.object(provider, "OpenAI")
    def test_chat_uses_configured_endpoint_and_model(self, factory):
        factory.return_value.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"No edits"}'))]
        )
        model, proposal = self.propose()
        factory.assert_called_once_with(api_key="test-placeholder", base_url="https://api.example.com/v1")
        self.assertEqual(model, "example-fast")
        self.assertEqual(proposal.summary, "No edits")
        self.assertEqual(factory.return_value.chat.completions.create.call_args.kwargs["model"], model)
        factory.return_value.responses.create.assert_not_called()

    @patch.object(provider, "OpenAI")
    def test_responses_uses_configured_hard_model(self, factory):
        os.environ["WORKER_API_MODE"] = "responses"
        factory.return_value.responses.create.return_value = SimpleNamespace(
            output_text='```json\n{"summary":"No edits"}\n```'
        )
        model, _ = self.propose("hard")
        self.assertEqual(model, "example-hard")
        self.assertEqual(factory.return_value.responses.create.call_args.kwargs["model"], model)
        factory.return_value.chat.completions.create.assert_not_called()

    @patch.object(provider, "OpenAI")
    def test_missing_model_does_not_make_api_call(self, factory):
        del os.environ["WORKER_MODEL_FAST"]
        with self.assertRaisesRegex(RuntimeError, "WORKER_MODEL_FAST"):
            self.propose()
        factory.assert_not_called()

    @patch.object(provider, "OpenAI")
    def test_invalid_api_mode_does_not_make_api_call(self, factory):
        os.environ["WORKER_API_MODE"] = "unknown"
        with self.assertRaisesRegex(RuntimeError, "WORKER_API_MODE"):
            self.propose()
        factory.assert_not_called()
