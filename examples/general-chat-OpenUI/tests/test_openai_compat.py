from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from openbench.chat.transport.openai_compat import OpenAICompatHandler, _message_content_to_text


class FakeEngine:
    def _execute_agent(self, content, config, attachments=None, on_chunk=None, **kwargs):
        if on_chunk:
            on_chunk("hello ")
            on_chunk(content)
        return {
            "output": f"hello {content}",
            "metadata": {"prompt_tokens": 2, "completion_tokens": 3},
        }

    @staticmethod
    def _extract_metadata(result):
        return result.get("metadata", {})

    @staticmethod
    def _result_failed(_result):
        return False, ""

    @staticmethod
    def _extract_output(result):
        return result.get("output")

    @staticmethod
    def _extract_text_content(output):
        return str(output or "")


class OpenAICompatTests(unittest.TestCase):
    def test_message_content_list_is_flattened(self):
        content = [
            {"type": "text", "text": "Summarize this"},
            {"type": "image_url", "image_url": {"url": "https://example.test/a.png"}},
        ]

        self.assertEqual(
            _message_content_to_text(content),
            "Summarize this\n\n[Image: https://example.test/a.png]",
        )

    def test_models_response_exposes_configured_model(self):
        handler = OpenAICompatHandler(
            build_engine=lambda _session: FakeEngine(),
            base_agent=object(),
            model_id="general-chat",
        )

        self.assertEqual(handler.models()["data"][0]["id"], "general-chat")

    def test_run_turn_uses_last_user_message(self):
        handler = OpenAICompatHandler(
            build_engine=lambda _session: FakeEngine(),
            base_agent=object(),
            model_id="general-chat",
        )

        text, metadata = handler._run_turn(
            {
                "messages": [
                    {"role": "user", "content": "first"},
                    {"role": "assistant", "content": "old answer"},
                    {"role": "user", "content": "latest"},
                ]
            },
            None,
        )

        self.assertEqual(text, "hello latest")
        self.assertEqual(metadata["prompt_tokens"], 2)


if __name__ == "__main__":
    unittest.main()
