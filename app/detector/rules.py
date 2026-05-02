from app.common.config import DetectorConfig

RULE_KEY_ALIASES = {
    "avg_1h_trade_value": "buy_1s_bid_trade_value",
}


def normalize_rule_key(rule_key: str) -> str:
    return RULE_KEY_ALIASES.get(rule_key, rule_key)

RULE_DEFINITIONS = [
    {
        "rule_key": "ratio_5m_vs_1h",
        "label": "5분 거래대금 / 1시간 평균 비율",
        "description": "최근 5분 거래대금이 평소 대비 얼마나 강하게 늘었는지 봅니다.",
        "metric_key": "ratio_5m_vs_1h",
        "operator_default": ">=",
        "sort_order": 10,
    },
    {
        "rule_key": "tps_ratio",
        "label": "TPS 증가 배수",
        "description": "현재 TPS가 1시간 평균 TPS보다 얼마나 높은지 비교합니다.",
        "metric_key": "tps_ratio",
        "operator_default": ">=",
        "sort_order": 20,
    },
    {
        "rule_key": "price_change_pct",
        "label": "최대 가격 변동률",
        "description": "신호 구간 동안 가격이 과하게 튄 종목은 제외합니다.",
        "metric_key": "price_change_pct",
        "operator_default": "<=",
        "sort_order": 30,
    },
    {
        "rule_key": "buy_1s_bid_trade_value",
        "label": "최근 5분 내 1초 최대 매수 거래대금",
        "description": "최근 5분 구간에서 1초 동안 발생한 매수 거래대금의 최대값을 기준으로 봅니다.",
        "metric_key": "buy_1s_bid_trade_value",
        "operator_default": ">=",
        "sort_order": 40,
    },
]

RULE_DEFINITION_MAP = {rule["rule_key"]: rule for rule in RULE_DEFINITIONS}


def build_default_rules(config: DetectorConfig):
    return [
        {
            "rule_key": "ratio_5m_vs_1h",
            "label": RULE_DEFINITION_MAP["ratio_5m_vs_1h"]["label"],
            "enabled": True,
            "operator": RULE_DEFINITION_MAP["ratio_5m_vs_1h"]["operator_default"],
            "threshold_value": config.ratio_5m_vs_1h,
            "params_json": "{}",
            "sort_order": RULE_DEFINITION_MAP["ratio_5m_vs_1h"]["sort_order"],
        },
        {
            "rule_key": "tps_ratio",
            "label": RULE_DEFINITION_MAP["tps_ratio"]["label"],
            "enabled": True,
            "operator": RULE_DEFINITION_MAP["tps_ratio"]["operator_default"],
            "threshold_value": config.tps_multiplier,
            "params_json": "{}",
            "sort_order": RULE_DEFINITION_MAP["tps_ratio"]["sort_order"],
        },
        {
            "rule_key": "price_change_pct",
            "label": RULE_DEFINITION_MAP["price_change_pct"]["label"],
            "enabled": True,
            "operator": RULE_DEFINITION_MAP["price_change_pct"]["operator_default"],
            "threshold_value": config.price_change_pct_max,
            "params_json": "{}",
            "sort_order": RULE_DEFINITION_MAP["price_change_pct"]["sort_order"],
        },
        {
            "rule_key": "buy_1s_bid_trade_value",
            "label": RULE_DEFINITION_MAP["buy_1s_bid_trade_value"]["label"],
            "enabled": True,
            "operator": RULE_DEFINITION_MAP["buy_1s_bid_trade_value"]["operator_default"],
            "threshold_value": config.buy_1s_bid_trade_value_min,
            "params_json": "{}",
            "sort_order": RULE_DEFINITION_MAP["buy_1s_bid_trade_value"]["sort_order"],
        },
    ]


def compare_metric(value, operator, threshold):
    if value is None:
        return False
    if operator == ">":
        return value > threshold
    if operator == ">=":
        return value >= threshold
    if operator == "<":
        return value < threshold
    if operator == "<=":
        return value <= threshold
    if operator == "==":
        return value == threshold
    raise ValueError(f"unsupported operator: {operator}")


def evaluate_rules(row, rules):
    active_rules = [rule for rule in rules if rule["enabled"]]
    if not active_rules:
        return True, ["no active rules"]

    reasons = []
    for rule in active_rules:
        normalized_rule_key = normalize_rule_key(rule["rule_key"])
        rule_def = RULE_DEFINITION_MAP.get(normalized_rule_key)
        if rule_def is None:
            return False, [f"unknown rule_key={rule['rule_key']}"]

        metric_value = row.get(rule_def["metric_key"])
        threshold_value = float(rule["threshold_value"])
        passed = compare_metric(metric_value, rule["operator"], threshold_value)
        reasons.append(
            f"{normalized_rule_key}={metric_value:.4f}{rule['operator']}{threshold_value:.4f}"
            if metric_value is not None
            else f"{normalized_rule_key}=NULL"
        )
        if not passed:
            return False, reasons
    return True, reasons
