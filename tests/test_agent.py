"""에이전트 루프를 가짜 클라이언트로 확인한다(API 호출 없음)."""

import json
from types import SimpleNamespace as NS

import pytest

import agent


class Msg(NS):
    def model_dump(self, exclude_none=False):
        return {"role": "assistant", "content": self.content, "tool_calls": [{"id": c.id} for c in self.tool_calls or []]}


def fn_call(name, args, call_id="c1"):
    return NS(id=call_id, function=NS(name=name, arguments=json.dumps(args, ensure_ascii=False)))


def resp(calls, text=""):
    msg = Msg(content=text or None, tool_calls=calls or None)
    return NS(choices=[NS(message=msg)], usage=NS(prompt_tokens=100, completion_tokens=10, total_tokens=130))


class FakeClient:
    """정해 둔 응답을 차례로 돌려주고, 받은 요청을 기록한다."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests = []
        self.chat = NS(completions=self)

    def create(self, **kwargs):
        self.requests.append({**kwargs, "messages": list(kwargs["messages"])})
        return self._responses.pop(0)


def test_tool_then_answer():
    client = FakeClient([
        resp([fn_call("run_sql", {"query": "SELECT count(*) FROM emd"})]),
        resp([], "법정동은 467개입니다."),
    ])
    r = agent.run("법정동 몇 개?", client, model="m")
    assert r.answer == "법정동은 467개입니다."
    assert [c.name for c in r.tool_calls] == ["run_sql"]
    assert r.tool_calls[0].result["rows"] == [[467]]
    # 출력 = 합계 - 입력(생각 토큰 20 포함)
    assert (r.rounds, r.input_tokens, r.output_tokens, r.thinking_tokens) == (2, 200, 60, 40)
    # 두 번째 요청에 도구 결과가 call_id와 함께 들어갔는지
    sent = client.requests[1]["messages"]
    assert sent[-2]["role"] == "assistant" and sent[-2]["tool_calls"][0]["id"] == "c1"
    assert sent[-1]["role"] == "tool" and sent[-1]["tool_call_id"] == "c1"
    assert json.loads(sent[-1]["content"])["rows"] == [[467]]


def test_tool_error_is_returned_to_model():
    client = FakeClient([
        resp([fn_call("run_sql", {"query": "DROP TABLE emd"})]),
        resp([], "실행할 수 없습니다."),
    ])
    r = agent.run("지워", client, model="m")
    assert "error" in r.tool_calls[0].result


def test_unknown_tool_and_bad_args():
    assert "error" in agent.call_tool("delete_all", "{}")[1]
    assert "error" in agent.call_tool("run_sql", '{"sql": "SELECT 1"}')[1]
    assert "error" in agent.call_tool("run_sql", "{not json")[1]


def test_round_limit_forces_answer():
    loop = [resp([fn_call("find_dong", {"name": "신사동"})]) for _ in range(agent.MAX_TOOL_ROUNDS)]
    client = FakeClient(loop + [resp([], "지금까지 결과로 답합니다.")])
    r = agent.run("신사동", client, model="m")
    assert len(r.tool_calls) == agent.MAX_TOOL_ROUNDS
    assert client.requests[-1]["tool_choice"] == "none"
    assert r.stopped.startswith("도구 호출 상한")


def test_history_is_sent():
    client = FakeClient([resp([], "강남구 신사동은 압구정역입니다.")])
    history = [{"role": "user", "content": "신사동 가까운 역?"}, {"role": "assistant", "content": "어느 구인가요?"}]
    agent.run("강남구", client, model="m", history=history)
    roles = [m["role"] for m in client.requests[0]["messages"]]
    assert roles == ["system", "user", "assistant", "user"]


def test_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(ValueError):
        agent.make_client("gemini")


def test_api_tools_schema():
    for t in agent.api_tools():
        assert t["type"] == "function"
        p = t["function"]["parameters"]
        assert p["additionalProperties"] is False and set(p["required"]) == set(p["properties"])


def test_eval_pipeline_with_fake_client(tmp_path, monkeypatch):
    import eval as ev

    qs = ev.load_set(["Q01", "Q25"])
    client = FakeClient([
        resp([fn_call("run_sql", {"query": "SELECT near_station, near_dist_m FROM emd WHERE emd_nm = '논현동'"})]),
        resp([], "가장 가까운 역은 학동역, 직선거리 44m입니다."),
        resp([], "버스 정류장 수는 데이터에 없습니다."),
    ])
    records = ev.run_eval(client, "m", qs)
    assert [r["correct"] for r in records] == [True, True]
    assert [r["tool_ok"] for r in records] == [True, True]
    monkeypatch.setattr(ev, "ROOT", tmp_path)
    (tmp_path / "outputs").mkdir()
    text = ev.write_report(records, "m", "test").read_text(encoding="utf-8")
    assert "2/2 (100%)" in text and "가격 미등록" in text
    assert "자기검증 켬: 개입 **0회**" in text


COUNT_SQL = {"query": "SELECT count(*) AS n FROM emd"}


def test_self_check_asks_again_when_number_is_not_in_tool_results():
    client = FakeClient([
        resp([fn_call("run_sql", COUNT_SQL)]),
        resp([], "법정동은 467개이고, 걸어서 약 12분입니다."),
        resp([], "법정동은 467개입니다. 걷는 시간은 데이터에 없습니다."),
    ])
    r = agent.run("법정동 몇 개?", client, model="m")
    assert r.answer == "법정동은 467개입니다. 걷는 시간은 데이터에 없습니다."
    assert r.first_ungrounded == ["12"] and "12분" in r.first_answer
    assert r.rounds == 3
    sent = client.requests[-1]["messages"]
    assert sent[-2] == {"role": "assistant", "content": "법정동은 467개이고, 걸어서 약 12분입니다."}
    assert sent[-1]["role"] == "user" and "12" in sent[-1]["content"] and "[자동 검증]" in sent[-1]["content"]


def test_self_check_retries_only_once():
    client = FakeClient([resp([], "고속터미널역 669m입니다."), resp([], "고속터미널역 670m입니다.")])
    r = agent.run("반포동 가까운 역?", client, model="m")
    assert r.answer == "고속터미널역 670m입니다."  # 다시 답해도 근거가 없으면 그대로 내보내고, 평가가 잡는다
    assert r.first_ungrounded == ["669"] and len(client.requests) == 2


def test_self_check_lets_model_call_tools_again():
    client = FakeClient([
        resp([], "고속터미널역 669m입니다."),
        resp([fn_call("run_sql", {"query": "SELECT near_station, near_dist_m FROM emd WHERE emd_nm = '반포동'"})]),
        resp([], "고속터미널역입니다."),
    ])
    r = agent.run("반포동 가까운 역?", client, model="m")
    assert [c.name for c in r.tool_calls] == ["run_sql"] and r.answer == "고속터미널역입니다."


def test_self_check_off_and_grounded_answers_cost_nothing_extra():
    client = FakeClient([resp([], "고속터미널역 669m입니다.")])
    r = agent.run("반포동 가까운 역?", client, model="m", self_check=False)
    assert r.first_ungrounded == [] and len(client.requests) == 1
    # 숫자가 질문·앞 대화에 있으면 근거로 본다
    client = FakeClient([resp([], "앞에서 말한 290m가 맞습니다.")])
    history = [{"role": "user", "content": "역삼동?"}, {"role": "assistant", "content": "역삼역 290m입니다."}]
    r = agent.run("그게 맞아?", client, model="m", history=history)
    assert r.first_ungrounded == [] and len(client.requests) == 1


def test_eval_records_first_answer_when_self_check_steps_in():
    import eval as ev

    client = FakeClient([resp([], "버스 정류장은 12개입니다."), resp([], "버스 정류장 수는 데이터에 없습니다.")])
    rec = ev.run_eval(client, "m", ev.load_set(["Q25"]))[0]
    assert rec["intervened"] and rec["first_ungrounded"] == ["12"] and rec["ungrounded"] == []
    assert rec["correct"] and not rec["first_correct"]
