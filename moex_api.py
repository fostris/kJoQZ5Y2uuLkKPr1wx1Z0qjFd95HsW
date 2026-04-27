"""
Клиент MOEX ISS API для получения купонного календаря облигаций.

MOEX ISS (Informational & Statistical Server) — бесплатный API без регистрации.
Документация: https://iss.moex.com/iss/reference/

Основные эндпоинты:
- /securities/{ISIN}/bondization — расписание купонов и амортизаций
- /securities/{ISIN} — общая информация о бумаге
"""

import json
import time
import logging
import math
from datetime import datetime, date
from dataclasses import dataclass
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import db

logger = logging.getLogger(__name__)

MOEX_BASE = "https://iss.moex.com/iss"
REQUEST_DELAY = 0.25  # Задержка между запросами (MOEX рекомендует не чаще 4 req/s)
YTM_CACHE_TTL_SEC = 300
ISIN_SEARCH_CACHE_TTL_SEC = 3600
FETCH_MAX_RETRIES = 3
FETCH_RETRY_BACKOFF_SEC = 0.5

_YTM_CACHE: dict[str, tuple[float, float | None]] = {}
_ISIN_TO_TICKER_CACHE: dict[str, str | None] = {}
_ISIN_SEARCH_CACHE: dict[str, tuple[float, dict | None]] = {}


@dataclass
class DividendInfo:
    """Информация о дивидендной выплате."""
    ticker: str
    isin: str
    name: str
    record_date: str       # дата фиксации реестра (YYYY-MM-DD)
    dividend_amount: float  # сумма дивиденда на 1 акцию, ₽
    close_date: str        # последний день покупки (T-1 от record_date)


@dataclass
class CouponInfo:
    """Информация о купонной выплате."""
    isin: str
    name: str
    coupon_date: str       # YYYY-MM-DD
    record_date: str       # дата фиксации реестра
    coupon_rate: float     # ставка купона, %
    coupon_amount: float   # сумма купона на 1 бумагу, ₽
    nominal: float         # текущий номинал
    coupon_number: int     # номер купона


def _is_retryable_error(error: URLError | HTTPError) -> bool:
    code = getattr(error, "code", None)
    if code is None:
        return True
    return int(code) in (429, 500, 502, 503, 504)


def _fetch_json(
    url: str,
    *,
    return_status: bool = False,
) -> dict | tuple[dict, int | None, str | None]:
    """GET-запрос к MOEX ISS с retry/backoff для временных ошибок."""
    req = Request(url, headers={"User-Agent": "BrokerDashboard/1.0"})
    last_error: URLError | HTTPError | None = None
    status_code: int | None = None

    for attempt in range(1, FETCH_MAX_RETRIES + 1):
        try:
            with urlopen(req, timeout=15) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if return_status:
                    return payload, getattr(resp, "status", None), None
                return payload
        except (URLError, HTTPError) as error:
            last_error = error
            status_code = getattr(error, "code", None)
            retryable = _is_retryable_error(error)
            has_retry = attempt < FETCH_MAX_RETRIES
            if retryable and has_retry:
                sleep_seconds = FETCH_RETRY_BACKOFF_SEC * (2 ** (attempt - 1))
                logger.warning(
                    "MOEX API temporary error (attempt %s/%s): %s → %s. Retry in %.2fs.",
                    attempt,
                    FETCH_MAX_RETRIES,
                    url,
                    error,
                    sleep_seconds,
                )
                time.sleep(sleep_seconds)
                continue
            break

    logger.error(
        "MOEX API error after %s attempts: %s → %s",
        FETCH_MAX_RETRIES,
        url,
        last_error,
    )
    if return_status:
        return {}, status_code, str(last_error) if last_error else "unknown error"
    return {}


def _iss_to_rows(data: dict, block: str) -> list[dict]:
    """
    Конвертация формата ISS в список словарей.
    ISS возвращает {block: {columns: [...], data: [[...], ...]}}.
    """
    if block not in data:
        return []
    columns = data[block].get("columns", [])
    rows = data[block].get("data", [])
    return [dict(zip(columns, row)) for row in rows]


def _search_security_by_isin(isin: str) -> dict | None:
    """Найти карточку бумаги по ISIN через /securities.json?q=..."""
    if not isin:
        return None

    now = time.time()
    cached = _ISIN_SEARCH_CACHE.get(isin)
    if cached and (now - cached[0] <= ISIN_SEARCH_CACHE_TTL_SEC):
        return cached[1]

    search_url = f"{MOEX_BASE}/securities.json?iss.meta=off&q={isin}"
    search_data = _fetch_json(search_url)
    securities = _iss_to_rows(search_data, "securities") if search_data else []
    for sec in securities:
        if sec.get("isin") == isin:
            _ISIN_SEARCH_CACHE[isin] = (now, sec)
            return sec

    _ISIN_SEARCH_CACHE[isin] = (now, None)
    return None


def _to_float(value) -> float | None:
    """Безопасно привести значение ISS к float."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_bond_ytm_from_marketdata(data: dict) -> float | None:
    """
    Извлечь YTM из блока marketdata endpoint securities/{ticker}.json.
    Используется поле YIELD (в процентах).
    """
    market_rows = _iss_to_rows(data, "marketdata")
    if not market_rows:
        return None

    with_yield = []
    for row in market_rows:
        ytm = _to_float(row.get("YIELD"))
        if ytm is not None:
            with_yield.append((row, ytm))

    if not with_yield:
        return None

    # Основной рынок облигаций MOEX, при его наличии берём его в первую очередь.
    for row, ytm in with_yield:
        if row.get("BOARDID") == "TQOB":
            return ytm

    # Иначе выбираем строку с максимальным оборотом.
    best_row, best_ytm = max(
        with_yield,
        key=lambda item: _to_float(item[0].get("VALTODAY")) or 0.0,
    )
    if best_row:
        return best_ytm

    return with_yield[0][1]


def fetch_bond_ytm(ticker: str) -> float | None:
    """
    Получить YTM облигации по SECID/тикеру через marketdata.
    Возвращает значение в процентах или None.
    """
    if not ticker:
        return None

    now = time.time()
    cached = _YTM_CACHE.get(ticker)
    if cached and (now - cached[0] <= YTM_CACHE_TTL_SEC):
        return cached[1]

    url = (
        f"{MOEX_BASE}/engines/stock/markets/bonds/securities/{ticker}.json"
        f"?iss.meta=off&iss.only=marketdata"
    )
    data = _fetch_json(url)
    if not data:
        _YTM_CACHE[ticker] = (now, None)
        return None

    ytm = extract_bond_ytm_from_marketdata(data)
    _YTM_CACHE[ticker] = (now, ytm)
    return ytm


def get_bond_ytm_by_isin(isin: str) -> float | None:
    """
    Получить YTM облигации по ISIN.
    Возвращает значение в процентах или None.
    """
    if not isin:
        return None

    ticker = get_ticker_by_isin(isin) or isin
    return fetch_bond_ytm(ticker)


def format_ytm(value: float | None) -> str:
    """Формат YTM для UI."""
    if value is None:
        return "—"
    if isinstance(value, float) and math.isnan(value):
        return "—"
    return f"{value:.2f}%"


def get_bond_coupons(isin: str) -> list[CouponInfo]:
    """
    Получить все купоны облигации по ISIN.
    
    Endpoint: /securities/{ISIN}/bondization.json
    """
    url = f"{MOEX_BASE}/securities/{isin}/bondization.json?iss.meta=off&limit=100"
    data = _fetch_json(url)

    if not data:
        return []

    coupons_raw = _iss_to_rows(data, "coupons")
    result = []

    for c in coupons_raw:
        coupon_date = c.get("coupondate", "")
        if not coupon_date:
            continue

        result.append(CouponInfo(
            isin=isin,
            name=c.get("name", ""),
            coupon_date=coupon_date,
            record_date=c.get("recorddate", ""),
            coupon_rate=c.get("valueprc") or 0.0,
            coupon_amount=c.get("value") or 0.0,
            nominal=c.get("facevalue") or 1000.0,
            coupon_number=c.get("couponperiod") or 0,
        ))

    return result


def get_bond_info(isin: str) -> dict:
    """
    Общая информация о бумаге: название, номинал, дата погашения.
    """
    url = f"{MOEX_BASE}/securities/{isin}.json?iss.meta=off"
    data = _fetch_json(url)

    if not data:
        return {}

    description = _iss_to_rows(data, "description")
    info = {}
    for row in description:
        name = row.get("name", "")
        value = row.get("value", "")
        if name == "NAME":
            info["name"] = value
        elif name == "FACEVALUE":
            info["nominal"] = float(value) if value else 1000.0
        elif name == "MATDATE":
            info["maturity_date"] = value
        elif name == "COUPONPERCENT":
            info["coupon_rate"] = float(value) if value else 0.0
        elif name == "ISSUEDATE":
            info["issue_date"] = value
        elif name == "COUPONFREQUENCY":
            info["coupon_frequency"] = int(value) if value else 0

    return info


@dataclass
class AmortizationInfo:
    """Информация об амортизации облигации."""
    isin: str
    amort_date: str        # YYYY-MM-DD
    facevalue: float       # номинал после амортизации
    initial_facevalue: float
    value_prc: float       # % от номинала


def get_bond_amortizations(isin: str) -> list[AmortizationInfo]:
    """
    Получить расписание амортизаций облигации.
    Endpoint: /securities/{ISIN}/bondization.json → блок amortizations
    """
    url = f"{MOEX_BASE}/securities/{isin}/bondization.json?iss.meta=off&limit=100"
    data = _fetch_json(url)

    if not data:
        return []

    amort_raw = _iss_to_rows(data, "amortizations")
    result = []

    for a in amort_raw:
        amort_date = a.get("amortdate", "")
        if not amort_date:
            continue

        result.append(AmortizationInfo(
            isin=isin,
            amort_date=amort_date,
            facevalue=a.get("facevalue") or 0.0,
            initial_facevalue=a.get("initialfacevalue") or 1000.0,
            value_prc=a.get("valueprc") or 0.0,
        ))

    return result


def sync_maturity_for_portfolio(positions: list) -> dict:
    """
    Получить даты погашений и амортизаций для всех облигаций в портфеле.
    """
    stats = {"synced": 0, "errors": [], "bonds_processed": 0}

    bonds = [
        p for p in positions
        if p["asset_type"] in ("bond_ofz_pd", "bond_ofz_in", "bond_corp")
    ]

    if not bonds:
        return stats

    for pos in bonds:
        isin = pos["isin"]
        name = pos["name"]
        qty = pos["qty"]
        nominal = pos.get("nominal", 1000)

        if not isin:
            continue

        logger.info(f"Загрузка погашений: {name} ({isin})")

        try:
            info = get_bond_info(isin)
            amorts = get_bond_amortizations(isin)
        except Exception as e:
            stats["errors"].append(f"{name}: {e}")
            continue

        stats["bonds_processed"] += 1

        maturity_date = info.get("maturity_date", "")
        coupon_rate = info.get("coupon_rate", 0)

        # Сохраняем инфо о погашении
        if maturity_date:
            maturity_value = nominal * qty  # Сумма к получению при погашении
            db.upsert_bond_maturity(
                isin=isin,
                name=name,
                maturity_date=maturity_date,
                nominal=nominal,
                qty=qty,
                maturity_value=maturity_value,
                coupon_rate=coupon_rate,
                has_amortization=len(amorts) > 1,  # >1 значит частичные выплаты
            )
            stats["synced"] += 1

        # Сохраняем амортизации
        for a in amorts:
            amort_value = a.value_prc / 100 * nominal * qty if a.value_prc else 0
            db.upsert_amortization(
                isin=isin,
                name=name,
                amort_date=a.amort_date,
                value_prc=a.value_prc,
                facevalue_after=a.facevalue,
                amort_value=amort_value,
                qty=qty,
            )

        time.sleep(REQUEST_DELAY)

    return stats


def sync_coupons_for_portfolio(positions: list, future_only: bool = True) -> dict:
    """
    Синхронизация купонного календаря для всех облигаций в портфеле.
    
    Args:
        positions: список позиций из БД (dict-like с полями isin, name, qty, asset_type)
        future_only: загружать только будущие купоны
    
    Returns:
        dict со статистикой: {synced: int, skipped: int, errors: list}
    """
    stats = {"synced": 0, "skipped": 0, "errors": [], "bonds_processed": 0}
    today = date.today().isoformat()

    # Фильтруем только облигации
    bonds = [
        p for p in positions
        if p["asset_type"] in ("bond_ofz_pd", "bond_ofz_in", "bond_corp")
    ]

    if not bonds:
        return stats

    for pos in bonds:
        isin = pos["isin"]
        name = pos["name"]
        qty = pos["qty"]

        if not isin:
            stats["skipped"] += 1
            continue

        logger.info(f"Загрузка купонов: {name} ({isin})")

        try:
            coupons = get_bond_coupons(isin)
        except Exception as e:
            stats["errors"].append(f"{name}: {e}")
            continue

        stats["bonds_processed"] += 1

        for c in coupons:
            # Пропускаем прошедшие если нужны только будущие
            if future_only and c.coupon_date < today:
                continue

            # Пропускаем купоны без суммы (ещё не определена)
            if c.coupon_amount <= 0:
                continue

            expected_income = c.coupon_amount * qty

            db.upsert_coupon(
                isin=isin,
                name=name,
                coupon_date=c.coupon_date,
                coupon_rate=c.coupon_rate,
                coupon_amount=c.coupon_amount,
                nominal=c.nominal,
                qty=qty,
                expected_income=expected_income,
            )
            stats["synced"] += 1

        # Пауза между запросами
        time.sleep(REQUEST_DELAY)

    return stats


def get_stock_dividends(ticker: str) -> list[DividendInfo]:
    """
    Получить историю дивидендов акции по тикеру.

    Endpoint: /securities/{ticker}/dividends.json
    """
    url = f"{MOEX_BASE}/securities/{ticker}/dividends.json?iss.meta=off"
    data = _fetch_json(url)

    if not data:
        return []

    divs_raw = _iss_to_rows(data, "dividends")
    result = []

    for d in divs_raw:
        record_date = d.get("registryclosedate", "")
        if not record_date:
            continue

        result.append(DividendInfo(
            ticker=ticker,
            isin=d.get("isin", ""),
            name=d.get("secid", ticker),
            record_date=record_date,
            dividend_amount=d.get("value") or 0.0,
            close_date=d.get("ldate", ""),
        ))

    return result


def get_ticker_by_isin(isin: str) -> str | None:
    """Получить тикер по ISIN через MOEX API."""
    if not isin:
        return None

    if isin in _ISIN_TO_TICKER_CACHE:
        return _ISIN_TO_TICKER_CACHE[isin]

    url = f"{MOEX_BASE}/securities/{isin}.json?iss.meta=off&iss.only=boards"
    data = _fetch_json(url)
    boards = _iss_to_rows(data, "boards") if data else []
    for board in boards:
        if str(board.get("is_primary")) == "1" and board.get("secid"):
            secid = board.get("secid")
            _ISIN_TO_TICKER_CACHE[isin] = secid
            return secid

    if boards:
        secid = boards[0].get("secid")
        _ISIN_TO_TICKER_CACHE[isin] = secid
        return secid

    # Для части облигаций boards по ISIN пустой, берём SECID через поиск.
    sec = _search_security_by_isin(isin)
    if sec and sec.get("secid"):
        secid = sec.get("secid")
        _ISIN_TO_TICKER_CACHE[isin] = secid
        return secid

    _ISIN_TO_TICKER_CACHE[isin] = None
    return None


def get_issuer_by_isin(isin: str) -> str | None:
    """Получить название эмитента по ISIN."""
    sec = _search_security_by_isin(isin)
    if not sec:
        return None

    issuer = sec.get("emitent_title")
    if issuer:
        return str(issuer)
    return None


def sync_dividends_for_portfolio(positions: list, future_only: bool = True) -> dict:
    """
    Синхронизация дивидендного календаря для всех акций в портфеле.
    """
    stats = {"synced": 0, "skipped": 0, "errors": [], "stocks_processed": 0}
    today = date.today().isoformat()

    stocks = [p for p in positions if p["asset_type"] == "stock"]

    if not stocks:
        return stats

    for pos in stocks:
        isin = pos["isin"]
        name = pos["name"]
        qty = pos["qty"]

        if not isin:
            stats["skipped"] += 1
            continue

        # Получаем тикер по ISIN
        ticker = get_ticker_by_isin(isin)
        if not ticker:
            stats["errors"].append(f"{name}: тикер не найден для {isin}")
            time.sleep(REQUEST_DELAY)
            continue

        logger.info(f"Загрузка дивидендов: {name} ({ticker})")

        try:
            dividends = get_stock_dividends(ticker)
        except Exception as e:
            stats["errors"].append(f"{name}: {e}")
            continue

        stats["stocks_processed"] += 1

        for d in dividends:
            if future_only and d.record_date < today:
                continue
            if d.dividend_amount <= 0:
                continue

            expected_income = d.dividend_amount * qty

            db.upsert_dividend(
                ticker=ticker,
                isin=isin,
                name=name,
                record_date=d.record_date,
                close_date=d.close_date,
                dividend_amount=d.dividend_amount,
                qty=qty,
                expected_income=expected_income,
            )
            stats["synced"] += 1

        time.sleep(REQUEST_DELAY)

    return stats


def sync_all_from_db(future_only: bool = True) -> dict:
    """
    Синхронизация купонов для всех облигаций из последнего отчёта в БД.
    Удобно вызывать из CLI или cron.
    """
    db.init_db()
    latest = db.get_latest_report()
    if not latest:
        return {"error": "Нет отчётов в базе"}

    positions = db.get_positions(latest["id"])
    pos_list = [dict(p) for p in positions]

    return sync_coupons_for_portfolio(pos_list, future_only=future_only)


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    future = "--all" not in sys.argv

    print("📅 Синхронизация купонного календаря с MOEX...")
    stats = sync_all_from_db(future_only=future)

    if "error" in stats:
        print(f"❌ {stats['error']}")
        sys.exit(1)

    print(f"✅ Облигаций обработано: {stats['bonds_processed']}")
    print(f"   Купонов загружено: {stats['synced']}")
    print(f"   Пропущено: {stats['skipped']}")
    if stats["errors"]:
        print(f"   Ошибки:")
        for e in stats["errors"]:
            print(f"     ⚠️  {e}")

    # Показать ближайшие купоны
    coupons = db.get_coupon_calendar()
    today = date.today().isoformat()
    upcoming = [c for c in coupons if c["coupon_date"] >= today]

    if upcoming:
        print(f"\n📆 Ближайшие {min(10, len(upcoming))} купонов:")
        total = 0
        for c in upcoming[:10]:
            income = c["expected_income"]
            total += income
            print(f"   {c['coupon_date']}  {c['name']:25s}  {c['coupon_amount']:>8.2f} ₽ × {c['qty']} = {income:>10.2f} ₽")
        print(f"\n   Итого ожидаемый доход: {total:,.2f} ₽")


# ─── Индекс Мосбиржи (IMOEX) ───

def get_imoex_history(date_from: str, date_to: str) -> list[dict]:
    """
    Получить историю индекса МосБиржи (IMOEX).

    Args:
        date_from: начало периода, YYYY-MM-DD
        date_to: конец периода, YYYY-MM-DD

    Returns:
        Список dict с ключами: date, open, close, high, low, value
    """
    results = []
    start = 0
    page_size = 100

    while True:
        url = (
            f"{MOEX_BASE}/history/engines/stock/markets/index/securities/IMOEX.json"
            f"?iss.meta=off&from={date_from}&till={date_to}"
            f"&start={start}&history.columns=TRADEDATE,OPEN,CLOSE,HIGH,LOW,VALUE"
        )
        data = _fetch_json(url)
        if not data:
            break

        rows = _iss_to_rows(data, "history")
        if not rows:
            break

        for r in rows:
            close = r.get("CLOSE")
            if close and close > 0:
                results.append({
                    "date": r.get("TRADEDATE", ""),
                    "open": r.get("OPEN") or 0,
                    "close": close,
                    "high": r.get("HIGH") or 0,
                    "low": r.get("LOW") or 0,
                    "value": r.get("VALUE") or 0,
                })

        start += page_size
        if len(rows) < page_size:
            break

        time.sleep(REQUEST_DELAY)

    return results
