"""읽기 전용 도구의 안전장치와 동 찾기 규칙을 확인한다(API 호출 없음)."""

import pytest

from tools import MAX_ROWS, find_dong, run_sql


def test_select_returns_rows():
    r = run_sql("SELECT count(*) AS n FROM emd")
    assert r["columns"] == ["n"] and r["rows"] == [[467]]
    assert run_sql("SELECT count(*) FROM stations")["rows"] == [[389]]


def test_order_by_is_kept():
    r = run_sql("SELECT emd_nm FROM emd ORDER BY near_dist_m DESC LIMIT 1")
    assert r["rows"] == [["평창동"]]


def test_with_clause_allowed():
    r = run_sql("WITH g AS (SELECT sgg_nm, count(*) AS n FROM emd GROUP BY sgg_nm) SELECT count(*) FROM g")
    assert r["rows"] == [[25]]


def test_codes_are_strings():
    r = run_sql("SELECT bjd_cd FROM emd WHERE emd_nm = '청운동'")
    assert r["rows"] == [["1111010100"]]


def test_row_limit():
    r = run_sql("SELECT * FROM emd")
    assert r["row_count"] == MAX_ROWS and r["truncated"] is True


@pytest.mark.parametrize(
    "query",
    [
        "DROP TABLE emd",
        "DELETE FROM emd",
        "INSERT INTO emd SELECT * FROM emd",
        "UPDATE emd SET near_dist_m = 0",
        "CREATE TABLE x AS SELECT 1",
        "SET threads = 1",
        "COPY emd TO 'x.csv'",
        "ATTACH 'x.db'",
        "INSTALL httpfs",
        "SELECT 1; DROP TABLE emd",
        "SELECT * FROM read_csv('data/emd.csv')",
    ],
)
def test_non_select_rejected(query):
    assert "error" in run_sql(query)
    assert run_sql("SELECT count(*) FROM emd")["rows"] == [[467]]  # 표가 그대로인지


def test_timeout():
    r = run_sql("SELECT count(*) FROM range(100000000000)")
    assert "시간" in r["error"]


@pytest.mark.parametrize("query", [
    "SELECT count(*) AS n FROM emd -- 법정동 수",  # 감싸는 쿼리의 닫는 괄호가 주석에 먹히지 않아야 한다(holdout_ai2 B15)
    "SELECT count(*) AS n FROM emd; -- 법정동 수",
    "SELECT count(*) AS n FROM emd; /* 법정동 수 */ ;",
    "SELECT count(*) AS n FROM emd;",
])
def test_trailing_comment_and_semicolon_allowed(query):
    assert run_sql(query)["rows"] == [[467]]


def test_semicolon_then_second_statement_still_rejected():
    assert "error" in run_sql("SELECT 1; -- c\nDROP TABLE emd")


def test_error_message_hides_wrapper():
    r = run_sql("SELECT nope FROM emd")
    assert "error" in r and "LIMIT" not in r["error"]


def test_duplicate_dong_returns_all():
    r = find_dong("신사동")
    assert r["count"] == 2
    assert {c["sgg_nm"] for c in r["candidates"]} == {"은평구", "강남구"}


def test_gu_narrows():
    r = find_dong("양천구 신정동")
    assert r["count"] == 1 and r["candidates"][0]["sgg_nm"] == "양천구"


def test_admin_dong_maps_to_legal_dong():
    r = find_dong("역삼1동")
    assert r["count"] == 1 and r["candidates"][0]["emd_nm"] == "역삼동" and "행정동" in r["note"]


def test_missing_dong():
    r = find_dong("없는동")
    assert r["count"] == 0 and "데이터에 해당 동이 없습니다" in r["note"]


def test_too_many_candidates_capped():
    r = find_dong("가")
    assert len(r["candidates"]) == 20 and r["count"] > 20


def test_dist_m_macro():
    """SQL 매크로 dist_m이 정답 계산(numpy)과 같은 거리를 내는지."""
    import answers

    r = run_sql("SELECT a.lon, a.lat, b.lon, b.lat, dist_m(a.lon, a.lat, b.lon, b.lat) "
                "FROM stations a, stations b WHERE a.name = '강남' AND b.name = '역삼'")
    lon1, lat1, lon2, lat2, d = r["rows"][0]
    assert abs(d - answers.haversine_m(lon1, lat1, lon2, lat2)) < 0.01
    assert 800 < d < 840


def test_find_dong_similar_is_marked_different():
    """없는 동(청담1가)은 후보로 주지 않고, 비슷한 동은 similar로 따로 '같은 동이 아님'을 붙인다."""
    r = find_dong("강남구 청담1가")
    assert r["count"] == 0 and r["candidates"] == []
    assert [c["emd_nm"] for c in r["similar"]] == ["청담동"]
    assert "같은 동이 아니다" in r["note"]
    assert "similar" not in find_dong("없는동")


def test_multi_value_split_example_runs():
    # 도구 설명에 둔 여러 값 열 나눠 세기 예시가 실제로 돈다(1016_03). 운영기관을 나누면 조합이 아니라 기관별로 센다
    res = run_sql("SELECT x, COUNT(*) AS n FROM stations, unnest(string_split(operators, ';')) AS t(x) "
                  "WHERE in_seoul = 1 GROUP BY x")
    counts = dict(res["rows"])
    assert not any(";" in k for k in counts)
    assert counts["서울교통공사"] == 225 and counts["한국철도공사"] == 59
