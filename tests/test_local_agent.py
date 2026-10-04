from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from local_agent import (
    AgentReply,
    LocalAgentConfig,
    LocalCartethyiaAgent,
    _parse_model_reply,
    direct_command,
    persona_fact_reply,
)


class LocalAgentTests(unittest.TestCase):
    def test_agent_is_disabled_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config = LocalAgentConfig.load(Path(temp_dir) / "missing.json")
        self.assertFalse(config.enabled)
        self.assertEqual(config.endpoint, "http://127.0.0.1:11434")
        self.assertEqual(config.model, "")

    def test_agent_config_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "agent.json"
            expected = LocalAgentConfig(True, "http://localhost:11434", "local-model")
            expected.save(path)
            loaded = LocalAgentConfig.load(path)
        self.assertEqual(loaded, expected)

    def test_explicit_commands_route_to_whitelist(self) -> None:
        cases = {
            "卡提希娅，帮我做做日常": "run_daily",
            "帮我把周常奖励拿满": "run_weekly_rewards",
            "运行周常拿满星声": "run_weekly_astrite",
            "执行30次4C": "run_4c_30",
            "执行十次4C": "run_4c_10",
            "帮我诊断程序": "diagnose",
            "停止当前任务": "stop_task",
        }
        for message, tool in cases.items():
            with self.subTest(message=message):
                reply = direct_command(message)
                self.assertIsNotNone(reply)
                self.assertEqual(reply.tool, tool)

    def test_daily_command_reply_names_the_daily_task(self) -> None:
        reply = direct_command("卡提希娅，帮我做做日常")
        self.assertIsNotNone(reply)
        self.assertIn("日常", reply.text)

    def test_each_pet_has_a_distinct_in_character_daily_reply(self) -> None:
        replies = {
            name: direct_command("帮我做做日常", name).text
            for name in ("达妮娅", "爱弥斯", "景燃", "卡提希娅")
        }
        self.assertEqual(len(set(replies.values())), 4)
        self.assertTrue(all("日常" in text for text in replies.values()))
        self.assertIn("红茶", replies["达妮娅"])
        self.assertIn("好消息", replies["爱弥斯"])
        self.assertIn("一样都不会落", replies["景燃"])

    def test_explicit_chat_commands_can_change_safe_settings(self) -> None:
        cases = {
            "任务结束后自动关机": "set_auto_shutdown_on",
            "不要自动关机": "set_auto_shutdown_off",
            "开启盯鼠标": "set_pointer_look_on",
            "关闭定时跳跃": "set_auto_jump_off",
        }
        for message, tool in cases.items():
            with self.subTest(message=message):
                reply = direct_command(message, "卡提希娅")
                self.assertIsNotNone(reply)
                self.assertEqual(reply.tool, tool)

    def test_old_heal_command_directs_user_to_role_modules(self):
        reply = direct_command("开启三号位回血", "卡提希娅")
        self.assertIsNone(reply.tool)
        self.assertIn("战斗排轴", reply.text)

    def test_unsupported_pet_does_not_change_look_settings(self) -> None:
        reply = direct_command("开启盯鼠标", "达妮娅")
        self.assertIsNotNone(reply)
        self.assertIsNone(reply.tool)
        self.assertIn("暂时不支持", reply.text)

    def test_identity_and_age_have_distinct_grounded_answers(self) -> None:
        for character in ("达妮娅", "爱弥斯", "景燃", "卡提希娅"):
            with self.subTest(character=character):
                identity = persona_fact_reply("你是谁？", character)
                age = persona_fact_reply("你的年龄是多少？", character)
                self.assertIsNotNone(identity)
                self.assertIsNotNone(age)
                self.assertNotEqual(identity.text, age.text)
                self.assertIn(character, identity.text)
                self.assertIn("没有公开", age.text)

    def test_aemeath_school_answer_preserves_timeline(self) -> None:
        reply = persona_fact_reply("你在哪里上学？", "爱弥斯")
        self.assertIsNotNone(reply)
        self.assertIn("以前在星炬学院", reply.text)
        self.assertIn("电子幽灵", reply.text)
        self.assertNotIn("理工大学", reply.text)

    def test_agent_answers_character_facts_without_calling_model(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434", "qwen3:4b")
        agent = LocalCartethyiaAgent(config, "卡提希娅人格")
        with patch("local_agent.urllib.request.urlopen") as urlopen:
            identity = agent.respond("你是谁")
            age = agent.respond("你多大了")
        urlopen.assert_not_called()
        self.assertNotEqual(identity.text, age.text)

    def test_casual_mentions_do_not_execute_tasks(self) -> None:
        self.assertIsNone(direct_command("你平时喜欢做日常吗"))
        self.assertIsNone(direct_command("给我讲讲周常的故事"))

    def test_model_json_parser_rejects_unknown_tool(self) -> None:
        reply = _parse_model_reply('{"reply":"一起走吧。","tool":"run_shell"}')
        self.assertEqual(reply, AgentReply("一起走吧。", None))

    def test_model_reply_strips_leading_stage_direction(self) -> None:
        reply = _parse_model_reply('{"reply":"（轻轻拍了拍肩膀）先休息一下吧。"}')
        self.assertEqual(reply.text, "先休息一下吧。")

    def test_ordinary_model_chat_cannot_invoke_even_whitelisted_tool(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434", "test-model")
        agent = LocalCartethyiaAgent(config, "persona")
        response = Mock()
        response.read.return_value = json.dumps(
            {"message": {"content": '{"reply":"一起走吧。","tool":"run_daily"}'}},
            ensure_ascii=False,
        ).encode("utf-8")
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch("local_agent.urllib.request.urlopen", return_value=context):
            reply = agent.respond("今天想聊聊旅行")
        self.assertEqual(reply, AgentReply("一起走吧。", None))

    def test_internal_reasoning_uses_character_fallback(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434", "test-model")
        agent = LocalCartethyiaAgent(
            config,
            "爱弥斯人格",
            character_name="爱弥斯",
            fallback_reply=lambda message: f"累了就休息一下吧，我陪你。{message[:0]}",
        )
        response = Mock()
        response.read.return_value = json.dumps(
            {"message": {"content": '{"reply":"首先，用户说自己很累，我需要分析角色设定。"}'}},
            ensure_ascii=False,
        ).encode("utf-8")
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch("local_agent.urllib.request.urlopen", return_value=context):
            reply = agent.respond("我有点累")
        self.assertEqual(reply.text, "累了就休息一下吧，我陪你。")

    def test_chat_request_uses_ollama_api_and_persona(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434/", "test-model")
        agent = LocalCartethyiaAgent(config, "卡提希娅人格")
        response = Mock()
        response.read.return_value = json.dumps(
            {"message": {"content": '{"reply":"新的故事开始啦。","tool":null}'}},
            ensure_ascii=False,
        ).encode("utf-8")
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch("local_agent.urllib.request.urlopen", return_value=context) as urlopen:
            reply = agent.respond("陪我聊会儿")
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/chat")
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["format"]["required"], ["reply"])
        self.assertFalse(payload["format"]["additionalProperties"])
        self.assertEqual(payload["keep_alive"], "60s")
        self.assertIs(payload["think"], False)
        self.assertEqual(payload["options"]["num_ctx"], 4096)
        self.assertEqual(payload["options"]["num_predict"], 128)
        self.assertIn("卡提希娅人格", payload["messages"][0]["content"])
        self.assertTrue(payload["messages"][-1]["content"].endswith("/no_think"))
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 180.0)
        self.assertEqual(reply.text, "新的故事开始啦。")

    def test_system_prompt_uses_selected_pet_name(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434", "test-model")
        agent = LocalCartethyiaAgent(config, "爱弥斯完整人格", character_name="爱弥斯")
        prompt = agent._system_prompt()
        self.assertIn("爱弥斯完整人格", prompt)
        self.assertIn("爱弥斯桌宠", prompt)
        self.assertNotIn("卡提希娅口吻", prompt)

    def test_timeout_message_explains_large_model_cold_start(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434", "qwen3.5:9b")
        agent = LocalCartethyiaAgent(config, "卡提希娅人格")
        with patch("local_agent.urllib.request.urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaisesRegex(RuntimeError, "大型模型首次载入可能需要1至3分钟"):
                agent.test_connection()

    def test_unload_requests_immediate_model_release(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434/api/chat", "qwen3:4b")
        agent = LocalCartethyiaAgent(config, "卡提希娅人格")
        response = Mock()
        response.read.return_value = b"{}"
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch("local_agent.urllib.request.urlopen", return_value=context) as urlopen:
            agent.unload()
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(payload, {"model": "qwen3:4b", "keep_alive": 0})

    def test_warmup_loads_model_for_sixty_seconds(self) -> None:
        config = LocalAgentConfig(True, "http://127.0.0.1:11434/api/chat", "qwen3:4b")
        agent = LocalCartethyiaAgent(config, "卡提希娅人格")
        response = Mock()
        response.read.return_value = b"{}"
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        with patch("local_agent.urllib.request.urlopen", return_value=context) as urlopen:
            agent.warmup()
        request = urlopen.call_args.args[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "http://127.0.0.1:11434/api/generate")
        self.assertEqual(payload, {"model": "qwen3:4b", "keep_alive": "60s"})
        self.assertEqual(urlopen.call_args.kwargs["timeout"], 180.0)


if __name__ == "__main__":
    unittest.main()
