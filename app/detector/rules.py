from app.common.config import DetectorConfig, DipBuyingConfig

RULE_KEY_ALIASES = {
    "avg_1h_trade_value": "buy_1s_bid_trade_value",
    "tps_multiplier": "tps_ratio",
}

STRATEGY_DEFINITIONS = {
    "spike": {
        "strategy_key": "spike",
        "name": "급등 감지",
        "description": "거래대금, TPS, 가격 변동, 강한 매수 유입을 기준으로 급등 후보를 감지합니다.",
        "rules": [
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
        ],
    },
    "dip_buying": {
        "strategy_key": "dip_buying",
        "name": "하따 감지",
        "description": "짧은 시간 급락과 강한 매도 거래대금이 함께 나타난 종목을 감지합니다.",
        "rules": [
            {
                "rule_key": "price_drop_pct",
                "label": "가격 하락률",
                "description": "기준 구간 시작가 대비 현재가가 몇 % 하락했는지 봅니다.",
                "metric_key": "price_drop_pct",
                "operator_default": ">=",
                "sort_order": 10,
            },
            {
                "rule_key": "lookback_minutes",
                "label": "비교 구간(분)",
                "description": "몇 분 전 가격과 비교할지 설정합니다.",
                "metric_key": None,
                "operator_default": "=",
                "sort_order": 20,
                "param_only": True,
            },
            {
                "rule_key": "ask_trade_value",
                "label": "최소 매도 거래대금",
                "description": "비교 구간 동안 누적된 매도 거래대금 하한선입니다.",
                "metric_key": "ask_trade_value",
                "operator_default": ">=",
                "sort_order": 30,
            },
        ],
    },
}


def normalize_rule_key(rule_key: str) -> str:
    return RULE_KEY_ALIASES.get(rule_key, rule_key)


def get_strategy_definition(strategy_key: str) -> dict:
    return STRATEGY_DEFINITIONS[strategy_key]


def get_rule_definitions(strategy_key: str) -> list[dict]:
    return STRATEGY_DEFINITIONS[strategy_key]["rules"]


def get_rule_definition_map(strategy_key: str) -> dict:
    return {rule["rule_key"]: rule for rule in get_rule_definitions(strategy_key)}


def build_default_strategy_bundle(strategy_key: str):
    if strategy_key == "spike":
        config = DetectorConfig()
        strategy = STRATEGY_DEFINITIONS["spike"]
        return {
            "strategy": {
                "strategy_key": "spike",
                "name": strategy["name"],
                "enabled": True,
                "cooldown_seconds": config.cooldown_seconds,
                "interval_seconds": config.interval_seconds,
                "webhook_enabled": True,
                "webhook_url": config.webhook_url,
                "updated_at": None,
            },
            "rules": [
                {
                    "rule_key": "ratio_5m_vs_1h",
                    "label": get_rule_definition_map("spike")["ratio_5m_vs_1h"]["label"],
                    "enabled": True,
                    "operator": get_rule_definition_map("spike")["ratio_5m_vs_1h"]["operator_default"],
                    "threshold_value": config.ratio_5m_vs_1h,
                    "params_json": "{}",
                    "sort_order": get_rule_definition_map("spike")["ratio_5m_vs_1h"]["sort_order"],
                },
                {
                    "rule_key": "tps_ratio",
                    "label": get_rule_definition_map("spike")["tps_ratio"]["label"],
                    "enabled": True,
                    "operator": get_rule_definition_map("spike")["tps_ratio"]["operator_default"],
                    "threshold_value": config.tps_multiplier,
                    "params_json": "{}",
                    "sort_order": get_rule_definition_map("spike")["tps_ratio"]["sort_order"],
                },
                {
                    "rule_key": "price_change_pct",
                    "label": get_rule_definition_map("spike")["price_change_pct"]["label"],
                    "enabled": True,
                    "operator": get_rule_definition_map("spike")["price_change_pct"]["operator_default"],
                    "threshold_value": config.price_change_pct_max,
                    "params_json": "{}",
                    "sort_order": get_rule_definition_map("spike")["price_change_pct"]["sort_order"],
                },
                {
                    "rule_key": "buy_1s_bid_trade_value",
                    "label": get_rule_definition_map("spike")["buy_1s_bid_trade_value"]["label"],
                    "enabled": True,
                    "operator": get_rule_definition_map("spike")["buy_1s_bid_trade_value"]["operator_default"],
                    "threshold_value": config.buy_1s_bid_trade_value_min,
                    "params_json": "{}",
                    "sort_order": get_rule_definition_map("spike")["buy_1s_bid_trade_value"]["sort_order"],
                },
            ],
        }

    if strategy_key == "dip_buying":
        config = DipBuyingConfig()
        strategy = STRATEGY_DEFINITIONS["dip_buying"]
        return {
            "strategy": {
                "strategy_key": "dip_buying",
                "name": strategy["name"],
                "enabled": True,
                "cooldown_seconds": config.cooldown_seconds,
                "interval_seconds": config.interval_seconds,
                "webhook_enabled": True,
                "webhook_url": config.webhook_url,
                "updated_at": None,
            },
            "rules": [
                {
                    "rule_key": "price_drop_pct",
                    "label": get_rule_definition_map("dip_buying")["price_drop_pct"]["label"],
                    "enabled": True,
                    "operator": get_rule_definition_map("dip_buying")["price_drop_pct"]["operator_default"],
                    "threshold_value": config.price_drop_pct,
                    "params_json": "{}",
                    "sort_order": get_rule_definition_map("dip_buying")["price_drop_pct"]["sort_order"],
                },
                {
                    "rule_key": "lookback_minutes",
                    "label": get_rule_definition_map("dip_buying")["lookback_minutes"]["label"],
                    "enabled": True,
                    "operator": get_rule_definition_map("dip_buying")["lookback_minutes"]["operator_default"],
                    "threshold_value": config.lookback_minutes,
                    "params_json": "{}",
                    "sort_order": get_rule_definition_map("dip_buying")["lookback_minutes"]["sort_order"],
                },
                {
                    "rule_key": "ask_trade_value",
                    "label": get_rule_definition_map("dip_buying")["ask_trade_value"]["label"],
                    "enabled": True,
                    "operator": get_rule_definition_map("dip_buying")["ask_trade_value"]["operator_default"],
                    "threshold_value": config.ask_trade_value_min,
                    "params_json": "{}",
                    "sort_order": get_rule_definition_map("dip_buying")["ask_trade_value"]["sort_order"],
                },
            ],
        }

    raise KeyError(f"unknown strategy_key={strategy_key}")


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
    if operator == "=":
        return value == threshold
    raise ValueError(f"unsupported operator: {operator}")


def get_param_threshold(rules: list[dict], rule_key: str, fallback: float):
    for rule in rules:
        if normalize_rule_key(rule["rule_key"]) == rule_key:
            return float(rule["threshold_value"])
    return fallback


def evaluate_rules(strategy_key: str, row: dict, rules: list[dict]):
    rule_definition_map = get_rule_definition_map(strategy_key)
    active_rules = []
    for rule in rules:
        normalized_rule_key = normalize_rule_key(rule["rule_key"])
        if rule.get("enabled") and normalized_rule_key in rule_definition_map:
            active_rules.append({**rule, "rule_key": normalized_rule_key})

    if not active_rules:
        return True, ["no active rules"]

    reasons = []
    for rule in active_rules:
        rule_def = rule_definition_map[rule["rule_key"]]
        if rule_def.get("param_only"):
            reasons.append(f"{rule['rule_key']}={float(rule['threshold_value']):.4f}")
            continue

        metric_value = row.get(rule_def["metric_key"])
        threshold_value = float(rule["threshold_value"])
        passed = compare_metric(metric_value, rule["operator"], threshold_value)
        reasons.append(
            f"{rule['rule_key']}={metric_value:.4f}{rule['operator']}{threshold_value:.4f}"
            if metric_value is not None
            else f"{rule['rule_key']}=NULL"
        )
        if not passed:
            return False, reasons
    return True, reasons
