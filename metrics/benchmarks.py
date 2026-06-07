"""
metrics/benchmarks.py
=====================
Региональные медианы и сигмы для финансовых мультипликаторов
(источник: Damodaran / MSCI 2023-24).

Публичный API:
    rate_regional(metric, value, region) → "ideal" | "good" | "warn" | "na"
    score_record(ratings)               → int 0-100
    REGIONAL_BM                         — сырые данные бенчмарков
"""

# Структура: metric → { region: (median, sigma) }
REGIONAL_BM: dict[str, dict[str, tuple]] = {
    "pe_ratio":        {"US": (22, 9),     "Europe": (14, 6),   "Asia": (15, 7),   "Emerging": (10, 5),  "KZ": (8, 4),    "Other": (15, 7)},
    "pb_ratio":        {"US": (4.0, 2.0),  "Europe": (1.6, .8), "Asia": (1.4, .7), "Emerging": (1.2, .6),"KZ": (1.0, .5), "Other": (1.8, .9)},
    "ps_ratio":        {"US": (2.8, 1.5),  "Europe": (1.2, .7), "Asia": (1.0, .6), "Emerging": (.8, .5), "KZ": (.7, .4),  "Other": (1.2, .7)},
    "ev_ebitda":       {"US": (15, 6),     "Europe": (9, 4),    "Asia": (10, 5),   "Emerging": (7, 3),   "KZ": (5, 2.5),  "Other": (10, 4)},
    "roe_pct":         {"US": (18, 8),     "Europe": (12, 6),   "Asia": (10, 5),   "Emerging": (14, 7),  "KZ": (18, 8),   "Other": (12, 6)},
    "de_ratio":        {"US": (1.5, .8),   "Europe": (1.2, .7), "Asia": (.9, .5),  "Emerging": (.8, .4), "KZ": (.7, .35), "Other": (1.0, .5)},
    "net_debt_ebitda": {"US": (2.0, 1.0),  "Europe": (1.8, .9), "Asia": (1.5, .8), "Emerging": (1.2, .6),"KZ": (1.0, .5), "Other": (1.5, .7)},
}

# Метрики, где меньшее значение лучше
LOWER_IS_BETTER: frozenset[str] = frozenset({"de_ratio", "net_debt_ebitda"})


def rate_regional(metric: str, value, region: str) -> str:
    """
    Оценить значение метрики относительно регионального бенчмарка.

    Returns:
        "ideal"  — в пределах одной сигмы от медианы
        "good"   — в пределах двух сигм
        "warn"   — за пределами двух сигм (или выше медианы для LOWER_IS_BETTER)
        "na"     — значение отсутствует
    """
    if value is None:
        return "na"

    bm = REGIONAL_BM.get(metric, {})
    median, sigma = bm.get(region) or bm.get("Other", (15, 7))
    v = float(value)

    if metric in LOWER_IS_BETTER:
        if v <= median:              return "ideal"
        if v <= median + sigma:      return "good"
        return "warn"
    else:
        if abs(v - median) <= sigma:       return "ideal"
        if abs(v - median) <= 2 * sigma:   return "good"
        return "warn"


def score_record(ratings: dict) -> int:
    """
    Рассчитать итоговый балл компании на основе рейтингов метрик.

    ideal=2, good=1, warn=0 — нормируется к 0-100.
    Метрики с na исключаются из числителя И знаменателя.
    """
    weights = {"ideal": 2, "good": 1, "warn": 0}
    valid = {k: v for k, v in ratings.items() if v != "na"}
    if not valid:
        return 0
    total = sum(weights[v] for v in valid.values())
    return round(total / (len(valid) * 2) * 100)


def region_medians_for(region: str) -> dict:
    """
    Вернуть медианы и сигмы всех метрик для заданного региона.
    Используется фронтендом для отображения бенчмарков.
    """
    return {
        metric: {
            "median": bm.get(region, bm.get("Other", (0, 0)))[0],
            "sigma":  bm.get(region, bm.get("Other", (0, 0)))[1],
        }
        for metric, bm in REGIONAL_BM.items()
    }
