"""Streamlit 화면을 가짜 클라이언트로 띄워 본다(API 호출 없음)."""

from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

import agent
from test_agent import FakeClient, fn_call, resp

APP = str(Path(__file__).resolve().parent.parent / "src" / "app.py")


@pytest.fixture(autouse=True)
def clear_client_cache():
    """화면은 클라이언트를 캐시하므로 테스트마다 비운다."""
    st.cache_resource.clear()


def test_app_answers_with_tool_details(monkeypatch):
    client = FakeClient([
        resp([fn_call("run_sql", {"query": "SELECT count(*) AS n FROM emd"})]),
        resp([], "법정동은 467개입니다. 약 12분 걸립니다."),
        resp([], "법정동은 467개입니다. 약 15분 걸립니다."),  # 자기검증 뒤에도 근거 없는 수치가 남은 경우
    ])
    monkeypatch.setattr(agent, "make_client", lambda provider, api_key=None: client)

    at = AppTest.from_file(APP, default_timeout=30).run()
    assert not at.exception
    at.chat_input[0].set_value("법정동은 몇 개야?").run()
    assert not at.exception
    assert any("467개" in m.value for m in at.markdown)
    # 첫 답의 12는 자기검증이 걸렀고, 다시 답한 15는 근거 없는 수치로 표시된다
    assert any("12" in e.label for e in at.expander)
    assert any("15" in w.value for w in at.warning)
    assert any(c.value == "SELECT count(*) AS n FROM emd" for c in at.code)


def test_follow_up_sends_history(monkeypatch):
    client = FakeClient([resp([], "어느 구의 신사동인가요?"), resp([], "압구정역입니다.")])
    monkeypatch.setattr(agent, "make_client", lambda provider, api_key=None: client)

    at = AppTest.from_file(APP, default_timeout=30).run()
    at.chat_input[0].set_value("신사동에서 가장 가까운 역은?").run()
    at.chat_input[0].set_value("강남구요").run()
    assert not at.exception
    sent = client.requests[-1]["messages"]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[2]["content"] == "어느 구의 신사동인가요?"
