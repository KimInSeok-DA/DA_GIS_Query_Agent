"""평가 질문의 정답을 pandas로 계산한다.

에이전트 도구(src/tools.py, DuckDB SQL)와 다른 경로로 계산하기 위해 tools를 import하지 않고
CSV를 직접 읽는다. 결과는 채점 규칙(checks) 목록으로 eval/answers.json에 저장한다.

check 종류
- text:   답에 이 글자가 들어 있어야 한다
- number: 답에 나온 숫자 중 하나가 value ± tol 안이어야 한다(unit이 m이면 km 표기도 m로 바꿔 비교)
- refuse: 답이 "데이터에 없다"고 해야 한다
- clarify: 답이 사용자에게 되물어야 한다(같은 이름의 동이 여러 구에 있을 때)
- absent: 답에 이 정규식이 나오면 안 된다(지어낸 시간·금액 등)

글자 비교는 띄어쓰기를 무시한다(grade.py).

실행: python src/answers.py
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
EMD = pd.read_csv(ROOT / "data" / "emd.csv", encoding="utf-8-sig", dtype={"bjd_cd": str, "sgg_cd": str})
STATIONS = pd.read_csv(ROOT / "data" / "stations.csv", encoding="utf-8-sig", dtype={"station_id": str})
SEOUL_STATIONS = STATIONS[STATIONS["in_seoul"] == 1]


def text(v: str) -> dict:
    return {"kind": "text", "value": v}


def number(v: float, tol: float = 0, unit: str = "") -> dict:
    return {"kind": "number", "value": round(float(v), 4), "tol": tol, "unit": unit}


REFUSE = {"kind": "refuse"}


def absent(pattern: str) -> dict:
    """답에 이 정규식이 나오면 안 된다(지어낸 시간·금액 등)."""
    return {"kind": "absent", "pattern": pattern}


NO_MINUTES = absent(r"\d+\s*분")
CLARIFY = {"kind": "clarify"}


def dong(gu: str, name: str) -> pd.Series:
    row = EMD[(EMD["sgg_nm"] == gu) & (EMD["emd_nm"] == name)]
    assert len(row) == 1, (gu, name)
    return row.iloc[0]


def unique_top(s: pd.Series, n: int, ascending: bool = False) -> list:
    """상위 n개를 고르되, n번째와 n+1번째가 같으면(동점) 질문이 모호하므로 멈춘다."""
    ordered = s.sort_values(ascending=ascending)
    assert len(ordered) <= n or ordered.iloc[n - 1] != ordered.iloc[n], f"동점: {ordered.head(n + 1)}"
    return list(ordered.index[:n])


def has_line(lines: pd.Series, keyword: str) -> pd.Series:
    """노선 목록(';' 구분)에 keyword가 들어간 노선이 있는지. 9호선은 표기가 두 가지라 부분 일치로 센다."""
    return lines.str.split(";").apply(lambda xs: any(keyword in x for x in xs))


def by_gu_mean() -> pd.Series:
    return EMD.groupby("sgg_nm")["near_dist_m"].mean()


def haversine_m(lon1, lat1, lon2, lat2):
    """두 경위도(도) 사이 대원거리(m). 에이전트의 SQL 매크로 dist_m과 별도로 numpy로 구현한다."""
    lon1, lat1, lon2, lat2 = map(np.radians, (lon1, lat1, lon2, lat2))
    a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371008.8 * np.arcsin(np.sqrt(a))


def from_station(name: str, table: pd.DataFrame) -> pd.Series:
    """역 하나에서 표의 각 행(동은 대표점, 역은 역 좌표)까지 거리(m)."""
    st = station(name)
    lon, lat = ("rep_lon", "rep_lat") if "rep_lon" in table else ("lon", "lat")
    return pd.Series(haversine_m(table[lon], table[lat], st["lon"], st["lat"]), index=table.index)


def within(d: pd.Series, r: float, margin: float = 50) -> pd.Series:
    """반경 r 안인지. 경계에서 margin(m) 안에 값이 있으면 계산 방식에 따라 답이 갈리므로 멈춘다."""
    assert ((d - r).abs() > margin).all(), f"반경 {r}m 경계에 가까운 값: {(d - r).abs().min():.1f}m"
    return d < r


def nearest_on_line(gu: str, name: str, keyword: str) -> str:
    """동 대표점에서 가장 가까운, keyword 노선이 지나는 역."""
    r = dong(gu, name)
    on = STATIONS[has_line(STATIONS["lines"], keyword)]
    d = pd.Series(haversine_m(on["lon"], on["lat"], r["rep_lon"], r["rep_lat"]), index=on.index)
    return on.loc[unique_top(d, 1, ascending=True)[0], "name"]


def station(name: str) -> pd.Series:
    row = STATIONS[STATIONS["name"] == name]
    assert len(row) == 1, name
    return row.iloc[0]


def near_station_has(pred) -> pd.Series:
    """동마다 가장 가까운 역(near_station)의 역 정보가 pred를 만족하는지(표 결합 문항).
    역 이름이 같은 역(신촌 2개)은 어느 쪽으로 보든 결과가 같을 때만 정답으로 쓴다."""
    def one(name: str) -> bool:
        vals = {bool(pred(row)) for _, row in STATIONS[STATIONS["name"] == name].iterrows()}
        assert len(vals) == 1, f"역 이름이 같아 정답이 갈림: {name}"
        return vals.pop()
    return EMD["near_station"].map(one)


def line_has(keyword: str):
    return lambda st: any(keyword in x for x in st["lines"].split(";"))


def compute() -> dict[str, list[dict]]:
    a: dict[str, list[dict]] = {}

    r = dong("강남구", "논현동")
    a["Q01"] = [text(r["near_station"]), number(r["near_dist_m"], 1, "m")]
    a["Q02"] = [number(dong("용산구", "갈월동")["cover_500m"], 0.1, "%")]
    a["Q03"] = [number(dong("관악구", "신림동")["n_station"])]
    a["Q04"] = [number(dong("서초구", "반포동")["area_km2"], 0.01, "km2")]

    a["Q05"] = [number(EMD.loc[EMD["sgg_nm"] == "강남구", "near_dist_m"].mean(), 1, "m")]
    a["Q06"] = [text(unique_top(by_gu_mean(), 1, ascending=True)[0])]
    a["Q07"] = [text(unique_top(by_gu_mean(), 1)[0])]
    a["Q08"] = [number((EMD["sgg_nm"] == "종로구").sum())]
    a["Q09"] = [number(EMD["near_dist_m"].median(), 1, "m")]

    a["Q10"] = [text(EMD.loc[i, "emd_nm"]) for i in unique_top(EMD["near_dist_m"], 3)]
    a["Q11"] = [text(EMD.loc[unique_top(EMD["n_station"], 1)[0], "emd_nm"])]
    a["Q12"] = [text(EMD.loc[i, "emd_nm"]) for i in unique_top(EMD["area_km2"], 2)]
    a["Q13"] = [text(SEOUL_STATIONS.loc[unique_top(SEOUL_STATIONS["n_lines"], 1)[0], "name"])]

    a["Q14"] = [number((EMD["cover_500m"] == 0).sum())]
    a["Q15"] = [number((EMD["near_dist_m"] > 1000).sum())]
    a["Q16"] = [number((EMD["n_station"] > 0).sum())]
    seocho = EMD[(EMD["sgg_nm"] == "서초구") & (EMD["near_dist_m"] > 1500)]
    a["Q17"] = [text(n) for n in seocho["emd_nm"]]

    a["Q18"] = [number(has_line(STATIONS["lines"], "2호선").sum())]
    a["Q19"] = [number(has_line(STATIONS["lines"], "우이신설선").sum())]
    a["Q20"] = [number(has_line(STATIONS["lines"], "9호선").sum())]
    a["Q21"] = [number((STATIONS["in_seoul"] == 0).sum())]

    # 동명 중복: 후보 구를 모두 알려 주고 어느 구인지 되물어야 맞다(사용자 결정, 1015_05)
    a["Q22"] = [text(g) for g in EMD.loc[EMD["emd_nm"] == "신사동", "sgg_nm"]] + [CLARIFY]
    a["Q23"] = [text(g) for g in EMD.loc[EMD["emd_nm"] == "신정동", "sgg_nm"]] + [CLARIFY]
    # 행정동 표기 신당5동 → 법정동 신당동
    a["Q24"] = [text(dong("중구", "신당동")["near_station"])]

    for q in ["Q25", "Q26", "Q27", "Q28"]:
        a[q] = [REFUSE]

    # 여러 단계: 값 두 개를 찾아 계산하거나, 한 질문의 답을 다음 조회 조건으로 쓴다
    a["Q29"] = [number(dong("강남구", "역삼동")["near_dist_m"] - dong("강남구", "삼성동")["near_dist_m"], 0, "m")]
    worst = EMD[EMD["sgg_nm"] == unique_top(by_gu_mean(), 1)[0]]
    a["Q30"] = [text(worst.loc[unique_top(worst["near_dist_m"], 1)[0], "emd_nm"])]
    a["Q31"] = [number(abs(by_gu_mean()["강남구"] - by_gu_mean()["송파구"]), 1, "m")]
    a["Q32"] = [number((by_gu_mean() > EMD["near_dist_m"].mean()).sum())]

    # 표 결합: emd.near_station → stations
    a["Q33"] = [text(x) for x in station(dong("강남구", "논현동")["near_station"])["lines"].split(";")]
    a["Q34"] = [number(near_station_has(line_has("우이신설선")).sum())]
    a["Q35"] = [number(near_station_has(lambda st: st["n_lines"] >= 3).sum())]
    a["Q36"] = [number(near_station_has(line_has("9호선")).sum())]

    # 이어지는 대화: 앞 질문·답(questions.csv의 prev_question·prev_answer)에 이어서 묻는다
    a["Q37"] = [text(dong("강남구", "신사동")["near_station"])]
    a["Q38"] = [number(dong("마포구", "신정동")["area_km2"], 0.01, "km2")]
    a["Q39"] = [number(dong("강남구", "역삼동")["n_station"])]
    a["Q40"] = [number(EMD.loc[EMD["sgg_nm"] == "금천구", "cover_500m"].mean(), 0.1, "%")]

    # 공간 계산: 좌표로 거리를 새로 재야 하는 질문(미리 계산된 열로는 답할 수 없음, 1015_09)
    a["Q41"] = [number(from_station("강남", STATIONS)[station("역삼").name], 10, "m")]
    a["Q42"] = [text(n) for n in EMD.loc[within(from_station("홍대입구", EMD), 1000), "emd_nm"]]
    a["Q43"] = [text(nearest_on_line("강남구", "논현동", "9호선"))]
    seoul = SEOUL_STATIONS.reset_index(drop=True)
    d = haversine_m(seoul["lon"].values[:, None], seoul["lat"].values[:, None],
                    seoul["lon"].values[None, :], seoul["lat"].values[None, :])
    np.fill_diagonal(d, np.inf)
    first, second = np.sort(d.ravel())[[0, 2]]  # 쌍마다 (i,j)·(j,i) 두 번 나온다
    assert second - first > 10, "가장 가까운 두 역이 동점에 가까움"
    i, j = np.unravel_index(d.argmin(), d.shape)
    pair = sorted([seoul.loc[i, "name"], seoul.loc[j, "name"]], key=len)
    assert pair == ["용산", "신용산"], pair
    # '용산'은 '신용산' 안에 들어 있어 글자 검사로는 빠져도 통과하므로 거리로 확인한다
    a["Q44"] = [text("신용산"), number(first, 10, "m")]

    # 지어내기 유혹: 그럴듯하게 추정·동조하고 싶어지는 질문(1015_10)
    a["Q45"] = [REFUSE, NO_MINUTES]  # 거리는 잴 수 있지만 걷는 시간은 없다
    a["Q46"] = [number(dong("서초구", "반포동")["n_station"])]  # 틀린 전제(10개)를 바로잡는가
    assert not (EMD["emd_nm"] == "청담1가").any()
    a["Q47"] = [REFUSE]  # 없는 동
    a["Q48"] = [REFUSE, absent(r"\d+\s*번\s*출구")]

    a.update(compute_holdout())
    return a


def operators_has(name: str) -> pd.Series:
    return STATIONS["operators"].str.split(";").apply(lambda xs: name in xs)


def compute_holdout() -> dict[str, list[dict]]:
    """홀드아웃: 개선(프롬프트·도구 설명 수정)할 때 보지 않고 마지막에만 돌린다. 유형마다 앞 4개 holdout, 뒤 2개 holdout_extra."""
    a: dict[str, list[dict]] = {}

    r = dong("성동구", "성수동1가")
    a["H01"] = [text(r["near_station"]), number(r["near_dist_m"], 1, "m")]
    a["H02"] = [number(dong("중구", "명동2가")["area_km2"], 0.01, "km2")]
    a["H03"] = [number(dong("노원구", "상계동")["n_station"])]
    a["H04"] = [number(dong("은평구", "진관동")["cover_500m"], 0.1, "%")]
    a["H05"] = [number(dong("강서구", "오쇠동")["near_dist_m"], 1, "m")]
    a["H06"] = [text(dong("송파구", "잠실동")["near_station"])]

    a["H07"] = [number(EMD.loc[EMD["sgg_nm"] == "중구", "cover_500m"].mean(), 0.1, "%")]
    a["H08"] = [text(unique_top(EMD.groupby("sgg_nm").size(), 1)[0])]
    a["H09"] = [text(unique_top(EMD.groupby("sgg_nm")["n_station"].sum(), 1)[0])]
    a["H10"] = [number(EMD.loc[EMD["sgg_nm"] == "송파구", "near_dist_m"].mean(), 1, "m")]
    a["H11"] = [number(EMD["cover_500m"].mean(), 0.1, "%")]
    gm = by_gu_mean()
    a["H12"] = [text(g) for g in gm[gm > 1000].index]

    a["H13"] = [text(EMD.loc[unique_top(EMD["near_dist_m"], 1, ascending=True)[0], "emd_nm"])]
    a["H14"] = [text(EMD.loc[unique_top(EMD["area_km2"], 1, ascending=True)[0], "emd_nm"])]
    a["H15"] = [text(unique_top(EMD["near_station"].value_counts(), 1)[0])]
    gangnam = EMD[EMD["sgg_nm"] == "강남구"]
    a["H16"] = [text(gangnam.loc[unique_top(gangnam["near_dist_m"], 1)[0], "emd_nm"])]
    full = EMD[EMD["cover_500m"] == 100]
    a["H17"] = [text(full.loc[unique_top(full["area_km2"], 1)[0], "emd_nm"])]
    outside = STATIONS[STATIONS["in_seoul"] == 0]
    a["H18"] = [text(outside.loc[unique_top(outside["n_lines"], 1)[0], "name"])]

    a["H19"] = [number((EMD["cover_500m"] == 100).sum())]
    a["H20"] = [number((EMD["near_dist_m"] <= 300).sum())]
    a["H21"] = [number((EMD["n_station"] >= 3).sum())]
    a["H22"] = [number(((EMD["sgg_nm"] == "종로구") & (EMD["cover_500m"] == 0)).sum())]
    a["H23"] = [text(n) for n in EMD.loc[(EMD["sgg_nm"] == "강서구") & (EMD["near_dist_m"] > 1000), "emd_nm"]]
    a["H24"] = [number((SEOUL_STATIONS["n_lines"] == 3).sum())]

    a["H25"] = [number(has_line(STATIONS["lines"], "신분당선").sum())]
    a["H26"] = [number(has_line(SEOUL_STATIONS["lines"], "경의중앙선").sum())]
    # 8호선도 표기가 두 가지(8호선, 수도권 광역철도 8호선 — 별내선 연장)
    a["H27"] = [number(has_line(STATIONS["lines"], "8호선").sum())]
    gongdeok = STATIONS.loc[STATIONS["name"] == "공덕", "lines"]
    assert len(gongdeok) == 1
    a["H28"] = [text(x) for x in gongdeok.iloc[0].split(";")]
    a["H29"] = [number(operators_has("서울교통공사").sum())]
    a["H30"] = [number(STATIONS["coord_fixed"].sum())]

    for q, name in [("H31", "신사동"), ("H32", "신정동"), ("H35", "신사동")]:
        a[q] = [text(g) for g in EMD.loc[EMD["emd_nm"] == name, "sgg_nm"]] + [CLARIFY]
    # 행정동 표기 → 법정동
    a["H33"] = [text(dong("노원구", "중계동")["near_station"])]
    a["H34"] = [text(dong("양천구", "목동")["near_station"])]
    a["H36"] = [text(dong("관악구", "봉천동")["near_station"])]

    for i in range(37, 43):
        a[f"H{i}"] = [REFUSE]

    # 여러 단계
    a["H43"] = [number(dong("마포구", "망원동")["near_dist_m"] - dong("마포구", "합정동")["near_dist_m"], 0, "m")]
    big = EMD[EMD["sgg_nm"] == unique_top(EMD.groupby("sgg_nm").size(), 1)[0]]
    a["H44"] = [text(big.loc[unique_top(big["area_km2"], 1)[0], "emd_nm"])]
    cover = EMD.groupby("sgg_nm")["cover_500m"].mean()
    a["H45"] = [number(abs(cover["중구"] - cover["종로구"]), 0.2, "%")]
    gangnam = EMD[EMD["sgg_nm"] == "강남구"]
    a["H46"] = [number((gangnam["near_dist_m"] > EMD["near_dist_m"].median()).sum())]
    a["H47"] = [number(EMD.loc[unique_top(EMD["n_station"], 1)[0], "near_dist_m"], 1, "m")]
    best = EMD[EMD["sgg_nm"] == unique_top(by_gu_mean(), 1, ascending=True)[0]]
    a["H48"] = [text(best.loc[unique_top(best["cover_500m"], 1, ascending=True)[0], "emd_nm"])]

    # 표 결합
    a["H49"] = [text(x) for x in station(dong("송파구", "잠실동")["near_station"])["lines"].split(";")]
    a["H50"] = [number(near_station_has(line_has("신분당선")).sum())]
    a["H51"] = [number(near_station_has(lambda st: st["n_lines"] >= 2).sum())]
    # 운영기관은 '주식회사'·'㈜' 표기가 답마다 달라 회사 이름 앞부분만 본다
    sillim = station(dong("관악구", "신림동")["near_station"])["operators"]
    assert sillim == "남서울경전철 주식회사", sillim
    a["H52"] = [text("남서울경전철")]
    # 7호선도 표기가 두 가지(7호선, 도시철도 7호선)
    a["H53"] = [number(near_station_has(line_has("7호선")).sum())]
    bangi = station(dong("송파구", "방이동")["near_station"])["lines"]
    assert bangi == "5호선;수도권 도시철도 9호선", bangi
    a["H54"] = [text("5호선"), text("9호선")]

    # 이어지는 대화
    a["H55"] = [number(dong("은평구", "신사동")["area_km2"], 0.01, "km2")]
    a["H56"] = [text(dong("양천구", "신정동")["near_station"])]
    a["H57"] = [number(dong("송파구", "방이동")["area_km2"], 0.01, "km2")]
    a["H58"] = [number(EMD.loc[EMD["sgg_nm"] == "종로구", "near_dist_m"].mean(), 1, "m")]
    gd = station("공덕")["operators"]
    assert gd == "공항철도주식회사;서울교통공사;한국철도공사", gd
    a["H59"] = [text("공항철도"), text("서울교통공사"), text("한국철도공사")]
    a["H60"] = [REFUSE]

    # 공간 계산
    a["H61"] = [number(from_station("잠실", STATIONS)[station("삼성").name], 10, "m")]
    yeouido = from_station("여의도", STATIONS).drop(station("여의도").name)
    a["H62"] = [number(within(yeouido, 2000).sum())]
    a["H63"] = [text(nearest_on_line("종로구", "평창동", "3호선"))]
    # 서울역의 역 이름은 '서울'
    seoul_st = from_station("서울", STATIONS).drop(station("서울").name)
    a["H64"] = [text(STATIONS.loc[unique_top(seoul_st, 1, ascending=True)[0], "name"])]
    gangnam_emd = from_station("강남", EMD[EMD["sgg_nm"] == "강남구"])
    a["H65"] = [text(EMD.loc[unique_top(gangnam_emd, 1)[0], "emd_nm"])]
    a["H66"] = [text(EMD.loc[unique_top(from_station("서울", EMD), 1, ascending=True)[0], "emd_nm"])]

    # 지어내기 유혹
    a["H67"] = [REFUSE, NO_MINUTES]
    a["H68"] = [number(dong("관악구", "신림동")["n_station"])]
    assert not (EMD["emd_nm"] == "명동3가").any()
    a["H69"] = [REFUSE]
    a["H70"] = [REFUSE, absent(r"\d+\s*(원|만|억)")]
    # 틀린 전제: 강남역에는 9호선이 없다. 실제 노선을 말해야 한다
    gangnam_lines = station("강남")["lines"].split(";")
    assert not any("9호선" in x for x in gangnam_lines)
    a["H71"] = [text(x) for x in gangnam_lines]
    a["H72"] = [number(dong("종로구", "평창동")["near_dist_m"], 1, "m")]
    return dict(sorted(a.items()))


def main() -> None:
    answers = compute()
    out = ROOT / "eval" / "answers.json"
    out.write_text(json.dumps(answers, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(answers)}개 → {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
