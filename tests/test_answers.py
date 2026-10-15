"""정답 계산(src/answers.py)이 원본 저장소 값과 맞는지, 질문 세트와 짝이 맞는지 확인한다."""

import csv
import json
from pathlib import Path

import answers

ROOT = Path(__file__).resolve().parent.parent
QUESTIONS = list(csv.DictReader(open(ROOT / "eval" / "questions.csv", encoding="utf-8")))
COMPUTED = answers.compute()


def test_matches_source_repo():
    """DA_Seoul_Subway_Access_GIS README·validation_report(2026-10-12)에 적힌 값과 대조한다."""
    emd = answers.EMD
    assert len(emd) == 467 and len(answers.STATIONS) == 389
    assert emd["near_dist_m"].median() == 412
    top = emd.loc[emd["near_dist_m"].idxmax()]
    assert (top["sgg_nm"], top["emd_nm"], top["near_dist_m"]) == ("종로구", "평창동", 2928)
    assert (emd["n_station"] > 0).sum() == 186
    assert emd["n_station"].sum() == (answers.STATIONS["in_seoul"] == 1).sum() == 307


def test_ids_match():
    assert [q["id"] for q in QUESTIONS] == list(COMPUTED)


def test_saved_file_is_current():
    saved = json.loads((ROOT / "eval" / "answers.json").read_text(encoding="utf-8"))
    assert saved == COMPUTED, "python src/answers.py로 다시 저장하세요"


def test_answers_not_in_question():
    """정답 글자·숫자가 질문에 이미 있으면 에이전트가 질문을 따라 말하기만 해도 맞게 된다."""
    from grade import numbers_in

    for q in QUESTIONS:
        shown = q["question"] + q["prev_question"] + q["prev_answer"]  # 이어지는 대화는 앞 대화도 본다
        for c in COMPUTED[q["id"]]:
            if c["kind"] == "text":
                assert c["value"] not in shown, q["id"]
            if c["kind"] == "number":
                assert c["value"] not in numbers_in(shown), q["id"]


def test_splits():
    """개선용 48개, 홀드아웃 유형마다 4+2개."""
    from collections import Counter

    assert Counter(q["split"] for q in QUESTIONS) == {"dev": 48, "holdout": 48, "holdout_extra": 24}
    hold = Counter((q["type"], q["split"]) for q in QUESTIONS if q["split"] != "dev")
    assert all(n == (4 if s == "holdout" else 2) for (_, s), n in hold.items())
    dev_q = {q["question"] for q in QUESTIONS if q["split"] == "dev"}
    assert not dev_q & {q["question"] for q in QUESTIONS if q["split"] != "dev"}


def test_types_and_tools():
    assert {q["expected_tool"] for q in QUESTIONS} <= {"run_sql", "find_dong", "none"}
    clarify = {q["id"] for q in QUESTIONS if answers.CLARIFY in COMPUTED[q["id"]]}
    assert clarify == {"Q22", "Q23", "H31", "H32", "H35"}
    for q in QUESTIONS:
        if q["type"] == "데이터에 없음" or q["id"] == "H60":
            assert COMPUTED[q["id"]] == [answers.REFUSE], q["id"]
        elif q["type"] != "지어내기 유혹":
            assert answers.REFUSE not in COMPUTED[q["id"]], q["id"]
        assert bool(q["prev_question"]) == bool(q["prev_answer"]) == (q["type"] == "이어지는 대화"), q["id"]


def test_prev_answers_match_data():
    """이어지는 대화의 앞 답(사람이 써 둔 고정 문장)에 나온 이름·수치가 데이터와 맞는지."""
    e, s = answers.EMD, answers.STATIONS
    gu_mean = answers.by_gu_mean()
    facts = {
        "Q39": ["역삼", "290"], "Q40": [answers.unique_top(gu_mean, 1)[0], f"{gu_mean.max():.1f}"],
        "H57": ["올림픽공원", "303"], "H60": ["학동", "44"],
        "H58": [answers.unique_top(e.groupby("sgg_nm").size(), 1)[0], str(e.groupby("sgg_nm").size().max())],
    }
    prev = {q["id"]: q for q in QUESTIONS}
    assert answers.dong("강남구", "역삼동")["near_station"] == "역삼" and answers.dong("강남구", "역삼동")["near_dist_m"] == 290
    assert answers.dong("송파구", "방이동")["near_station"] == "올림픽공원" and answers.dong("송파구", "방이동")["near_dist_m"] == 303
    assert answers.dong("강남구", "논현동")["near_station"] == "학동" and answers.dong("강남구", "논현동")["near_dist_m"] == 44
    for qid, words in facts.items():
        for w in words:
            assert w in prev[qid]["prev_answer"], (qid, w)
    gongdeok = answers.station("공덕")["lines"].split(";")
    assert all(x in prev["H59"]["prev_answer"] for x in gongdeok)
    assert len(s[s["name"] == "공덕"]) == 1


def test_haversine_matches_source():
    """정답 계산의 거리 공식이 원본 저장소의 가장 가까운 역·거리를 다시 만들어 내는지(공간 계산 문항의 근거)."""
    e, s = answers.EMD, answers.STATIONS
    d = answers.haversine_m(e["rep_lon"].values[:, None], e["rep_lat"].values[:, None],
                            s["lon"].values[None, :], s["lat"].values[None, :])
    assert (s["name"].values[d.argmin(axis=1)] == e["near_station"].values).all()
    assert abs(d.min(axis=1) - e["near_dist_m"]).max() < 10
