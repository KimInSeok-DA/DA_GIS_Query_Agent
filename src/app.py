"""질문하면 에이전트가 도구로 데이터를 조회해 답하는 화면.

실행: streamlit run src/app.py
- API 키는 사이드바 입력 또는 .env에서만 받는다. 키는 이 세션의 메모리에만 있고 파일·로그에 남기지 않는다
- 답마다 에이전트가 한 일(도구 호출·SQL·결과), 근거 없는 수치, 토큰·비용을 보여 준다
- 자기검증이 첫 답을 고치게 했으면 고치기 전 답과 걸린 수치도 보여 준다
- 같은 이름의 동처럼 되물은 뒤에는 이어서 답하면 앞 대화를 함께 보낸다
"""

from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

import agent
from eval import cost_usd
from grade import ungrounded_numbers

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = {"gemini": "gemini-3.5-flash-lite", "openai": "gpt-6-luna"}
HISTORY_TURNS = 3  # 앞 대화는 최근 3번 주고받은 것까지 보낸다
EXAMPLES = [
    "강남구 논현동에서 가장 가까운 지하철역과 거리는?",
    "신사동에서 가장 가까운 역은?",
    "홍대입구역에서 1km 안에 대표점이 있는 법정동을 모두 알려줘",
    "가장 가까운 역까지 평균 거리가 가장 긴 구에서 가장 먼 동은?",
    "역삼동에서 강남역까지 걸어서 몇 분 걸려?",
]

load_dotenv(ROOT / ".env")
st.set_page_config(page_title="서울 지하철 접근성 질의 에이전트", page_icon="🚇")


@st.cache_resource(show_spinner=False)
def get_client(provider: str, api_key: str):
    """제공사·키별로 클라이언트를 한 번만 만든다(호출 간격 제한을 세션 안에서 지키도록)."""
    return agent.make_client(provider, api_key or None)


def show_tool_call(i: int, call: dict) -> None:
    st.markdown(f"**{i}. `{call['name']}`**")
    args = call["arguments"]
    if call["name"] == "run_sql" and "query" in args:
        st.code(args["query"], language="sql")
    else:
        st.json(args, expanded=False)
    result = call["result"]
    if "error" in result:
        st.error(result["error"])
    elif "rows" in result:
        st.dataframe(pd.DataFrame(result["rows"], columns=result["columns"]), hide_index=True)
        if result.get("truncated"):
            st.caption("결과가 길어 앞부분만 받았습니다.")
    else:
        if "candidates" in result:
            st.dataframe(pd.DataFrame(result["candidates"]), hide_index=True)
        if result.get("note"):
            st.caption(result["note"])


def show_details(d: dict) -> None:
    """답 아래에 에이전트가 한 일과 비용을 보여 준다."""
    if d.get("first_ungrounded"):
        with st.expander(f"자동 검증으로 고친 답 — 첫 답의 수치 {', '.join(d['first_ungrounded'])}이(가) 도구 결과에 없었습니다"):
            st.markdown(d["first_answer"])
    if d["ungrounded"]:
        st.warning(f"도구 결과에 없는 수치가 답에 있습니다: {', '.join(d['ungrounded'])} — 확인이 필요합니다.")
    with st.expander(f"에이전트가 한 일 (도구 호출 {len(d['tool_calls'])}번)"):
        if not d["tool_calls"]:
            st.caption("도구를 쓰지 않고 답했습니다.")
        for i, call in enumerate(d["tool_calls"], 1):
            show_tool_call(i, call)
        if d["stopped"]:
            st.caption(f"멈춘 이유: {d['stopped']}")
    cost = f", 유료 환산 ${d['cost']:.5f}" if d["cost"] is not None else ""
    st.caption(f"토큰 입력 {d['input_tokens']:,} · 출력 {d['output_tokens']:,}{cost} · "
               f"모델 호출 {d['rounds']}번 · {d['seconds']}초")


# 사이드바: 제공사·모델·키
with st.sidebar:
    st.header("설정")
    provider = st.selectbox("제공사", list(agent.PROVIDERS), index=0)
    model = st.text_input("모델", DEFAULT_MODEL[provider])
    key_env = agent.PROVIDERS[provider]["key_env"]
    api_key = st.text_input(f"API 키 (비우면 .env의 {key_env})", type="password")
    if provider == "gemini":
        st.caption("Gemini 무료 등급은 입력이 제품 개선에 쓰일 수 있습니다. 보내는 내용은 질문과 공개 데이터 조회 결과뿐입니다.")
    self_check = st.toggle("자기검증", value=True,
                           help="답의 수치가 도구 결과에 없으면 1번 다시 답하게 합니다(모델 호출 1번 추가).")
    if st.button("대화 지우기"):
        st.session_state.messages = []
    st.divider()
    st.caption("데이터: DA_Seoul_Subway_Access_GIS 공개 결과(서울 법정동 467개, 역 389개). "
               "동까지의 거리는 동 대표점에서 잰 직선거리입니다.")

st.title("서울 지하철 접근성 질의 에이전트")
st.caption("질문하면 LLM이 읽기 전용 도구(SQL·동 찾기)로 데이터를 조회하고, 그 결과로만 답합니다.")

if "messages" not in st.session_state:
    st.session_state.messages = []  # {"role", "content", "details"(답일 때)}

if not st.session_state.messages:
    st.markdown("**예시 질문**")
    for ex in EXAMPLES:
        if st.button(ex, key=f"ex_{ex}"):
            st.session_state.pending = ex
            st.rerun()

for m in st.session_state.messages:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])
        if m.get("details"):
            show_details(m["details"])

question = st.chat_input("질문을 입력하세요") or st.session_state.pop("pending", None)
if question:
    history = [{"role": m["role"], "content": m["content"]}
               for m in st.session_state.messages[-2 * HISTORY_TURNS:]]
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        try:
            client = get_client(provider, api_key)
            with st.spinner("도구로 데이터를 조회하는 중…"):
                r = agent.run(question, client, model, history=history, self_check=self_check)
        except agent.DailyQuotaExceeded:
            st.session_state.messages.pop()  # 답 없는 질문을 다음 질문의 앞 대화로 보내지 않는다
            st.error("API 호출 한도(하루 한도 또는 크레딧)에 걸렸습니다. 나중에 다시 시도하거나 다른 키를 쓰세요.")
            st.stop()
        except Exception as e:  # 키 오류·네트워크 등. 메시지에는 키가 들어가지 않는다
            st.session_state.messages.pop()
            st.error(f"호출 실패: {type(e).__name__}: {str(e)[:300]}")
            st.stop()
        calls = [{"name": c.name, "arguments": c.arguments, "result": c.result} for c in r.tool_calls]
        details = {
            "tool_calls": calls,
            "ungrounded": ungrounded_numbers(r.answer, [calls, question, history]),
            "first_answer": r.first_answer, "first_ungrounded": r.first_ungrounded,
            "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
            "cost": cost_usd(model, r.input_tokens, r.output_tokens),
            "rounds": r.rounds, "seconds": r.seconds, "stopped": r.stopped,
        }
        answer = r.answer or "(빈 답)"
        st.markdown(answer)
        show_details(details)
    st.session_state.messages.append({"role": "assistant", "content": answer, "details": details})
