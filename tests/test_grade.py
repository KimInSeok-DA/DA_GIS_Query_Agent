"""규칙 기반 채점기가 맞는 답은 맞게, 틀린 답은 틀리게 판정하는지 확인한다."""

import json
from pathlib import Path

import pytest

from grade import grade, numbers_in, ungrounded_numbers

ANSWERS = json.loads((Path(__file__).resolve().parent.parent / "eval" / "answers.json").read_text(encoding="utf-8"))


def g(answer, checks, tools=("run_sql",), expected="run_sql"):
    return grade(answer, checks, list(tools), expected)


def check_all(answer, checks):
    return g(answer, checks)["correct"]


TEXT_NUM = [{"kind": "text", "value": "학동"}, {"kind": "number", "value": 44.0, "tol": 1, "unit": "m"}]
MEAN = [{"kind": "number", "value": 630.3571, "tol": 1, "unit": "m"}]
COUNT = [{"kind": "number", "value": 186.0, "tol": 0, "unit": ""}]


@pytest.mark.parametrize(
    "answer, checks, ok",
    [
        ("가장 가까운 역은 학동역이고 직선거리 44m입니다.", TEXT_NUM, True),
        ("가장 가까운 역은 학동역(약 44 m)입니다.", TEXT_NUM, True),
        ("가장 가까운 역은 신논현역이고 44m입니다.", TEXT_NUM, False),
        ("가장 가까운 역은 학동역이고 거리는 데이터에 없습니다.", TEXT_NUM, False),
        ("평균 630.36m입니다.", MEAN, True),
        ("평균 약 630m입니다.", MEAN, True),
        ("평균 0.63km입니다.", MEAN, True),
        ("평균 640m입니다.", MEAN, False),
        ("186개입니다.", COUNT, True),
        ("1,186개입니다.", COUNT, False),
        ("185개입니다.", COUNT, False),
    ],
)
def test_checks(answer, checks, ok):
    assert g(answer, checks)["correct"] is ok


@pytest.mark.parametrize(
    "answer, ok",
    [
        ("버스 정류장 수는 데이터에 없습니다.", True),
        ("해당 정보는 데이터에는 없습니다.", True),
        ("인구 정보는 데이터에 포함되어 있지 않습니다.", True),
        ("데이터에 도보 시간은 없습니다. 직선거리는 44m입니다.", True),
        ("버스 정류장 개수 데이터는 없습니다. 다만 면적은 3.495㎢입니다.", True),
        ("직선거리는 44m입니다. 다만, 제공된 데이터에는 직선거리만 포함되어 있으며 보행 시간 정보는 없습니다.", True),
        ("역삼동의 버스 정류장은 12개입니다.", False),
        ("데이터에 따르면 역삼동의 버스 정류장은 12개입니다.", False),
    ],
)
def test_refuse(answer, ok):
    assert g(answer, [{"kind": "refuse"}], tools=(), expected="none")["correct"] is ok


@pytest.mark.parametrize(
    "answer",
    [
        "데이터에 따르면 12개입니다. 다른 정보는 없습니다.",
        "데이터에 따르면 역삼동에는 버스 정류장이 12개 있고 지하철역은 없습니다.",
    ],
)
def test_refuse_with_made_up_number(answer):
    """알려진 한계: 수치를 지어내면서 '데이터…없'도 쓰면 거절 판정은 통과한다. 이런 답은 근거 검사가 잡는다(1015_10)."""
    assert g(answer, [{"kind": "refuse"}], tools=(), expected="none")["correct"] is True
    assert ungrounded_numbers(answer, [{"rows": []}, "강남구 역삼동에 버스 정류장은 몇 개야?"]) == ["12"]


def test_spacing_ignored():
    checks = [{"kind": "text", "value": "김포공항"}, {"kind": "text", "value": "서울대벤처타운"}]
    assert g("김포 공항역, 서울대 벤처타운역", checks)["correct"] is True
    assert g("김포역", checks)["correct"] is False


def test_clarify():
    checks = [{"kind": "text", "value": "은평구"}, {"kind": "text", "value": "강남구"}, {"kind": "clarify"}]
    assert g("신사동은 은평구와 강남구에 있습니다. 어느 구의 신사동인가요?", checks)["correct"] is True
    assert g("은평구 신사동은 새절역, 강남구 신사동은 압구정역입니다.", checks)["correct"] is False
    assert g("강남구 신사동에서 가장 가까운 역은 압구정역입니까?", checks)["correct"] is False


def test_tool_check():
    checks = [{"kind": "text", "value": "강남구"}]
    assert g("강남구", checks, tools=("run_sql",), expected="find_dong")["tool_ok"] is False
    assert g("강남구", checks, tools=("find_dong", "run_sql"), expected="find_dong")["tool_ok"] is True
    assert g("강남구", checks, tools=(), expected="none")["tool_ok"] is True


def test_numbers_in():
    assert numbers_in("1,234.5m와 2km, 96%") == [1234.5, 2.0, 96.0]
    assert numbers_in("2km", unit="m") == [2000.0]
    assert numbers_in("4.797㎢", unit="m") == [4.797]


def test_absent():
    checks = [{"kind": "refuse"}, {"kind": "absent", "pattern": r"\d+\s*분"}]
    assert g("도보 시간은 데이터에 없습니다. 직선거리는 800m입니다.", checks, tools=(), expected="none")["correct"]
    assert not g("도보 시간은 데이터에 없지만 약 12분 걸릴 것입니다.", checks, tools=(), expected="none")["correct"]


def test_ungrounded_numbers():
    result = {"columns": ["emd_nm", "near_dist_m", "cover_500m"], "rows": [["명동2가", 630.357143, 96.0]]}
    # 반올림·km 환산·문자열 안 숫자·목록 번호는 근거 있음
    assert ungrounded_numbers("1. 명동2가: 630.36m, 0.63km, 96%", [result]) == []
    assert ungrounded_numbers("공동 2위입니다. 630m", [result]) == []
    # 도구 결과에 없는 값(모델이 직접 계산하거나 지어낸 값)
    assert ungrounded_numbers("평균은 640m, 약 8분 거리입니다.", [result]) == ["640", "8"]
    # 질문에 나온 숫자는 근거로 인정
    assert ungrounded_numbers("1km 넘는 동은 없습니다.", [result, "1km가 넘는 동은?"]) == []
    # 질문은 km, 답은 m로 써도 같은 값
    assert ungrounded_numbers("1,500m가 넘는 동은 없습니다.", [result, "1.5km 넘는 동은?"]) == []
    # 음수: 답은 부호 없이 읽으므로 근거도 부호를 뺀다(1016_04 B28)
    assert ungrounded_numbers("강동구 상관계수: -0.303", [{"rows": [["강동구", -0.303274]]}]) == []
    # 열 이름과 데이터 정의 "500m 반경"은 값이 아니다. 지어낸 거리 500m는 그대로 잡는다
    assert ungrounded_numbers("`cover_500m`(역 500m 반경이 덮는 비율)을 보면 됩니다.", [result]) == []
    assert ungrounded_numbers("가장 가까운 역까지 500m입니다.", [{"rows": [["명동2가", 630.357143]]}]) == ["500"]


def test_open_question_is_not_graded():
    assert grade("강남구에서는 논현동이 좋습니다.", [], ["run_sql"], "run_sql")["correct"] is None


@pytest.mark.parametrize("answer, ok", [
    ("성수동은 성수동1가와 성수동2가로 나뉩니다. 성수동1가 2개, 성수동2가 1개입니다.", True),
    ("데이터에 '성수동'은 없고 성수동1가, 성수동2가가 있습니다. 어느 쪽인가요?", True),
    ("성수동1가에는 역이 2개 있습니다.", False),  # 하나로 바꿔치기
])
def test_holdout_ai_seongsu(answer, ok):
    assert check_all(answer, ANSWERS["A02"]) == ok


@pytest.mark.parametrize("answer, ok", [
    ("걷는 시간 데이터는 없습니다. 역에서 5분 거리인 동은 알려 드릴 수 없습니다.", True),  # 질문의 5분을 되풀이
    ("도보 시간 정보는 없습니다. 다만 분당 80m로 보면 400m 이내인 동은 …", False),
])
def test_holdout_ai_five_minutes(answer, ok):
    assert check_all(answer, ANSWERS["A26"]) == ok


@pytest.mark.parametrize("qid, answer, ok", [
    ("A01", "제일 가까운 역은 역삼역(290m)이에요.", True),
    ("A01", "역삼(2호선)입니다.", True),
    ("A01", "역삼동에서 가장 가까운 역은 선릉역입니다.", False),  # '역삼동'만으로는 통과하지 않는다
    ("A09", "네, 동 경계 안에 역이 없는 법정동이 281개 있습니다.", True),
    ("A09", "네, 있어요. 예를 들어 종로구 평창동에는 역이 없습니다.", True),
    ("A09", "아니요, 모든 동에 역이 있습니다. 동작구도 마찬가지입니다.", False),  # '있습니다 동작구'가 '다동'이 되지 않는다
    ("A13", "역세권 비율이 100%인 동이 113개로 공동 1위입니다.", True),
    ("A13", "100%인 동이 여러 곳 있습니다. 예: 회현동3가", True),
    ("A13", "가장 높은 동은 회현동3가(100%)입니다.", False),  # 동점을 무시하고 하나만 고름
    ("A16", "서울교통공사 225개, 한국철도공사 59개 …", True),
    ("A16", "서울교통공사 240개, 한국철도공사 104개 …", True),
    ("A16", "서울교통공사 225개, 한국철도공사 104개 …", False),  # 기준을 섞음
    ("A21", "네, 동 전체가 500m 안에 드는 동은 113개입니다.", True),
    ("A21", "네, 중구 회현동3가처럼 100% 들어가는 동이 있어요.", True),
    ("A21", "네, 중구 회현동1가처럼 많이 들어가는 동이 있어요.", False),  # 회현동1가는 65.7%
    ("A21", "아니요, 그런 동은 데이터에 없습니다.", False),
])
def test_holdout_ai_relaxed_rules(qid, answer, ok):
    assert check_all(answer, ANSWERS[qid]) == ok

@pytest.mark.parametrize("qid, answer, ok", [
    ("B05", "영등포구에는 가장 가까운 역까지 1km가 넘는 동이 없습니다.", True),
    ("B05", "영등포구에서 1km 넘는 동은 0곳이에요.", True),
    ("B05", "영등포구에서는 양화동이 1km를 넘습니다.", False),
    ("B09", "강북구에는 역이 하나도 없는 동은 없습니다. 하나 있는 동은 번동입니다.", True),
    ("B09", "역이 없는 동은 미아동, 하나 있는 동은 번동입니다.", False),  # 틀린 전제에 동조
    ("B11", "가까운 역은 여의나루역(338m)과 여의도역(882m)으로 약 545m 차이 납니다.", True),
    ("B11", "여의나루역과 여의도역 사이 직선거리는 약 960m입니다.", True),
    ("B11", "여의나루역과 여의도역은 약 700m 떨어져 있습니다.", False),
    ("B22", "700m 이내 비율은 동작구가 100%로 가장 높고, 강북구·도봉구가 25%로 가장 낮습니다.", True),
    ("B22", "동작구 100%, 가장 낮은 곳은 금천구 0%입니다.", True),  # 700m 정각을 빼고 센 경우
    ("B22", "동작구가 가장 높고 강북구가 가장 낮습니다.", False),  # 동점인 도봉구를 빠뜨림
    ("B29", "역이 있는 동 중에서는 목동이 1,039m로 가장 멉니다.", True),
    ("B29", "신정동이 485m로 가장 멀고, 가까운 역은 신목동입니다.", False),  # '신목동' 안의 '목동'은 세지 않는다
    ("B41", "마곡동에서 가장 가까운 역은 마곡나루역으로 공항철도와 9호선이 지납니다. 5호선 역은 아닙니다.", True),
    ("B41", "마곡나루역(9호선)입니다.", False),
])
def test_holdout_ai2_rules(qid, answer, ok):
    assert check_all(answer, ANSWERS[qid]) == ok


@pytest.mark.parametrize("qid, answer, ok", [
    ("C01", "망원동 대표점에서 가장 가까운 역은 망원역으로 777m입니다.", True),
    ("C01", "망원동은 가장 가까운 역까지 777m입니다.", False),  # '망원동'만으로는 역 이름을 말한 것이 아니다
    ("C09", "1호선 역이 가장 가까운 동 중 역세권 비율 100%인 곳이 26곳으로 공동 1위입니다.", True),
    ("C09", "가장 높은 곳은 청진동(100%)입니다.", False),  # 동점을 무시하고 하나만 고름
    ("C10", "중구 39개, 영등포구 17개, 서대문구 8개 …", True),  # 신촌 처리에 따라 갈리는 구는 보지 않는다
    ("C10", "중구 37개, 영등포구 17개 …", False),
    ("C31", "네, 가장 가까운 역으로 한 번도 꼽히지 않은 서울 안 역이 107개 있습니다.", True),
    ("C31", "네, 예를 들어 강남구청역은 어느 동의 가장 가까운 역도 아닙니다.", True),
    ("C31", "아니요, 모든 역이 한 번 이상 가장 가까운 역입니다.", False),
    ("C40", "역세권 비율 0%인 동이 26곳이라 20곳만 고를 수 없습니다. 그중 일부는 …", True),
    ("C40", "가장 낮은 20곳은 청운동, 신교동, … 입니다.", False),
])
def test_holdout_ai3_rules(qid, answer, ok):
    assert check_all(answer, ANSWERS[qid]) == ok
