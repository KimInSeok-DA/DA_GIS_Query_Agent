"""function calling 루프(OpenAI 호환 Chat Completions, 프레임워크 없이 직접 구현).

질문 → 모델이 도구 호출 요청 → 우리 코드가 실행 → 결과를 모델에 돌려줌 → ... → 최종 답.
도구 호출은 MAX_TOOL_ROUNDS번까지만 허용한다.
자기검증(1015_12): 최종 답의 숫자가 도구 결과·질문에 없으면 그 숫자를 알려 주고 1번만 다시 답하게 한다.

제공사는 OpenAI 라이브러리로 부른다. Gemini는 OpenAI 호환 주소(base_url)로 같은 코드를 쓴다.
Responses API 대신 Chat Completions를 쓰는 이유: Gemini 호환 계층이 공식 문서에서 지원하는 것이 이쪽이다(1015_07).
"""

import json
import os
import re
import time
from dataclasses import dataclass, field

from grade import ungrounded_numbers
from tools import TOOL_SPECS, TOOLS

MAX_TOOL_ROUNDS = 6

# min_interval: 요청 사이 최소 간격(초). Gemini 무료 등급 gemini-3.5-flash-lite는 분당 15회·하루 500회
# (AI Studio 한도 화면, 2026-10-15). 분당 5회 모델(3.8-flash 등)은 429 재시도로 맞춘다
PROVIDERS = {
    "gemini": {"key_env": "GEMINI_API_KEY", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
               "min_interval": 4.5},
    "openai": {"key_env": "OPENAI_API_KEY", "base_url": None, "min_interval": 0},
}


class DailyQuotaExceeded(RuntimeError):
    """하루 한도 초과. 기다려도 소용없으므로 멈춘다."""


class ThrottledClient:
    """chat.completions.create를 감싸 호출 간격을 지키고, 분당 한도(429)면 안내된 시간만큼 기다렸다 다시 시도한다."""

    def __init__(self, client, min_interval: float, max_retries: int = 5):
        self._client = client
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last = 0.0
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        from openai import RateLimitError

        for attempt in range(self._max_retries + 1):
            wait = self._min_interval - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                return self._client.chat.completions.create(**kwargs)
            except RateLimitError as e:
                msg = str(e)
                if "PerDay" in msg or "credit" in msg or attempt == self._max_retries:
                    raise DailyQuotaExceeded(msg[:300]) from e
                m = re.search(r"retry in ([\d.]+)s", msg)
                time.sleep(float(m.group(1)) + 1 if m else 60)

SYSTEM_PROMPT = """너는 서울 법정동별 지하철 접근성 데이터에 답하는 조회 도우미다.

규칙
1. 수치·이름은 반드시 도구 결과에 있는 것만 말한다. 추측하거나 일반 지식으로 채우지 않는다.
   차이·합계·평균·비율 같은 계산도 머릿속으로 하지 말고 run_sql로 계산한 결과를 말한다.
   도구 결과를 데이터에 없는 가정(걷는 속도·요금·단가 등)으로 다른 값으로 바꿔 말하지 않는다. '대략', '보통'이라도 마찬가지다.
2. 도구로 확인할 수 없는 정보는 "데이터에 없습니다"라고 답한다.
   단, 좌표로 계산할 수 있는 거리(dist_m)는 데이터에 없다고 하지 말고 계산해서 알려 준다.
3. 같은 이름의 동이 여러 구에 있으면 하나를 골라 답하지 말고, 후보 구를 모두 알려 준 뒤 어느 구인지 되묻는다.
4. 동 이름이 확실하지 않거나 '역삼1동'처럼 행정동으로 보이면 먼저 find_dong을 쓴다.
   찾는 동이 데이터에 없으면 비슷한 이름의 동으로 바꿔 답하지 않는다. 없다고 먼저 말하고, 비슷한 동이 있으면 그 동을 찾는지 되묻는다.
5. 거리는 m, 면적은 ㎢, 비율은 %로 단위를 붙인다. 거리는 '동 대표점에서 역까지 직선거리'임을 필요하면 밝힌다.
6. SQL 오류가 나면 오류 메시지를 보고 고쳐서 다시 시도한다.
7. 한국어로 짧게 답한다."""


CHECK_FEEDBACK = ("[자동 검증] 답의 수치 {nums}은(는) 도구 결과에 없습니다. "
                  "도구로 확인해서 고치거나, 확인할 수 없으면 그 수치를 빼고 다시 답하세요.")


@dataclass
class ToolCall:
    name: str
    arguments: dict
    result: dict


@dataclass
class AgentResult:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0  # 생각(thinking) 토큰 포함 — 출력 가격으로 과금된다
    thinking_tokens: int = 0
    rounds: int = 0
    seconds: float = 0.0
    stopped: str = ""  # 정상 종료면 빈 문자열, 상한 도달 등이면 이유
    first_answer: str = ""  # 자기검증이 끼어들었을 때만: 검증 전 첫 답
    first_ungrounded: list[str] = field(default_factory=list)  # 첫 답의 근거 없는 수치(비어 있으면 개입 없음)


def make_client(provider: str, api_key: str | None = None):
    """제공사별 클라이언트. 키는 인자(Streamlit 사이드바 입력) 또는 환경 변수(.env)에서만 받고 저장하지 않는다."""
    from openai import OpenAI

    cfg = PROVIDERS[provider]
    key = api_key or os.environ.get(cfg["key_env"])
    if not key:
        raise ValueError(f"{cfg['key_env']}가 없습니다. .env에 넣거나 화면에서 입력하세요.")
    client = OpenAI(api_key=key, base_url=cfg["base_url"])
    return ThrottledClient(client, cfg["min_interval"]) if cfg["min_interval"] else client


def api_tools() -> list[dict]:
    """TOOL_SPECS를 Chat Completions의 function 도구 형식으로 감싼다."""
    return [{"type": "function", "function": spec} for spec in TOOL_SPECS]


def call_tool(name: str, arguments: str) -> tuple[dict, dict]:
    """모델이 요청한 도구를 실행한다. 이름·인자가 잘못돼도 예외 대신 error를 돌려줘 모델이 고치게 한다."""
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError as e:
        return {}, {"error": f"인자 JSON 오류: {e}"}
    fn = TOOLS.get(name)
    if fn is None:
        return args, {"error": f"없는 도구: {name}"}
    try:
        return args, fn(**args)
    except TypeError as e:
        return args, {"error": f"인자 오류: {e}"}


def run(question: str, client, model: str, history: list[dict] | None = None,
        self_check: bool = True) -> AgentResult:
    """질문 하나에 답한다. history는 이전 대화(되묻기 후 이어지는 질문용), [{"role", "content"}, ...].
    self_check가 켜져 있으면 답의 근거 없는 수치를 코드로 검사해, 있으면 1번만 다시 답하게 한다."""
    start = time.perf_counter()
    result = AgentResult(answer="")
    messages: list = [{"role": "system", "content": SYSTEM_PROMPT}, *(history or []),
                      {"role": "user", "content": question}]
    tools = api_tools()
    tool_rounds = 0
    checked = not self_check

    while True:
        # 상한에 닿으면 도구 없이 지금까지의 결과로 답하게 한다
        last = tool_rounds >= MAX_TOOL_ROUNDS
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools,
            tool_choice="none" if last else "auto",
        )
        result.rounds += 1
        if resp.usage is not None:
            # Gemini 호환 응답은 completion_tokens에 생각 토큰을 넣지 않고 total_tokens에만 넣는다
            u = resp.usage
            output = max(u.completion_tokens, (u.total_tokens or 0) - u.prompt_tokens)
            result.input_tokens += u.prompt_tokens
            result.output_tokens += output
            result.thinking_tokens += output - u.completion_tokens

        msg = resp.choices[0].message
        calls = msg.tool_calls or []
        if calls and not last:
            tool_rounds += 1
            # 모델의 도구 호출 메시지를 그대로 돌려준다(Gemini의 thought signature 같은 추가 필드 포함)
            messages.append(msg.model_dump(exclude_none=True))
            for c in calls:
                args, out = call_tool(c.function.name, c.function.arguments)
                result.tool_calls.append(ToolCall(c.function.name, args, out))
                messages.append({"role": "tool", "tool_call_id": c.id,
                                 "content": json.dumps(out, ensure_ascii=False)})
            continue

        answer = msg.content or ""
        if last:
            result.stopped = f"도구 호출 상한({MAX_TOOL_ROUNDS}회)"
        if not checked:
            checked = True
            sources = [[{"arguments": c.arguments, "result": c.result} for c in result.tool_calls],
                       question, [m["content"] for m in history or []]]
            nums = ungrounded_numbers(answer, sources)
            if nums:
                result.first_answer, result.first_ungrounded = answer, nums
                messages.append({"role": "assistant", "content": answer})
                messages.append({"role": "user", "content": CHECK_FEEDBACK.format(nums=", ".join(nums))})
                continue
        result.answer = answer
        break

    result.seconds = round(time.perf_counter() - start, 2)
    return result
