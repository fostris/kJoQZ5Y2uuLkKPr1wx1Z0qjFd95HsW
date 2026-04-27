"""
Парсер HTML-отчётов брокера Сбербанк.
Извлекает: портфель ЦБ, денежные средства, движение ДС, сделки, пополнения ИИС.
"""

import re
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from bs4 import BeautifulSoup


@dataclass
class Position:
    """Позиция в портфеле ценных бумаг."""
    name: str
    isin: str
    currency: str
    qty: int
    nominal: float
    price_end: float
    value_end: float
    nkd_end: float
    price_start: float
    value_start: float
    nkd_start: float
    change_value: float
    asset_type: str = ""  # bond_ofz_pd, bond_ofz_in, bond_corp, etf, stock


@dataclass
class CashFlow:
    """Движение денежных средств."""
    date: str
    description: str
    currency: str
    credit: float
    debit: float


@dataclass
class Trade:
    """Сделка купли/продажи."""
    trade_date: str
    settle_date: str
    trade_time: str
    name: str
    ticker: str
    currency: str
    side: str  # Покупка / Продажа
    qty: int
    price: float
    amount: float
    nkd: float
    broker_fee: float
    exchange_fee: float
    trade_id: str
    status: str


@dataclass
class Deposit:
    """Зачисление на ИИС."""
    year: str
    date: str
    amount: float
    iis_type: str  # ИИС или ИИС3


@dataclass
class SecurityInfo:
    """Справочник ценных бумаг."""
    ticker: str
    isin: str
    issuer: str
    sec_type: str  # Обыкновенная акция, Корп. облигация, Гос. облигация, Биржевой фонд
    issue: str


@dataclass
class BrokerReport:
    """Полный распарсенный отчёт."""
    report_date: str
    period_start: str
    period_end: str
    investor: str
    contract: str
    total_start: float
    total_end: float
    total_change: float
    securities_start: float
    securities_end: float
    cash_start: float
    cash_end: float
    positions: list = field(default_factory=list)
    cash_flows: list = field(default_factory=list)
    trades: list = field(default_factory=list)
    deposits: list = field(default_factory=list)
    securities_info: list = field(default_factory=list)


def _clean_number(text: str) -> float:
    """Очистка числа из HTML: '58 670.10' -> 58670.10."""
    if not text or not text.strip():
        return 0.0
    text = text.strip().replace("\xa0", "").replace(" ", "").replace("+", "")
    text = text.replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return 0.0


def _clean_text(text: str) -> str:
    """Очистка текста."""
    if not text:
        return ""
    return text.strip().replace("\xa0", " ").replace("\n", " ").strip()


def _classify_security(name: str, isin: str, sec_info: dict) -> str:
    """Определение типа бумаги по ISIN и справочнику."""
    info = sec_info.get(isin)
    if info:
        st = info.sec_type.lower()
        if "государственная облигация" in st:
            # Различаем ОФЗ-ПД и ОФЗ-ИН по номеру серии
            n = name.strip()
            if n.startswith("52") or n.startswith("290"):
                return "bond_ofz_in"
            return "bond_ofz_pd"
        if "корпоративная облигация" in st:
            return "bond_corp"
        if "биржевой фонд" in st:
            return "etf"
        if "акция" in st:
            return "stock"
    # Фоллбэк по имени
    nl = name.lower()
    if "etf" in nl or "бпиф" in nl:
        return "etf"
    if any(x in nl for x in ["офз", "26", "29", "52"]):
        return "bond_ofz_pd"
    return "stock"


def parse_report(html_path: str | Path) -> BrokerReport:
    """Основная функция парсинга HTML-отчёта."""
    html_path = Path(html_path)
    html_content = html_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "html.parser")

    report = BrokerReport(
        report_date="",
        period_start="",
        period_end="",
        investor="",
        contract="",
        total_start=0,
        total_end=0,
        total_change=0,
        securities_start=0,
        securities_end=0,
        cash_start=0,
        cash_end=0,
    )

    # --- Заголовок ---
    h3 = soup.find("h3")
    if h3:
        h3_text = _clean_text(h3.get_text())
        date_match = re.search(r"с (\d{2}\.\d{2}\.\d{4}) по (\d{2}\.\d{2}\.\d{4}).*?дата создания (\d{2}\.\d{2}\.\d{4})", h3_text)
        if date_match:
            report.period_start = date_match.group(1)
            report.period_end = date_match.group(2)
            report.report_date = date_match.group(3)

    # --- Инвестор ---
    for p in soup.find_all("p"):
        p_text = _clean_text(p.get_text())
        if "Инвестор:" in p_text:
            inv_match = re.search(r"Инвестор:\s*(.+?)(?:\s*Договор|$)", p_text)
            if inv_match:
                report.investor = inv_match.group(1).strip()
            contract_match = re.search(r"Договор.*?(\S+)\s+от", p_text)
            if contract_match:
                report.contract = contract_match.group(1)
            break

    # --- Оценка активов ---
    rating_table = soup.find("table", class_="RatingAssets")
    if rating_table:
        data_rows = [
            tr for tr in rating_table.find_all("tr")
            if not any(
                c in (tr.get("class") or [])
                for c in ["table-header", "rn"]
            ) and "summary-row" not in (tr.get("class") or [])
        ]
        for row in data_rows:
            tds = row.find_all("td")
            if len(tds) >= 10:
                report.securities_start = _clean_number(tds[1].get_text())
                report.cash_start = _clean_number(tds[2].get_text())
                report.total_start = _clean_number(tds[3].get_text())
                report.securities_end = _clean_number(tds[4].get_text())
                report.cash_end = _clean_number(tds[5].get_text())
                report.total_end = _clean_number(tds[6].get_text())
                report.total_change = _clean_number(tds[9].get_text())
                break

    # --- Справочник ЦБ (парсим сначала для классификации) ---
    sec_info_map: dict[str, SecurityInfo] = {}
    tables = soup.find_all("table")
    for table in tables:
        headers = table.find_all("tr", class_="table-header")
        if headers:
            header_text = _clean_text(headers[0].get_text())
            if "Эмитент" in header_text and "Код" in header_text:
                for row in table.find_all("tr"):
                    if row.get("class") and any(c in row["class"] for c in ["table-header", "rn", "summary-row"]):
                        continue
                    tds = row.find_all("td")
                    if len(tds) >= 5:
                        ticker = _clean_text(tds[1].get_text())
                        isin = _clean_text(tds[2].get_text())
                        issuer = _clean_text(tds[3].get_text())
                        sec_type = _clean_text(tds[4].get_text())
                        issue = _clean_text(tds[5].get_text()) if len(tds) > 5 else ""
                        if isin:
                            info = SecurityInfo(
                                ticker=ticker,
                                isin=isin,
                                issuer=issuer,
                                sec_type=sec_type,
                                issue=issue,
                            )
                            sec_info_map[isin] = info
                            report.securities_info.append(info)

    # --- Портфель ЦБ ---
    for table in tables:
        headers = table.find_all("tr", class_="table-header")
        if not headers:
            continue
        first_header = _clean_text(headers[0].get_text())
        if "Основной рынок" in first_header and "Начало периода" in first_header and "Конец периода" in first_header:
            for row in table.find_all("tr"):
                cls = row.get("class") or []
                if any(c in cls for c in ["table-header", "rn", "summary-row"]):
                    continue
                tds = row.find_all("td")
                # Строки площадки (colspan) — пропускаем
                if len(tds) < 15:
                    continue
                name = _clean_text(tds[0].get_text())
                isin = _clean_text(tds[1].get_text())
                currency = _clean_text(tds[2].get_text())
                qty_start = int(_clean_number(tds[3].get_text()))
                nominal = _clean_number(tds[4].get_text())
                price_start = _clean_number(tds[5].get_text())
                value_start = _clean_number(tds[6].get_text())
                nkd_start = _clean_number(tds[7].get_text())
                qty_end = int(_clean_number(tds[8].get_text()))
                # tds[9] — nominal end (может отличаться для ОФЗ-ИН)
                price_end = _clean_number(tds[10].get_text())
                value_end = _clean_number(tds[11].get_text())
                nkd_end = _clean_number(tds[12].get_text())
                # tds[13] — change qty
                change_value = _clean_number(tds[14].get_text())

                asset_type = _classify_security(name, isin, sec_info_map)

                pos = Position(
                    name=name,
                    isin=isin,
                    currency=currency,
                    qty=qty_end,
                    nominal=nominal,
                    price_end=price_end,
                    value_end=value_end,
                    nkd_end=nkd_end,
                    price_start=price_start,
                    value_start=value_start,
                    nkd_start=nkd_start,
                    change_value=change_value,
                    asset_type=asset_type,
                )
                report.positions.append(pos)
            break

    # --- Движение ДС ---
    for table in tables:
        headers = table.find_all("tr", class_="table-header")
        if not headers:
            continue
        ht = _clean_text(headers[0].get_text())
        if "Дата" in ht and "Описание операции" in ht and "Сумма зачисления" in ht:
            for row in table.find_all("tr"):
                cls = row.get("class") or []
                if any(c in cls for c in ["table-header", "rn", "summary-row"]):
                    continue
                tds = row.find_all("td")
                if len(tds) < 6:
                    continue
                # Пропускаем colspan строки
                first_td = tds[0]
                if first_td.get("colspan"):
                    continue
                cf = CashFlow(
                    date=_clean_text(tds[0].get_text()),
                    description=_clean_text(tds[2].get_text()),
                    currency=_clean_text(tds[3].get_text()),
                    credit=_clean_number(tds[4].get_text()),
                    debit=_clean_number(tds[5].get_text()),
                )
                report.cash_flows.append(cf)

    # --- Сделки ---
    for table in tables:
        headers = table.find_all("tr", class_="table-header")
        if not headers:
            continue
        ht = _clean_text(headers[0].get_text())
        if "Дата заключения" in ht and "Наименование ЦБ" in ht:
            for row in table.find_all("tr"):
                cls = row.get("class") or []
                if any(c in cls for c in ["table-header", "rn", "summary-row"]):
                    continue
                tds = row.find_all("td")
                if len(tds) < 14:
                    continue
                first_td = tds[0]
                if first_td.get("colspan"):
                    continue
                trade = Trade(
                    trade_date=_clean_text(tds[0].get_text()),
                    settle_date=_clean_text(tds[1].get_text()),
                    trade_time=_clean_text(tds[2].get_text()),
                    name=_clean_text(tds[3].get_text()),
                    ticker=_clean_text(tds[4].get_text()),
                    currency=_clean_text(tds[5].get_text()),
                    side=_clean_text(tds[6].get_text()),
                    qty=int(_clean_number(tds[7].get_text())),
                    price=_clean_number(tds[8].get_text()),
                    amount=_clean_number(tds[9].get_text()),
                    nkd=_clean_number(tds[10].get_text()),
                    broker_fee=_clean_number(tds[11].get_text()),
                    exchange_fee=_clean_number(tds[12].get_text()),
                    trade_id=_clean_text(tds[13].get_text()),
                    status=_clean_text(tds[15].get_text()) if len(tds) > 15 else "",
                )
                report.trades.append(trade)

    # --- Пополнения ИИС ---
    for table in tables:
        headers = table.find_all("tr", class_="table-header")
        if not headers:
            continue
        ht = _clean_text(headers[0].get_text())
        if "Лимит" in ht and "Дата операции" in ht and "Основание операции" in ht:
            current_iis_type = "ИИС"
            current_year = ""
            for row in table.find_all("tr"):
                cls = row.get("class") or []
                if any(c in cls for c in ["table-header", "rn", "summary-row"]):
                    continue
                tds = row.find_all("td")
                # Строки-разделители: "ИИС" или "ИИС3"
                if len(tds) == 1 or (len(tds) > 0 and tds[0].get("colspan")):
                    label = _clean_text(tds[0].get_text())
                    if "ИИС3" in label.replace(" ", ""):
                        current_iis_type = "ИИС-3"
                    elif "ИИС" in label:
                        current_iis_type = "ИИС"
                    continue
                if len(tds) < 4:
                    continue
                year = _clean_text(tds[0].get_text())
                if year:
                    current_year = year
                date = _clean_text(tds[2].get_text())
                amount = _clean_number(tds[3].get_text())
                if date and amount > 0:
                    dep = Deposit(
                        year=current_year,
                        date=date,
                        amount=amount,
                        iis_type=current_iis_type,
                    )
                    report.deposits.append(dep)

    return report


if __name__ == "__main__":
    import sys
    import json

    if len(sys.argv) < 2:
        print("Использование: python parser.py <путь_к_отчёту.html>")
        sys.exit(1)

    report = parse_report(sys.argv[1])
    print(f"Дата отчёта: {report.report_date}")
    print(f"Период: {report.period_start} — {report.period_end}")
    print(f"Инвестор: {report.investor}")
    print(f"Портфель: {report.total_end:,.2f} ₽ (Δ {report.total_change:+,.2f} ₽)")
    print(f"Позиций: {len(report.positions)}")
    print(f"Движений ДС: {len(report.cash_flows)}")
    print(f"Сделок: {len(report.trades)}")
    print(f"Пополнений: {len(report.deposits)}")
