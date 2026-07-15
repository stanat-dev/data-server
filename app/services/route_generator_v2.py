"""경로 생성(distance-v2): 결정적 파이프라인 (RNG 금지, stdlib 만).

파이프라인:
1. 비용 행렬 사전계산 — haversine 미터 행렬 + felt-cost(분) 행렬.
   felt(d) = min(도보 d/67, 대중교통 10 + d/250). 하한 엔벨로프라 삼각부등식이
   유지된다(2-opt 수렴 = 자기교차 제거 보장의 전제).
2. multi-start NN — 여러 시작점의 NN 투어 중 felt 총합 최소(타이는 앞선 시작점).
   v1 의 places[0] 시작 편향 제거.
3. 2-opt + or-opt 수렴 — first-improvement, 고정 스캔 순서(결정적).
4. split-DP — O(n²·day_count) 로 투어의 일자 경계 최적화.
   목적: max(일자 부하) 최소화. 부하 = Σ체류(타입별 기본값) + Σ이동(felt).
5. 일자 내 재최적화 — ≤ HELD_KARP_MAX_PLACES 는 비트마스크 DP 정확해(open path),
   초과는 multi-start NN + 2-opt/or-opt. 방향은 정규화(정/역 동비용 → 인덱스 사전순).
6. 규칙 보수 패스 — 요청에 item_type 이 하나라도 있으면 사전식(lexicographic)
   티어 벡터 (P0 숙소 마지막, P1 점심창·25분+ 구간, P2 앵커 성지 후반·저녁 식당,
   이동합, P3 카페 창) 가 개선되는 재배치만 수락. 가중치/퍼센트 캡 없음.

계약: v1 응답 구조 + additive 필드(day_load_minutes, over_budget,
suggested_day_count — 초과 시에만 설정). ref 는 불투명 passthrough.
정본 테스트: tests/test_routes_api.py, tests/test_route_v2_contract.py.

이 모듈은 math + app.schemas + route_generator.haversine_meters 외 import 금지
(설정/DB/네트워크 무관, 순수 함수 유지).
"""

from __future__ import annotations

from app.schemas import (
    RouteDayOut,
    RouteGenerateRequest,
    RouteGenerateResponse,
    RouteItemOut,
    RoutePlaceIn,
)
from app.services.route_generator import haversine_meters

ALGORITHM_VERSION = "distance-v2"

WALK_METERS_PER_MINUTE = 67.0  # 도보 약 4km/h (v1 과 동일)
TRANSIT_OVERHEAD_MINUTES = 10.0  # 정류장 이동/대기 프록시
TRANSIT_METERS_PER_MINUTE = 250.0  # 대중교통 약 15km/h (도심 환승 포함 체감)

DAY_START_MINUTES = 9 * 60 + 30  # 일자 시계 시뮬레이션 시작 09:30
DAILY_BUDGET_MINUTES = 600  # 하루 활동 예산 10시간

# 타입별 기본 체류 분 (stay_minutes 미지정 시)
DEFAULT_STAY_MINUTES = {
    "SACRED": 90,
    "TOURIST_SPOT": 60,
    "RESTAURANT": 60,
    "CAFE": 40,
    "ACCOMMODATION": 0,
    "ETC": 60,
}
FALLBACK_STAY_MINUTES = 60  # item_type 도 없을 때

LUNCH_WINDOW = (11 * 60, 14 * 60)  # 점심 식당 도착 허용 창
CAFE_WINDOW = (14 * 60, 16 * 60 + 30)  # 카페 선호 창(오후 휴식)
DINNER_LAST_SLOTS = 3  # 저녁 식당은 마지막 N 슬롯
MAX_LEG_FELT_MINUTES = 25.0  # 이 felt 분을 넘는 단일 구간은 P1 위반

HELD_KARP_MAX_PLACES = 10  # 이하 정확해, 초과 휴리스틱 (순수 파이썬 지연 상한)
MULTI_START_LIMIT = 16  # NN 시작점 수 상한 (결정적 등간격 샘플)
RULE_REPAIR_MAX_EVALS = 4000  # 규칙 패스 후보 평가 상한 (병리적 대형 일자 가드)

_EPS = 1e-9


def felt_minutes(meters: float) -> float:
    """체감 이동 분 — 도보/대중교통 중 싼 쪽(하한 엔벨로프, 메트릭 유지)."""
    return min(meters / WALK_METERS_PER_MINUTE, TRANSIT_OVERHEAD_MINUTES + meters / TRANSIT_METERS_PER_MINUTE)


def _effective_stay(place: RoutePlaceIn) -> int:
    if place.stay_minutes is not None:
        return place.stay_minutes
    if place.item_type is not None:
        return DEFAULT_STAY_MINUTES[place.item_type]
    return FALLBACK_STAY_MINUTES


def _build_matrices(places: list[RoutePlaceIn]) -> tuple[list[list[float]], list[list[float]]]:
    n = len(places)
    dist = [[0.0] * n for _ in range(n)]
    felt = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = haversine_meters(places[i].lat, places[i].lng, places[j].lat, places[j].lng)
            f = felt_minutes(d)
            dist[i][j] = dist[j][i] = d
            felt[i][j] = felt[j][i] = f
    return dist, felt


# ---------------------------------------------------------------- 투어 구성


def _multi_start_nn(indices: list[int], felt: list[list[float]]) -> list[int]:
    n = len(indices)
    if n <= 1:
        return list(indices)
    step = 1 if n <= MULTI_START_LIMIT else -(-n // MULTI_START_LIMIT)  # ceil → 등간격 샘플
    best_tour: list[int] = []
    best_cost = float("inf")
    for si in range(0, n, step):
        start = indices[si]
        unvisited = [idx for idx in indices if idx != start]
        tour = [start]
        total = 0.0
        cur = start
        while unvisited:
            frow = felt[cur]
            pick = 0
            best_leg = frow[unvisited[0]]
            for t in range(1, len(unvisited)):
                leg = frow[unvisited[t]]
                if leg < best_leg - _EPS:  # 타이는 입력 순서 앞쪽 유지(결정적)
                    best_leg = leg
                    pick = t
            cur = unvisited.pop(pick)
            total += best_leg
            tour.append(cur)
        if total < best_cost - _EPS:  # 타이는 앞선 시작점 유지
            best_cost = total
            best_tour = tour
    return best_tour


def _two_opt_pass(tour: list[int], felt: list[list[float]]) -> bool:
    """open path 2-opt 한 pass (first-improvement). 개선 시 True."""
    n = len(tour)
    for i in range(n - 1):
        a = tour[i - 1] if i > 0 else -1
        for j in range(i + 1, n):
            b, c = tour[i], tour[j]
            d = tour[j + 1] if j + 1 < n else -1
            before = (felt[a][b] if a >= 0 else 0.0) + (felt[c][d] if d >= 0 else 0.0)
            after = (felt[a][c] if a >= 0 else 0.0) + (felt[b][d] if d >= 0 else 0.0)
            if after < before - _EPS:
                tour[i : j + 1] = reversed(tour[i : j + 1])
                return True
    return False


def _or_opt_pass(tour: list[int], felt: list[list[float]]) -> bool:
    """길이 1~3 구간 재배치 한 pass (first-improvement). 개선 시 True."""
    n = len(tour)
    for seg_len in (1, 2, 3):
        if n < seg_len + 2:
            continue
        for i in range(n - seg_len + 1):
            a = tour[i - 1] if i > 0 else -1
            b, c = tour[i], tour[i + seg_len - 1]
            d = tour[i + seg_len] if i + seg_len < n else -1
            gain_remove = (
                (felt[a][b] if a >= 0 else 0.0)
                + (felt[c][d] if d >= 0 else 0.0)
                - (felt[a][d] if a >= 0 and d >= 0 else 0.0)
            )
            if gain_remove <= _EPS:
                continue
            seg = tour[i : i + seg_len]
            rest = tour[:i] + tour[i + seg_len :]
            for p in range(len(rest) + 1):
                if p == i:  # 원위치 재삽입
                    continue
                x = rest[p - 1] if p > 0 else -1
                y = rest[p] if p < len(rest) else -1
                cost_insert = (
                    (felt[x][b] if x >= 0 else 0.0)
                    + (felt[c][y] if y >= 0 else 0.0)
                    - (felt[x][y] if x >= 0 and y >= 0 else 0.0)
                )
                if cost_insert < gain_remove - _EPS:
                    tour[:] = rest[:p] + seg + rest[p:]
                    return True
    return False


def _optimize_tour(indices: list[int], felt: list[list[float]]) -> list[int]:
    tour = _multi_start_nn(indices, felt)
    guard = 0
    improved = len(tour) >= 3
    while improved and guard < 200:
        guard += 1
        improved = _two_opt_pass(tour, felt)
        if not improved:
            improved = _or_opt_pass(tour, felt)
    return tour


# ---------------------------------------------------------------- 일자 분할


def _split_min_max(
    tour: list[int], felt: list[list[float]], stays: list[int], day_count: int
) -> list[list[int]]:
    """투어를 day_count 개 연속 구간으로 — max(일자 부하) 최소화 DP (정확해)."""
    n = len(tour)
    prefix_stay = [0.0] * (n + 1)
    for k in range(n):
        prefix_stay[k + 1] = prefix_stay[k] + stays[tour[k]]
    prefix_move = [0.0] * n  # prefix_move[k] = 투어 위치 0..k-1 사이 이동합
    for k in range(1, n):
        prefix_move[k] = prefix_move[k - 1] + felt[tour[k - 1]][tour[k]]

    def seg_load(a: int, b: int) -> float:  # 투어 위치 a..b-1 을 한 일자로
        return (prefix_stay[b] - prefix_stay[a]) + (prefix_move[b - 1] - prefix_move[a])

    inf = float("inf")
    dp = [[inf] * (n + 1) for _ in range(day_count + 1)]
    parent = [[-1] * (n + 1) for _ in range(day_count + 1)]
    dp[0][0] = 0.0
    for d in range(1, day_count + 1):
        for i in range(d, n - (day_count - d) + 1):
            best = inf
            best_j = -1
            for j in range(d - 1, i):
                prev = dp[d - 1][j]
                if prev == inf:
                    continue
                cost = seg_load(j, i)
                v = prev if prev >= cost else cost
                if v < best - _EPS:  # 타이는 앞선 경계 유지(결정적)
                    best = v
                    best_j = j
            dp[d][i] = best
            parent[d][i] = best_j

    bounds: list[tuple[int, int]] = []
    i = n
    for d in range(day_count, 0, -1):
        j = parent[d][i]
        bounds.append((j, i))
        i = j
    bounds.reverse()
    return [[tour[k] for k in range(a, b)] for a, b in bounds]


# ---------------------------------------------------------------- 일자 내 순서


def _held_karp_path(chunk: list[int], felt: list[list[float]]) -> list[int]:
    """자유 양끝 open path TSP 정확해 (비트마스크 DP). len(chunk) ≤ HELD_KARP_MAX_PLACES."""
    m = len(chunk)
    f = [[felt[a][b] for b in chunk] for a in chunk]
    size = 1 << m
    inf = float("inf")
    dp = [[inf] * m for _ in range(size)]
    parent = [[-1] * m for _ in range(size)]
    for i in range(m):
        dp[1 << i][i] = 0.0
    for mask in range(size):
        row = dp[mask]
        for i in range(m):
            base = row[i]
            if base == inf:
                continue
            fi = f[i]
            for j in range(m):
                if mask >> j & 1:
                    continue
                cand = base + fi[j]
                nm = mask | (1 << j)
                if cand < dp[nm][j] - _EPS:
                    dp[nm][j] = cand
                    parent[nm][j] = i
    full = size - 1
    end = min(range(m), key=lambda i: (dp[full][i], i))
    local: list[int] = []
    mask, cur = full, end
    while cur != -1:
        local.append(cur)
        prev = parent[mask][cur]
        mask ^= 1 << cur
        cur = prev
    local.reverse()
    return [chunk[i] for i in local]


def _canonical_orientation(order: list[int]) -> list[int]:
    """open path 는 정/역 동비용(대칭 행렬) — 인덱스 사전순으로 방향 정규화."""
    rev = order[::-1]
    return order if order <= rev else rev


def _reorder_day(chunk: list[int], felt: list[list[float]]) -> list[int]:
    if len(chunk) <= 2:
        return _canonical_orientation(list(chunk))
    if len(chunk) <= HELD_KARP_MAX_PLACES:
        order = _held_karp_path(chunk, felt)
    else:
        order = _optimize_tour(list(chunk), felt)
    return _canonical_orientation(order)


# ---------------------------------------------------------------- 규칙 보수 패스


def _tier_vector(
    order: list[int], places: list[RoutePlaceIn], stays: list[int], felt: list[list[float]]
) -> tuple[int, int, int, int, int]:
    """사전식 비교용 티어 벡터: (P0, P1, P2, 이동합, P3). 작을수록 좋다."""
    m = len(order)
    arrivals = [0.0] * m
    clock = float(DAY_START_MINUTES)
    for k in range(m):
        if k:
            clock += stays[order[k - 1]] + felt[order[k - 1]][order[k]]
        arrivals[k] = clock
    types = [places[i].item_type for i in order]

    # P0: ACCOMMODATION 뒤에 다른 항목이 오면 위반
    p0 = 0
    for pos, ty in enumerate(types):
        if ty == "ACCOMMODATION":
            p0 += sum(1 for other in types[pos + 1 :] if other != "ACCOMMODATION")

    # P1: 점심 식당 도착 창 + 25분 초과 단일 구간
    p1 = 0
    restaurant_positions = [pos for pos, ty in enumerate(types) if ty == "RESTAURANT"]
    if restaurant_positions:
        lunch_arrival = arrivals[restaurant_positions[0]]
        if not (LUNCH_WINDOW[0] <= lunch_arrival <= LUNCH_WINDOW[1]):
            p1 += 1
    total_move = 0.0
    for k in range(1, m):
        leg = felt[order[k - 1]][order[k]]
        total_move += leg
        if leg > MAX_LEG_FELT_MINUTES:
            p1 += 1

    # P2: 앵커 성지(최장 체류, 타이는 앞선 인덱스)는 일자 후반 1/3 + 저녁 식당은 마지막 슬롯
    p2 = 0
    if m >= 3:
        sacred = [i for i in order if places[i].item_type == "SACRED"]
        if sacred:
            anchor = max(sacred, key=lambda i: (stays[i], -i))
            if order.index(anchor) < m - (m + 2) // 3:  # 후반 ceil(m/3) 밖
                p2 += 1
    if len(restaurant_positions) >= 2 and restaurant_positions[-1] < m - DINNER_LAST_SLOTS:
        p2 += 1

    # P3(코스메틱): 카페는 오후 휴식 창
    p3 = 0
    for pos, ty in enumerate(types):
        if ty == "CAFE" and not (CAFE_WINDOW[0] <= arrivals[pos] <= CAFE_WINDOW[1]):
            p3 += 1

    return (p0, p1, p2, round(total_move * 1000), p3)


def _repair_rules(
    order: list[int], places: list[RoutePlaceIn], stays: list[int], felt: list[list[float]]
) -> list[int]:
    """규칙 관련 항목(식당/카페/숙소/앵커 성지)만 재배치 후보로 — 티어 벡터가
    사전식으로 개선될 때만 수락 (상위 티어 비악화가 비교에 내장됨)."""
    order = list(order)
    m = len(order)
    if m < 2:
        return order
    best = _tier_vector(order, places, stays, felt)
    evals = 0
    improved = True
    while improved and evals < RULE_REPAIR_MAX_EVALS:
        improved = False
        movable: list[int] = []
        sacred = [i for i in order if places[i].item_type == "SACRED"]
        anchor = max(sacred, key=lambda i: (stays[i], -i)) if sacred else None
        for pos, idx in enumerate(order):
            ty = places[idx].item_type
            if ty in ("RESTAURANT", "CAFE", "ACCOMMODATION") or idx == anchor:
                movable.append(pos)
        for pos in movable:
            for target in range(m):
                if target == pos:
                    continue
                candidate = order[:]
                item = candidate.pop(pos)
                candidate.insert(target, item)
                evals += 1
                vector = _tier_vector(candidate, places, stays, felt)
                if vector < best:
                    order, best = candidate, vector
                    improved = True
                    break
                if evals >= RULE_REPAIR_MAX_EVALS:
                    break
            if improved or evals >= RULE_REPAIR_MAX_EVALS:
                break
    return order


# ---------------------------------------------------------------- 진입점


def generate_route_v2(req: RouteGenerateRequest) -> RouteGenerateResponse:
    places = req.places
    n = len(places)
    dist, felt = _build_matrices(places)
    stays = [_effective_stay(p) for p in places]

    tour = _optimize_tour(list(range(n)), felt)
    if n <= req.day_count:
        chunks = [[idx] for idx in tour] + [[] for _ in range(req.day_count - n)]
    else:
        chunks = _split_min_max(tour, felt, stays, req.day_count)

    rules_active = any(p.item_type is not None for p in places)
    day_orders: list[list[int]] = []
    for chunk in chunks:
        order = _reorder_day(chunk, felt) if len(chunk) >= 2 else list(chunk)
        if rules_active and len(order) >= 2:
            order = _repair_rules(order, places, stays, felt)
        day_orders.append(order)

    days: list[RouteDayOut] = []
    total_load = 0
    for day_index, order in enumerate(day_orders):
        items: list[RouteItemOut] = []
        load = sum(stays[idx] for idx in order)
        for seq_index, idx in enumerate(order):
            if seq_index == 0:
                distance = None
                move = None
            else:
                prev = order[seq_index - 1]
                distance = round(dist[prev][idx])
                move = max(1, round(felt[prev][idx]))
                load += move
            items.append(
                RouteItemOut(
                    ref=places[idx].ref,
                    sequence_no=seq_index + 1,
                    distance_meter_from_prev=distance,
                    move_minutes_from_prev=move,
                )
            )
        day_load = round(load)
        total_load += day_load
        days.append(
            RouteDayOut(
                day_no=day_index + 1,
                items=items,
                day_load_minutes=day_load,
                over_budget=day_load > DAILY_BUDGET_MINUTES,
            )
        )

    extra: dict[str, int] = {}
    if total_load > req.day_count * DAILY_BUDGET_MINUTES:
        extra["suggested_day_count"] = -(-total_load // DAILY_BUDGET_MINUTES)  # ceil
    return RouteGenerateResponse(algorithm_version=ALGORITHM_VERSION, days=days, **extra)
