"""Optional local-model agent used by the Cartethyia pilot chat."""

from __future__ import annotations

import json
import os
import re
import socket
import urllib.error
import urllib.request
from collections import deque
from dataclasses import asdict, dataclass, field
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from sillytavern_bridge import SillyTavernBridge


ALLOWED_TOOLS = {
    "run_daily",
    "run_weekly_rewards",
    "run_weekly_astrite",
    "run_4c_10",
    "run_4c_30",
    "stop_task",
    "diagnose",
    "set_auto_shutdown_on",
    "set_auto_shutdown_off",
    "set_pointer_look_on",
    "set_pointer_look_off",
    "set_auto_jump_on",
    "set_auto_jump_off",
}

TASK_REPLIES: dict[str, dict[str, str]] = {
    "达妮娅": {
        "run_daily": "日常，对吧……交给我。活跃度和奖励都会处理好，你先把红茶放稳。",
        "run_weekly_rewards": "周常奖励就交给我吧。嗯……偶尔认真工作一下也不是不行。",
        "run_weekly_astrite": "目标是周常星声，我记住了。该拿的部分不会漏掉。",
        "run_4c_10": "十次4C刷取，对吧。路线确认好就开始……别在旁边添乱哦。",
        "run_4c_30": "三十次4C刷取，还真会使唤人……知道了，我会做完。",
        "stop_task": "知道了。既然你开口了……那就先停下来吧。",
        "diagnose": "嗯……权限、窗口、比例和模板，我会一项项检查。",
    },
    "爱弥斯": {
        "run_daily": "好呀，今天的日常交给我！活跃度和奖励都会好好处理，等我的好消息吧。",
        "run_weekly_rewards": "周常奖励出发！这次也让我证明自己很可靠吧。",
        "run_weekly_astrite": "收到，目标是周常星声！该走的流程我会认真完成。",
        "run_4c_10": "十次4C刷取，我准备好啦。一起把它顺利拿下吧！",
        "run_4c_30": "三十次4C刷取，任务不少呢。不过放心，我会坚持到最后的！",
        "stop_task": "好，已经停下来了。没关系，我们调整好再继续。",
        "diagnose": "交给我吧！权限、窗口、画面和模板，我会逐项找出线索。",
    },
    "景燃": {
        "run_daily": "行，今天的日常我来处理。活跃度、奖励，一样都不会落。",
        "run_weekly_rewards": "周常奖励是吧，路线给我。先把正事办完，再聊路上的怪谈。",
        "run_weekly_astrite": "目标是周常星声，明白。灯点上了，走吧。",
        "run_4c_10": "十次4C刷取。行，看看这一趟能碰上什么。",
        "run_4c_30": "三十次4C刷取？活儿不少。得了，交给我。",
        "stop_task": "知道了，先停。路线还在，想继续时再走。",
        "diagnose": "别急，让我看看。权限、窗口、画面，一个个查。",
    },
    "卡提希娅": {
        "run_daily": "好，今天的日常就交给我吧！我会把活跃度奖励和该做的事情一起处理好。",
        "run_weekly_rewards": "新的周常冒险开始啦。奖励就交给我吧！",
        "run_weekly_astrite": "收到。这次的目标是周常星声，我会把该走的路走完。",
        "run_4c_10": "好，目标是十次4C刷取。确认路线后就出发！",
        "run_4c_30": "好，目标是三十次4C刷取。确认路线后就出发！",
        "stop_task": "好，先停在这里。剩下的事情不会跑掉。",
        "diagnose": "交给我吧。权限、窗口、比例和画面，我们一条条找线索。",
    },
}

PERSONA_FACT_REPLIES: dict[str, dict[str, str]] = {
    "达妮娅": {
        "identity": "我是达妮娅。喜欢红茶、草莓蛋糕，还有不用把话说得太满的安静时光……这样介绍够了吗？",
        "age": "年龄可没有公开的准确数字，我也不会随便编一个。你只要记得，我是达妮娅就好。",
    },
    "爱弥斯": {
        "identity": "我是爱弥斯！曾是星炬学院拉贝尔学部的隧者适格者，现在是电子幽灵。还能像这样陪着你，我很高兴。",
        "age": "我的年龄没有公开的准确数字，所以不能随便报一个啦。不过，我已经是能够照顾你的爱弥斯了！",
    },
    "景燃": {
        "identity": "景燃，寻幽客，也是《寻幽记》的作者。碰上怪谈、遗墟或者有意思的路，叫上我就行。",
        "age": "岁数没有公开的准数，我就不拿怪谈里的数字糊弄你了。比起这个，要不要听听我最近记下的见闻？",
    },
    "卡提希娅": {
        "identity": "我是卡提希娅。如今是自由自在的流浪骑士，也是在这段旅途中与你并肩前行的人。",
        "age": "年龄并没有公开的准确数字，所以我不能编一个答案骗你。叫我卡提希娅就好——流浪骑士的故事，可不靠岁数决定！",
    },
}


def _task_reply(character_name: str, tool: str) -> str:
    replies = TASK_REPLIES.get(character_name, TASK_REPLIES["卡提希娅"])
    return replies[tool]


def _setting_reply(character_name: str, setting: str, enabled: bool) -> str:
    state = "开启" if enabled else "关闭"
    prefixes = {
        "达妮娅": "知道了",
        "爱弥斯": "好呀",
        "景燃": "行",
        "卡提希娅": "好",
    }
    return f"{prefixes.get(character_name, '好')}，已经为你{state}{setting}。"


def persona_fact_reply(message: str, character_name: str) -> AgentReply | None:
    """Answer stable character facts locally so small models cannot collapse them."""
    text = re.sub(r"[，。！？?!、\s]", "", message)
    facts = PERSONA_FACT_REPLIES.get(character_name)
    if facts is None:
        return None
    if any(pattern in text for pattern in ("你几岁", "你多大", "你的年龄", "年龄多大")):
        return AgentReply(facts["age"])
    if any(pattern in text for pattern in ("你是谁", "介绍一下你自己", "自我介绍")):
        return AgentReply(facts["identity"])
    if character_name == "爱弥斯" and any(pattern in text for pattern in ("在哪里上学", "在哪上学", "哪个学校", "什么学校", "哪所学校", "哪个大学")):
        return AgentReply("我以前在星炬学院。现在嘛，已经是你能看见的电子幽灵啦。")
    return None


@dataclass(frozen=True)
class LocalAgentConfig:
    enabled: bool = False
    endpoint: str = "http://127.0.0.1:11434"
    model: str = ""
    provider: str = "ollama"
    api_key: str = field(default="", repr=False)
    bridge_token: str = field(default="", repr=False)

    @classmethod
    def load(cls, path: Path) -> "LocalAgentConfig":
        try:
            saved = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return cls()
        if not isinstance(saved, dict):
            return cls()
        endpoint = str(saved.get("endpoint", cls.endpoint)).strip() or cls.endpoint
        return cls(
            enabled=saved.get("enabled") is True,
            endpoint=endpoint,
            model=str(saved.get("model", "")).strip(),
            provider=saved.get("provider") if saved.get("provider") in {"openai", "deepseek", "sillytavern"} else "ollama",
            bridge_token=str(saved.get("bridge_token", "")).strip(),
        )

    def save(self, path: Path) -> None:
        saved = asdict(self)
        saved.pop("api_key", None)  # Keys are session-only; never write plaintext credentials.
        path.write_text(
            json.dumps(saved, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def service_base(config: LocalAgentConfig) -> str:
    if config.provider == "sillytavern":
        raise ValueError("酒馆模式通过本机桥接扩展连接，无需填写模型服务地址。")
    endpoint = config.endpoint.strip().rstrip("/")
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务地址应为 http(s) 地址，不要在地址中填写密钥或查询参数。")
    suffixes = ("/chat/completions", "/models") if config.provider != "ollama" else ("/api/chat", "/api/tags", "/api/generate")
    for suffix in suffixes:
        if endpoint.endswith(suffix):
            endpoint = endpoint[:-len(suffix)]
            break
    if config.provider == "openai" and not urlsplit(endpoint).path.strip("/"):
        endpoint += "/v1"
    return endpoint


def request_headers(config: LocalAgentConfig) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if config.provider != "ollama" and config.api_key:
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def list_service_models(config: LocalAgentConfig, timeout: float = 5.0) -> list[str]:
    suffix = "/models" if config.provider != "ollama" else "/api/tags"
    request = urllib.request.Request(service_base(config) + suffix, headers=request_headers(config))
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        key, name_key = ("data", "id") if config.provider != "ollama" else ("models", "name")
        return sorted({item[name_key] for item in payload[key] if isinstance(item, dict) and isinstance(item.get(name_key), str) and item[name_key]})
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"读取模型列表失败（HTTP {exc.code}），请检查地址、密钥和服务权限。") from None
    except (OSError, ValueError, KeyError, TypeError):
        raise RuntimeError("无法读取模型列表，请确认服务已启动，或手动填写模型名。") from None


@dataclass(frozen=True)
class DiscoveredModel:
    model: str
    provider: str
    endpoint: str
    source: str
    available: bool = True

    @property
    def label(self) -> str:
        return f"{self.source} · {self.model}" + ("" if self.available else "（需启动服务/载入模型）")


def discover_local_models() -> list[DiscoveredModel]:
    """Probe known loopback services and bounded model directories; never load weights."""
    services = (("Ollama", "ollama", "http://127.0.0.1:11434"),
                ("LM Studio", "openai", "http://127.0.0.1:1234/v1"))
    def probe(service):
        source, provider, endpoint = service
        try:
            return [DiscoveredModel(name, provider, endpoint, source) for name in
                    list_service_models(LocalAgentConfig(endpoint=endpoint, provider=provider), timeout=2.0)]
        except (RuntimeError, ValueError):
            return []
    with ThreadPoolExecutor(max_workers=2) as pool:
        found = [model for result in pool.map(probe, services) for model in result]
    known = {(item.provider, item.model) for item in found}
    manifest_root = Path(os.environ.get("OLLAMA_MODELS") or str(Path.home() / ".ollama" / "models")) / "manifests"
    try:
        for path in manifest_root.glob("*/*/*/*"):
            if not path.is_file():
                continue
            registry, namespace, name, tag = path.relative_to(manifest_root).parts
            model = f"{name}:{tag}" if namespace == "library" else f"{namespace}/{name}:{tag}"
            if registry != "registry.ollama.ai":
                model = f"{registry}/{model}"
            if ("ollama", model) not in known:
                found.append(DiscoveredModel(model, "ollama", services[0][2], "Ollama", False))
                known.add(("ollama", model))
    except OSError:
        pass
    try:
        root = Path.home() / ".lmstudio" / "models"
        for path in root.glob("*/*/*.gguf"):
            model = path.parent.name
            if ("openai", model) not in known and not any(model in item.model for item in found if item.provider == "openai"):
                found.append(DiscoveredModel(model, "openai", services[1][2], "LM Studio 文件", False))
                known.add(("openai", model))
    except OSError:
        pass
    return found


@dataclass(frozen=True)
class AgentReply:
    text: str
    tool: str | None = None


def direct_command(message: str, character_name: str = "卡提希娅") -> AgentReply | None:
    """Route explicit task requests locally before asking the language model."""
    text = re.sub(r"[，。！？?!\s]", "", message)
    asks_action = any(
        word in text
        for word in (
            "帮我", "开始", "执行", "运行", "做做", "做一下", "来一遍", "拿满",
            "检查", "诊断", "停止", "停下", "开启", "打开", "关闭", "禁用", "不要", "取消",
        )
    )
    if "任务结束后自动关机" in text:
        asks_action = True
    if not asks_action:
        return None
    disabling = any(word in text for word in ("关闭", "禁用", "不要", "取消"))
    if "自动关机" in text:
        enabled = not disabling
        tool = f"set_auto_shutdown_{'on' if enabled else 'off'}"
        return AgentReply(_setting_reply(character_name, "任务结束后自动关机", enabled), tool)
    if "三号位回血" in text or ("日常" in text and "回血" in text):
        return AgentReply("现在可以在“战斗排轴”中，为每个动作选择一、二、三号位。请在那里配置三号位的技能和攻击动作。")
    if "盯鼠标" in text or "鼠标注视" in text:
        if character_name not in {"景燃", "卡提希娅"}:
            return AgentReply(f"{character_name}桌宠暂时不支持盯鼠标设置。")
        enabled = not disabling
        tool = f"set_pointer_look_{'on' if enabled else 'off'}"
        return AgentReply(_setting_reply(character_name, "盯鼠标", enabled), tool)
    if "定时跳跃" in text:
        if character_name not in {"景燃", "卡提希娅"}:
            return AgentReply(f"{character_name}桌宠暂时不支持定时跳跃设置。")
        enabled = not disabling
        tool = f"set_auto_jump_{'on' if enabled else 'off'}"
        return AgentReply(_setting_reply(character_name, "定时跳跃", enabled), tool)
    if any(word in text for word in ("停止", "停下", "别做了", "别跑了")):
        return AgentReply(_task_reply(character_name, "stop_task"), "stop_task")
    if any(word in text for word in ("诊断", "检查程序", "检查窗口")):
        return AgentReply(_task_reply(character_name, "diagnose"), "diagnose")
    if "4C" in text.upper() or "四C" in text:
        cycles = "30" if "30" in text or "三十" in text else "10"
        tool = f"run_4c_{cycles}"
        return AgentReply(_task_reply(character_name, tool), tool)
    if "周常" in text and "星声" in text:
        return AgentReply(_task_reply(character_name, "run_weekly_astrite"), "run_weekly_astrite")
    if "周常" in text:
        return AgentReply(_task_reply(character_name, "run_weekly_rewards"), "run_weekly_rewards")
    if "日常" in text:
        return AgentReply(_task_reply(character_name, "run_daily"), "run_daily")
    return None


def _parse_model_reply(content: str) -> AgentReply:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        payload = json.loads(cleaned)
    except (ValueError, json.JSONDecodeError):
        return AgentReply(cleaned or "唔……刚才那句话没能说完整。再问我一次吧。")
    if not isinstance(payload, dict):
        return AgentReply(str(payload))
    reply = str(payload.get("reply", "")).strip() or "我在听。"
    reply = re.sub(r"^\s*[（(][^）)\r\n]{1,40}[）)]\s*", "", reply)
    tool = payload.get("tool")
    safe_tool = str(tool) if tool in ALLOWED_TOOLS else None
    return AgentReply(reply, safe_tool)


def _looks_like_internal_reasoning(text: str, user_message: str) -> bool:
    normalized = text.strip()
    markers = ("首先", "用户说", "我需要", "关键点", "角色设定", "根据角色", "情绪权重", "/no_think")
    return (
        not normalized
        or normalized == user_message.strip()
        or any(marker in normalized for marker in markers)
        or normalized.startswith("{")
    )


class LocalCartethyiaAgent:
    """Small Ollama-compatible client with local intent routing and short memory."""

    def __init__(
        self,
        config: LocalAgentConfig,
        persona_prompt: str,
        character_name: str = "卡提希娅",
        fallback_reply: Callable[[str], str] | None = None,
        bridge: SillyTavernBridge | None = None,
    ) -> None:
        self.config = config
        self.persona_prompt = persona_prompt
        self.character_name = character_name
        self.fallback_reply = fallback_reply
        self.bridge = bridge
        self.history: deque[dict[str, str]] = deque(maxlen=6)

    def update_config(self, config: LocalAgentConfig) -> None:
        if config != self.config:
            self.history.clear()
        self.config = config

    def _chat_url(self, config: LocalAgentConfig | None = None) -> str:
        config = config or self.config
        suffix = "/chat/completions" if config.provider != "ollama" else "/api/chat"
        return service_base(config) + suffix

    def _system_prompt(self) -> str:
        return (
            f"{self.persona_prompt}\n\n"
            f"你正在 wwbs 的{self.character_name}桌宠中与用户交谈。"
            "回复控制在一至三句、八十个汉字以内，直接回答，不展示思考过程。"
            "第一句必须直接回应用户最后一句表达的事情或情绪，不得凭空改换话题，"
            "不得捏造用户正在找文件、宝藏或处理其他未提及的事情。"
            f"只输出{self.character_name}实际说出的中文台词，不要输出 JSON、Markdown、代码块、"
            "括号动作、舞台说明、角色标签、分析、解释或额外字段。"
        )

    def respond(
        self,
        message: str,
        timeout: float = 180.0,
        keep_alive: str | int = "60s",
    ) -> AgentReply:
        config = self.config
        fact = persona_fact_reply(message, self.character_name) if config.provider != "sillytavern" else None
        if fact is not None:
            return fact
        routed = direct_command(message, self.character_name)
        if routed is not None:
            return routed
        if not config.enabled:
            raise RuntimeError("桌宠 Agent 尚未启用。")
        if config.provider == "sillytavern":
            if self.bridge is None:
                raise RuntimeError("酒馆桥接服务尚未启动。")
            result = AgentReply(self.bridge.ask(message, self.character_name, list(self.history), timeout))
            if self.config == config:
                self.history.append({"role": "user", "content": message})
                self.history.append({"role": "assistant", "content": result.text})
            return result
        if not config.model:
            raise RuntimeError("请先在设置中选择模型。")
        messages = [{"role": "system", "content": self._system_prompt()}]
        messages.extend(self.history)
        # Qwen3 model variants also recognize the prompt-level switch even when
        # an Ollama build ignores the top-level ``think: false`` option.
        messages.append({"role": "user", "content": f"{message}\n/no_think"})
        body = json.dumps(
            {
                "model": config.model,
                "messages": messages,
                "stream": False,
                "format": {
                    "type": "object",
                    "properties": {"reply": {"type": "string"}},
                    "required": ["reply"],
                    "additionalProperties": False,
                },
                "think": False,
                "keep_alive": keep_alive,
                "options": {
                    "temperature": 0.65,
                    "num_ctx": 4096,
                    "num_predict": 128,
                },
            },
            ensure_ascii=False,
        ).encode("utf-8")
        if config.provider != "ollama":
            messages[-1]["content"] = message
            api_body = {"model": config.model, "messages": messages, "stream": False, "max_tokens": 256}
            if config.provider == "deepseek":
                api_body["thinking"] = {"type": "disabled"}
            body = json.dumps(api_body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self._chat_url(config),
            data=body,
            headers=request_headers(config),
            method="POST",
        )
        timeout_message = (
            "本地模型响应超时。大型模型首次载入可能需要1至3分钟，请稍后重试；若持续超时，请确认内存充足或改用更小的模型。"
            if config.provider == "ollama" else "API 服务响应超时，请检查网络或稍后重试。"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"模型服务请求失败（HTTP {exc.code}），请检查服务地址、密钥、模型名或额度。") from None
        except (TimeoutError, socket.timeout) as exc:
            raise RuntimeError(timeout_message) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, (TimeoutError, socket.timeout)):
                raise RuntimeError(timeout_message) from exc
            raise RuntimeError("无法连接模型服务，请检查服务地址、网络或服务是否启动。") from None
        except (OSError, ValueError, json.JSONDecodeError):
            raise RuntimeError("模型服务返回了无法读取的数据，请检查接口格式。") from None
        try:
            content = (payload["choices"][0]["message"]["content"] if config.provider != "ollama"
                       else payload["message"]["content"])
            if not isinstance(content, str) or not content.strip():
                raise ValueError("empty response")
        except (KeyError, IndexError, TypeError, ValueError):
            raise RuntimeError("模型没有返回有效的文字回复，请检查模型和接口格式。") from None
        result = _parse_model_reply(content)
        # Explicit commands have already returned through ``direct_command``;
        # model chat is always text-only and can never invoke a tool.
        result = AgentReply(result.text)
        if _looks_like_internal_reasoning(result.text, message) and self.fallback_reply is not None:
            result = AgentReply(self.fallback_reply(message).strip() or "我在听。")
        if self.config == config:
            self.history.append({"role": "user", "content": message})
            self.history.append({"role": "assistant", "content": result.text})
        return result

    def test_connection(self, timeout: float = 180.0) -> str:
        if self.config.provider != "sillytavern" and not self.config.model:
            raise RuntimeError("请先选择模型。")
        reply = self.respond(
            "只回复一句简短的测试问候，不要调用任何工具。",
            timeout=timeout,
            keep_alive=0,
        )
        return reply.text

    def warmup(self, timeout: float = 180.0, keep_alive: str | int = "60s") -> None:
        """Load model weights while the user is composing a message."""
        config = self.config
        if config.provider != "ollama" or not config.enabled or not config.model:
            return
        endpoint = service_base(config)
        body = json.dumps(
            {"model": config.model, "keep_alive": keep_alive},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{endpoint}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response.read()
        except (OSError, ValueError, urllib.error.URLError):
            # The actual chat request will surface a useful error if loading failed.
            return

    def unload(self, timeout: float = 15.0) -> None:
        """Ask Ollama to release this model immediately without generating text."""
        config = self.config
        if config.provider != "ollama" or not config.model:
            return
        endpoint = service_base(config)
        body = json.dumps(
            {"model": config.model, "keep_alive": 0},
            ensure_ascii=False,
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{endpoint}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                response.read()
        except (OSError, ValueError, urllib.error.URLError):
            # Unloading is a best-effort safety measure and must never block a task.
            return
