"""에이전트가 쓰는 읽기 전용 도구.

- run_sql: DuckDB 메모리 DB(표 emd·stations)에 SELECT 하나만 실행. 행 수·시간 상한.
  두 경위도 사이 거리를 재는 SQL 함수 dist_m을 쓸 수 있다(공간 계산)
- find_dong: 동 이름(일부) → 법정동 후보. 같은 이름이 여러 구에 있으면 모두 돌려준다

정답 계산(src/answers.py)은 이 모듈을 쓰지 않고 pandas로 따로 계산한다.
"""

import re
import threading
from pathlib import Path

import duckdb
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_ROWS = 200
TIMEOUT_SEC = 5.0
EARTH_RADIUS_M = 6371008.8  # 평균 지구 반지름

# 하버사인 공식으로 두 경위도(도) 사이 대원거리(m). 순수 SQL 매크로라 시간 상한(interrupt)이 그대로 걸린다
DIST_MACRO = f"""
CREATE MACRO dist_m(lon1, lat1, lon2, lat2) AS
    2 * {EARTH_RADIUS_M} * asin(sqrt(
        pow(sin(radians(lat2 - lat1) / 2), 2)
        + cos(radians(lat1)) * cos(radians(lat2)) * pow(sin(radians(lon2 - lon1) / 2), 2)
    ))
"""


def load_tables() -> dict[str, pd.DataFrame]:
    """CSV 2개를 읽는다. 코드 열은 앞자리 0이 없지만 문자열로 둔다(원본 README 기준)."""
    emd = pd.read_csv(DATA_DIR / "emd.csv", encoding="utf-8-sig", dtype={"bjd_cd": str, "sgg_cd": str})
    stations = pd.read_csv(DATA_DIR / "stations.csv", encoding="utf-8-sig", dtype={"station_id": str})
    return {"emd": emd, "stations": stations}


def _connect(tables: dict[str, pd.DataFrame]) -> duckdb.DuckDBPyConnection:
    """표를 메모리에 올린 뒤 파일·네트워크 접근과 설정 변경을 막는다."""
    con = duckdb.connect(":memory:")
    for name, df in tables.items():
        con.register(f"_{name}", df)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM _{name}")
        con.unregister(f"_{name}")
    con.execute(DIST_MACRO)
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


_TABLES = load_tables()
_CON = _connect(_TABLES)


def run_sql(query: str) -> dict:
    """SELECT 문 하나를 실행한다. 성공하면 columns·rows·row_count·truncated, 실패하면 error."""
    query = query.strip().rstrip(";").strip()
    if not query:
        return {"error": "빈 쿼리입니다."}
    try:
        statements = duckdb.extract_statements(query)
    except duckdb.Error as e:
        return {"error": f"SQL 문법 오류: {str(e).split(chr(10) + chr(10) + 'LINE')[0]}"}
    if len(statements) != 1:
        return {"error": "SELECT 문 하나만 실행할 수 있습니다."}
    if statements[0].type != duckdb.StatementType.SELECT:
        return {"error": f"SELECT만 허용합니다(받은 문: {statements[0].type.name})."}

    # 상한보다 1행 더 가져와서 잘렸는지 판단한다
    wrapped = f"SELECT * FROM ({query}) AS q LIMIT {MAX_ROWS + 1}"
    con = _CON.cursor()
    timer = threading.Timer(TIMEOUT_SEC, con.interrupt)
    timer.start()
    try:
        cur = con.execute(wrapped)
        columns = [d[0] for d in cur.description]
        rows = cur.fetchall()
    except duckdb.InterruptException:
        return {"error": f"실행 시간이 {TIMEOUT_SEC:g}초를 넘어 중단했습니다."}
    except duckdb.Error as e:
        # 오류 위치 표시(LINE 1: ...)는 감싼 쿼리를 보여 줘서 혼란스러우므로 뺀다
        return {"error": f"실행 오류: {str(e).split(chr(10) + chr(10) + 'LINE')[0]}"}
    finally:
        timer.cancel()
        con.close()

    truncated = len(rows) > MAX_ROWS
    rows = [[_to_json(v) for v in r] for r in rows[:MAX_ROWS]]
    return {"columns": columns, "rows": rows, "row_count": len(rows), "truncated": truncated}


def _to_json(v):
    if isinstance(v, float):
        return round(v, 6)
    if v is None or isinstance(v, (int, str, bool)):
        return v
    return str(v)


_GU_RE = re.compile(r"([가-힣]+구)\s*")
_ADMIN_DONG_RE = re.compile(r"^(.+?)\d+동$")  # 행정동 표기: 역삼1동 → 역삼동


def find_dong(name: str) -> dict:
    """동 이름(일부)으로 법정동 후보를 찾는다. "강남구 신사동"처럼 구를 붙이면 그 구로 좁힌다."""
    emd = _TABLES["emd"]
    text = re.sub(r"^서울(특별)?시\s*", "", name.strip())
    gu = None
    m = _GU_RE.match(text)
    if m and m.group(1) in set(emd["sgg_nm"]):
        gu, text = m.group(1), text[m.end():]
    text = text.replace(" ", "")
    if not text:
        return {"error": "동 이름을 입력하세요."}

    pool = emd if gu is None else emd[emd["sgg_nm"] == gu]
    note = None
    hit = pool[pool["emd_nm"] == text]
    if hit.empty:
        hit = pool[pool["emd_nm"].str.contains(text, regex=False)]
    if hit.empty and (m := _ADMIN_DONG_RE.match(text)):
        hit = pool[pool["emd_nm"] == m.group(1) + "동"]
        if not hit.empty:
            note = f"'{text}'은 행정동 표기로 보여 법정동 '{m.group(1)}동'으로 찾았습니다."

    cols = ["bjd_cd", "sgg_nm", "emd_nm", "full_nm"]
    candidates = hit[cols].head(20).to_dict(orient="records")
    result = {"query": name, "count": len(hit), "candidates": candidates}
    if len(hit) > 20:
        result["note"] = f"후보 {len(hit)}개 중 20개만 보여 줍니다. 더 구체적으로 입력하세요."
    elif note:
        result["note"] = note
    if hit.empty:
        result["note"] = "데이터에 해당 동이 없습니다(서울 법정동 467개 기준)."
        # 없는 동을 비슷한 동으로 말없이 바꿔 답하지 않도록, 비슷한 동은 따로 '같은 동이 아님'을 붙여 준다(1015_11)
        base = re.sub(r"\d*(가|동)$", "", text)
        if len(base) >= 2:
            similar = pool[pool["emd_nm"].str.startswith(base)]
            if not similar.empty:
                result["similar"] = similar[cols].head(5).to_dict(orient="records")
                result["note"] += (" similar는 이름이 비슷한 다른 동이며 같은 동이 아니다. "
                                   "그 동으로 바꿔 답하지 말고, 없다고 말한 뒤 그 동을 찾는지 사용자에게 물어라.")
    return result


# LLM에 넘길 도구 설명. 형식은 JSON Schema이고, API별 감싸는 방식은 에이전트 코드에서 맞춘다
TOOL_SPECS = [
    {
        "name": "run_sql",
        "description": (
            "서울 법정동별 지하철 접근성 데이터에 DuckDB SQL SELECT 문 하나를 실행한다. "
            f"결과는 최대 {MAX_ROWS}행.\n"
            "표 emd(법정동 467행): bjd_cd 법정동코드(문자열), sgg_cd 구 코드, sgg_nm 구 이름, emd_nm 동 이름, "
            "full_nm 전체 이름, area_km2 면적(㎢), near_station 가장 가까운 역 이름, "
            "near_dist_m 동 대표점에서 그 역까지 직선거리(m), n_station 동 경계 안의 역 수(환승역은 1개), "
            "cover_500m 역 500m 반경이 동 면적을 덮는 비율(%, 0～100), collected 경계 수집일, "
            "rep_lon·rep_lat 대표점 경위도.\n"
            "표 stations(역 389행, 서울 밖 역 포함): station_id, name 역 이름, name_full 원래 표기, "
            "lines 노선 목록(';' 구분, 예 '3호선;8호선'), n_lines 노선 수, "
            "operators 운영기관 목록(';' 구분, 예 '서울교통공사;한국철도공사'), "
            "in_seoul 서울 안이면 1, coord_fixed 좌표 보정 여부, ref_date 기준일, lon·lat 경위도.\n"
            "lines·operators는 한 칸에 여러 값이 들어 있다. 노선별·운영기관별로 셀 때는 그대로 GROUP BY 하지 말고 나눠서 센다. "
            "예: SELECT x, COUNT(*) FROM stations, unnest(string_split(lines, ';')) AS t(x) GROUP BY x\n"
            "같은 노선이 다르게 적힌 경우가 있다(예: '7호선'·'도시철도 7호선', '8호선'·'수도권 광역철도 8호선', "
            "'서울 도시철도 9호선'·'수도권 도시철도 9호선'). 노선을 찾을 때는 x LIKE '%9호선%'처럼 포함 여부로 찾는다.\n"
            "stations에는 역이 속한 구·동 정보가 없다. emd.n_station은 동 안의 역 '수'만 있고 어느 역인지는 없다.\n"
            "공간 계산: dist_m(lon1, lat1, lon2, lat2)는 두 경위도 사이 직선거리(m)를 돌려준다. "
            "예: 동 대표점과 역 사이 dist_m(e.rep_lon, e.rep_lat, s.lon, s.lat). 동까지의 거리는 대표점 기준이다.\n"
            "같은 동 이름이 여러 구에 있을 수 있다. 동 이름이 확실하지 않으면 먼저 find_dong을 쓴다."
        ),
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "DuckDB SELECT 문 하나"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "find_dong",
        "description": (
            "동 이름(일부도 가능)으로 서울 법정동 후보를 찾는다. '종로구 청운동'처럼 구를 붙이면 그 구로 좁힌다. "
            "'역삼1동' 같은 행정동 표기는 법정동 '역삼동'으로 찾는다. "
            "결과의 bjd_cd로 run_sql에서 정확히 조회한다."
        ),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "동 이름, 예: 청운동, 종로구 청운동"}},
            "required": ["name"],
            "additionalProperties": False,
        },
    },
]

TOOLS = {"run_sql": run_sql, "find_dong": find_dong}
