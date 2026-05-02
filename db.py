"""
SQLite хранилище для исторических данных портфеля.
Каждый импортированный отчёт сохраняет снимок портфеля за дату.
"""

import sqlite3
from pathlib import Path
from dataclasses import asdict
from contextlib import contextmanager
from datetime import datetime

DB_PATH = Path(__file__).parent / "portfolio.db"

SCHEMA_MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "baseline_schema_snapshot", ""),
    (
        2,
        "add_data_sync_status",
        """
        CREATE TABLE IF NOT EXISTS data_sync_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_source TEXT NOT NULL,
            entity TEXT NOT NULL,
            isin TEXT NOT NULL DEFAULT '',
            fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
            status TEXT NOT NULL,
            error_message TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_data_sync_entity
            ON data_sync_status(data_source, entity, isin, fetched_at);
        """,
    ),
    (
        3,
        "add_issuer_reference",
        """
        CREATE TABLE IF NOT EXISTS issuer_reference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issuer_name TEXT NOT NULL UNIQUE,
            issuer_group TEXT DEFAULT '',
            sector TEXT DEFAULT '',
            issuer_type TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_issuer_reference_name
            ON issuer_reference(issuer_name);
        """,
    ),
    (
        4,
        "add_bond_ratings",
        """
        CREATE TABLE IF NOT EXISTS bond_ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            isin TEXT NOT NULL UNIQUE,
            issuer TEXT DEFAULT '',
            rating TEXT NOT NULL,
            rating_agency TEXT DEFAULT '',
            rating_date TEXT DEFAULT '',
            source_url TEXT DEFAULT '',
            comment TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_bond_ratings_isin
            ON bond_ratings(isin);
        """,
    ),
    (
        5,
        "add_instrument_fx",
        """
        CREATE TABLE IF NOT EXISTS instrument_fx (
            isin TEXT PRIMARY KEY,
            currency TEXT NOT NULL DEFAULT 'RUB',
            exposure_type TEXT NOT NULL DEFAULT 'rub',
            note TEXT DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """,
    ),
]


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """
    )


def get_schema_version(conn: sqlite3.Connection | None = None) -> int:
    """Текущая версия схемы БД по таблице schema_migrations."""
    if conn is None:
        with get_db() as local_conn:
            return get_schema_version(local_conn)

    table_exists = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table' AND name = 'schema_migrations'
        """
    ).fetchone()
    if not table_exists:
        return 0

    row = conn.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations").fetchone()
    return int(row[0] or 0) if row else 0


def apply_migrations(conn: sqlite3.Connection | None = None) -> int:
    """Применить все неприменённые миграции. Возвращает число применённых миграций."""
    if conn is None:
        with get_db() as local_conn:
            return apply_migrations(local_conn)

    _ensure_schema_migrations_table(conn)
    current_version = get_schema_version(conn)
    applied_count = 0

    for version, name, migration_sql in SCHEMA_MIGRATIONS:
        if version <= current_version:
            continue
        if migration_sql.strip():
            conn.executescript(migration_sql)
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (version, name),
        )
        applied_count += 1

    return applied_count


def init_db():
    """Создание таблиц при первом запуске."""
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                period_start TEXT NOT NULL,
                period_end TEXT NOT NULL,
                investor TEXT,
                contract TEXT,
                total_start REAL,
                total_end REAL,
                total_change REAL,
                securities_start REAL,
                securities_end REAL,
                cash_start REAL,
                cash_end REAL,
                imported_at TEXT DEFAULT (datetime('now')),
                UNIQUE(period_end)
            );

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                isin TEXT,
                currency TEXT DEFAULT 'RUB',
                qty INTEGER,
                nominal REAL,
                price_end REAL,
                value_end REAL,
                nkd_end REAL DEFAULT 0,
                price_start REAL,
                value_start REAL,
                nkd_start REAL DEFAULT 0,
                change_value REAL DEFAULT 0,
                asset_type TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS cash_flows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                date TEXT,
                description TEXT,
                currency TEXT DEFAULT 'RUB',
                credit REAL DEFAULT 0,
                debit REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                trade_date TEXT,
                settle_date TEXT,
                trade_time TEXT,
                name TEXT,
                ticker TEXT,
                currency TEXT DEFAULT 'RUB',
                side TEXT,
                qty INTEGER,
                price REAL,
                amount REAL,
                nkd REAL DEFAULT 0,
                broker_fee REAL DEFAULT 0,
                exchange_fee REAL DEFAULT 0,
                trade_id TEXT,
                status TEXT
            );

            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
                year TEXT,
                date TEXT,
                amount REAL,
                iis_type TEXT DEFAULT 'ИИС'
            );

            CREATE TABLE IF NOT EXISTS coupon_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin TEXT NOT NULL,
                name TEXT,
                coupon_date TEXT NOT NULL,
                coupon_rate REAL,
                coupon_amount REAL,
                nominal REAL,
                qty INTEGER,
                expected_income REAL,
                UNIQUE(isin, coupon_date)
            );

            CREATE TABLE IF NOT EXISTS dividend_calendar (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                isin TEXT,
                name TEXT,
                record_date TEXT NOT NULL,
                close_date TEXT,
                dividend_amount REAL,
                qty INTEGER,
                expected_income REAL,
                UNIQUE(ticker, record_date)
            );

            CREATE TABLE IF NOT EXISTS rebalance_targets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_type TEXT NOT NULL UNIQUE,
                target_pct REAL NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS cost_basis (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin TEXT NOT NULL UNIQUE,
                name TEXT,
                avg_price REAL NOT NULL DEFAULT 0,
                total_qty INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0,
                source TEXT DEFAULT 'manual',
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS bond_maturities (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin TEXT NOT NULL UNIQUE,
                name TEXT,
                maturity_date TEXT NOT NULL,
                nominal REAL DEFAULT 1000,
                qty INTEGER DEFAULT 0,
                maturity_value REAL DEFAULT 0,
                coupon_rate REAL DEFAULT 0,
                has_amortization INTEGER DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS bond_amortizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                isin TEXT NOT NULL,
                name TEXT,
                amort_date TEXT NOT NULL,
                value_prc REAL DEFAULT 0,
                facevalue_after REAL DEFAULT 0,
                amort_value REAL DEFAULT 0,
                qty INTEGER DEFAULT 0,
                UNIQUE(isin, amort_date)
            );

            CREATE INDEX IF NOT EXISTS idx_maturity_date ON bond_maturities(maturity_date);
            CREATE INDEX IF NOT EXISTS idx_amort_date ON bond_amortizations(amort_date);

            CREATE INDEX IF NOT EXISTS idx_positions_report ON positions(report_id);
            CREATE INDEX IF NOT EXISTS idx_positions_isin ON positions(isin);
            CREATE INDEX IF NOT EXISTS idx_cash_flows_report ON cash_flows(report_id);
            CREATE INDEX IF NOT EXISTS idx_trades_report ON trades(report_id);
            CREATE INDEX IF NOT EXISTS idx_coupon_date ON coupon_calendar(coupon_date);
            CREATE INDEX IF NOT EXISTS idx_dividend_date ON dividend_calendar(record_date);

            CREATE TABLE IF NOT EXISTS fire_assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'deposit',
                value REAL NOT NULL DEFAULT 0,
                rate REAL DEFAULT 0,
                currency TEXT DEFAULT 'RUB',
                notes TEXT DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now')),
                UNIQUE(name)
            );

            CREATE TABLE IF NOT EXISTS instrument_fx (
                isin TEXT PRIMARY KEY,
                currency TEXT NOT NULL DEFAULT 'RUB',
                exposure_type TEXT NOT NULL DEFAULT 'rub',
                note TEXT DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        apply_migrations(conn)


def import_report(report) -> int:
    """
    Импорт распарсенного отчёта в БД.
    Возвращает ID отчёта или -1 если дубликат.
    """
    with get_db() as conn:
        # Проверяем дубликат
        existing = conn.execute(
            "SELECT id FROM reports WHERE period_end = ?",
            (report.period_end,)
        ).fetchone()

        if existing:
            return -1

        cursor = conn.execute(
            """INSERT INTO reports
               (report_date, period_start, period_end, investor, contract,
                total_start, total_end, total_change,
                securities_start, securities_end, cash_start, cash_end)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                report.report_date, report.period_start, report.period_end,
                report.investor, report.contract,
                report.total_start, report.total_end, report.total_change,
                report.securities_start, report.securities_end,
                report.cash_start, report.cash_end,
            ),
        )
        report_id = cursor.lastrowid

        # Позиции
        for pos in report.positions:
            conn.execute(
                """INSERT INTO positions
                   (report_id, name, isin, currency, qty, nominal,
                    price_end, value_end, nkd_end,
                    price_start, value_start, nkd_start, change_value, asset_type)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report_id, pos.name, pos.isin, pos.currency, pos.qty,
                    pos.nominal, pos.price_end, pos.value_end, pos.nkd_end,
                    pos.price_start, pos.value_start, pos.nkd_start,
                    pos.change_value, pos.asset_type,
                ),
            )

        # Движения ДС
        for cf in report.cash_flows:
            conn.execute(
                """INSERT INTO cash_flows
                   (report_id, date, description, currency, credit, debit)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (report_id, cf.date, cf.description, cf.currency, cf.credit, cf.debit),
            )

        # Сделки
        for t in report.trades:
            conn.execute(
                """INSERT INTO trades
                   (report_id, trade_date, settle_date, trade_time, name, ticker,
                    currency, side, qty, price, amount, nkd,
                    broker_fee, exchange_fee, trade_id, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    report_id, t.trade_date, t.settle_date, t.trade_time,
                    t.name, t.ticker, t.currency, t.side, t.qty, t.price,
                    t.amount, t.nkd, t.broker_fee, t.exchange_fee,
                    t.trade_id, t.status,
                ),
            )

        # Пополнения — upsert по дате+сумме
        for dep in report.deposits:
            conn.execute(
                """INSERT OR IGNORE INTO deposits
                   (report_id, year, date, amount, iis_type)
                   VALUES (?, ?, ?, ?, ?)""",
                (report_id, dep.year, dep.date, dep.amount, dep.iis_type),
            )

        return report_id


def get_latest_report():
    """Последний импортированный отчёт."""
    with get_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM reports
            ORDER BY substr(period_end,7,4)||substr(period_end,4,2)||substr(period_end,1,2) DESC, id DESC
            LIMIT 1
            """
        ).fetchone()


def get_positions(report_id: int):
    """Позиции для конкретного отчёта."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM positions WHERE report_id = ? ORDER BY value_end DESC",
            (report_id,),
        ).fetchall()


def get_all_deposits():
    """Все пополнения ИИС (дедупликация)."""
    with get_db() as conn:
        return conn.execute(
            """SELECT DISTINCT date, amount, iis_type, year
               FROM deposits ORDER BY date""",
        ).fetchall()


def get_cash_flows(report_id: int):
    """Движения ДС для отчёта."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM cash_flows WHERE report_id = ?",
            (report_id,),
        ).fetchall()


def get_trades(report_id: int = None):
    """Сделки, опционально фильтр по отчёту."""
    with get_db() as conn:
        if report_id:
            return conn.execute(
                "SELECT * FROM trades WHERE report_id = ? ORDER BY trade_date DESC",
                (report_id,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM trades ORDER BY trade_date DESC"
        ).fetchall()


def get_portfolio_history():
    """История стоимости портфеля по всем отчётам."""
    with get_db() as conn:
        return conn.execute(
            """SELECT period_end, total_end, securities_end, cash_end, total_change
               FROM reports ORDER BY period_end""",
        ).fetchall()


def get_report_snapshots_summary():
    """Краткие снимки портфеля по отчётам: report_id, period_end, total_value."""
    with get_db() as conn:
        return conn.execute(
            """
            SELECT
                r.id AS report_id,
                r.period_end,
                COALESCE(
                    r.total_end,
                    COALESCE(SUM(COALESCE(p.value_end, 0) + COALESCE(p.nkd_end, 0)), 0) + COALESCE(r.cash_end, 0),
                    0
                ) AS total_value
            FROM reports r
            LEFT JOIN positions p ON p.report_id = r.id
            GROUP BY r.id, r.period_end, r.total_end, r.cash_end
            ORDER BY substr(r.period_end,7,4)||substr(r.period_end,4,2)||substr(r.period_end,1,2)
            """
        ).fetchall()


def get_external_withdrawals():
    """Потенциальные внешние выводы из cash_flows (без сделок/комиссий/купонов)."""
    include_keywords = ("вывод", "списание д/с", "списание дс", "перевод д/с", "перевод дс")
    exclude_keywords = ("сделка", "комисси", "выплата", "купон", "дивиденд")

    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT date, description, debit
            FROM cash_flows
            WHERE COALESCE(debit, 0) > 0
            ORDER BY date
            """
        ).fetchall()

    result = []
    for row in rows:
        description = str(row["description"] or "").strip().lower()
        if not description:
            continue
        if any(token in description for token in exclude_keywords):
            continue
        if not any(token in description for token in include_keywords):
            continue
        result.append(
            {
                "date": row["date"],
                "amount": float(row["debit"] or 0.0),
                "description": row["description"],
            }
        )
    return result


def get_position_history(isin: str):
    """История конкретной позиции по всем отчётам."""
    with get_db() as conn:
        return conn.execute(
            """SELECT r.period_end, p.price_end, p.value_end, p.nkd_end, p.qty
               FROM positions p
               JOIN reports r ON r.id = p.report_id
               WHERE p.isin = ?
               ORDER BY r.period_end""",
            (isin,),
        ).fetchall()


def get_all_reports():
    """Список всех отчётов."""
    with get_db() as conn:
        return conn.execute(
            """
            SELECT *
            FROM reports
            ORDER BY substr(period_end,7,4)||substr(period_end,4,2)||substr(period_end,1,2) DESC, id DESC
            """
        ).fetchall()


def get_deposits_by_year(year: str = None):
    """Пополнения за год."""
    with get_db() as conn:
        if year:
            return conn.execute(
                "SELECT DISTINCT date, amount, iis_type FROM deposits WHERE year = ? ORDER BY date",
                (year,),
            ).fetchall()
        return conn.execute(
            "SELECT DISTINCT year, SUM(amount) as total FROM deposits GROUP BY year ORDER BY year"
        ).fetchall()


def get_coupon_calendar():
    """Календарь купонов."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM coupon_calendar ORDER BY coupon_date"
        ).fetchall()


def upsert_coupon(isin: str, name: str, coupon_date: str,
                  coupon_rate: float, coupon_amount: float,
                  nominal: float, qty: int, expected_income: float):
    """Добавить/обновить запись в календаре купонов."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO coupon_calendar
               (isin, name, coupon_date, coupon_rate, coupon_amount, nominal, qty, expected_income)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(isin, coupon_date) DO UPDATE SET
                 coupon_rate=excluded.coupon_rate,
                 coupon_amount=excluded.coupon_amount,
                 nominal=excluded.nominal,
                 qty=excluded.qty,
                 expected_income=excluded.expected_income""",
            (isin, name, coupon_date, coupon_rate, coupon_amount,
             nominal, qty, expected_income),
        )


# ─── FIRE Assets ───

def get_fire_assets():
    """Все внешние активы для FIRE-трекера."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM fire_assets ORDER BY value DESC"
        ).fetchall()


def upsert_fire_asset(name: str, category: str, value: float,
                      rate: float = 0, currency: str = "RUB", notes: str = ""):
    """Добавить/обновить внешний актив."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO fire_assets (name, category, value, rate, currency, notes, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(name) DO UPDATE SET
                 category=excluded.category,
                 value=excluded.value,
                 rate=excluded.rate,
                 currency=excluded.currency,
                 notes=excluded.notes,
                 updated_at=datetime('now')""",
            (name, category, value, rate, currency, notes),
        )


def delete_fire_asset(asset_id: int):
    """Удалить внешний актив."""
    with get_db() as conn:
        conn.execute("DELETE FROM fire_assets WHERE id = ?", (asset_id,))


def get_fire_assets_total():
    """Сумма всех внешних активов."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(value), 0) as total FROM fire_assets"
        ).fetchone()
        return row["total"]


# ─── Dividend Calendar ───

def upsert_dividend(ticker: str, isin: str, name: str, record_date: str,
                    close_date: str, dividend_amount: float,
                    qty: int, expected_income: float):
    """Добавить/обновить запись в дивидендном календаре."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO dividend_calendar
               (ticker, isin, name, record_date, close_date,
                dividend_amount, qty, expected_income)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(ticker, record_date) DO UPDATE SET
                 isin=excluded.isin,
                 name=excluded.name,
                 close_date=excluded.close_date,
                 dividend_amount=excluded.dividend_amount,
                 qty=excluded.qty,
                 expected_income=excluded.expected_income""",
            (ticker, isin, name, record_date, close_date,
             dividend_amount, qty, expected_income),
        )


def get_dividend_calendar():
    """Все записи дивидендного календаря."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM dividend_calendar ORDER BY record_date"
        ).fetchall()


# ─── Data Freshness ───

def upsert_data_sync_status(
    data_source: str,
    entity: str,
    isin: str | None,
    status: str,
    error_message: str | None = None,
    fetched_at: str | None = None,
):
    """Сохранить запись статуса синхронизации данных по сущности и ISIN."""
    normalized_isin = isin or ""
    effective_fetched_at = fetched_at or datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    with get_db() as conn:
        conn.execute(
            """INSERT INTO data_sync_status
               (data_source, entity, isin, fetched_at, status, error_message)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (data_source, entity, normalized_isin, effective_fetched_at, status, error_message),
        )


def get_data_sync_freshness(entity: str, data_source: str = "moex_iss") -> dict:
    """Агрегированная свежесть данных по сущности."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT isin, fetched_at, status, error_message
               FROM data_sync_status
               WHERE data_source = ? AND entity = ?
               ORDER BY fetched_at DESC""",
            (data_source, entity),
        ).fetchall()

    if not rows:
        return {
            "entity": entity,
            "data_source": data_source,
            "total": 0,
            "success_count": 0,
            "error_count": 0,
            "latest_status": None,
            "latest_at": None,
            "latest_success_at": None,
            "latest_error_at": None,
            "latest_error_message": None,
        }

    success_count = sum(1 for row in rows if row["status"] == "success")
    error_count = sum(1 for row in rows if row["status"] == "error")
    latest_row = rows[0]
    latest_success_row = next((row for row in rows if row["status"] == "success"), None)
    latest_error_row = next((row for row in rows if row["status"] == "error"), None)

    return {
        "entity": entity,
        "data_source": data_source,
        "total": len(rows),
        "success_count": success_count,
        "error_count": error_count,
        "latest_status": latest_row["status"],
        "latest_at": latest_row["fetched_at"],
        "latest_success_at": latest_success_row["fetched_at"] if latest_success_row else None,
        "latest_error_at": latest_error_row["fetched_at"] if latest_error_row else None,
        "latest_error_message": latest_error_row["error_message"] if latest_error_row else None,
    }


# ─── Issuer Reference ───

def get_issuer_references():
    """Все записи ручного справочника эмитентов."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM issuer_reference ORDER BY issuer_name COLLATE NOCASE"
        ).fetchall()


def get_issuer_reference_map() -> dict[str, dict]:
    """Словарь issuer_name -> запись справочника эмитентов."""
    rows = get_issuer_references()
    return {row["issuer_name"]: dict(row) for row in rows}


def upsert_issuer_reference(
    issuer_name: str,
    issuer_group: str = "",
    sector: str = "",
    issuer_type: str = "",
    comment: str = "",
):
    """Добавить/обновить запись справочника эмитентов."""
    normalized_name = (issuer_name or "").strip()
    if not normalized_name:
        raise ValueError("issuer_name is required")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO issuer_reference
               (issuer_name, issuer_group, sector, issuer_type, comment, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(issuer_name) DO UPDATE SET
                 issuer_group=excluded.issuer_group,
                 sector=excluded.sector,
                 issuer_type=excluded.issuer_type,
                 comment=excluded.comment,
                 updated_at=datetime('now')""",
            (
                normalized_name,
                (issuer_group or "").strip(),
                (sector or "").strip(),
                (issuer_type or "").strip(),
                (comment or "").strip(),
            ),
        )


def delete_issuer_reference(issuer_name: str) -> None:
    """Удалить запись из справочника эмитентов по issuer_name."""
    normalized_name = (issuer_name or "").strip()
    if not normalized_name:
        return
    with get_db() as conn:
        conn.execute(
            "DELETE FROM issuer_reference WHERE issuer_name = ?",
            (normalized_name,),
        )


# ─── Bond Ratings ───

def get_bond_ratings():
    """Все записи ручного справочника рейтингов облигаций."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bond_ratings ORDER BY isin COLLATE NOCASE"
        ).fetchall()


def get_bond_ratings_map() -> dict[str, dict]:
    """Словарь ISIN -> запись рейтинга."""
    rows = get_bond_ratings()
    return {str(row["isin"]): dict(row) for row in rows if row["isin"]}


def upsert_bond_rating(
    isin: str,
    issuer: str = "",
    rating: str = "",
    rating_agency: str = "",
    rating_date: str = "",
    source_url: str = "",
    comment: str = "",
) -> None:
    """Добавить/обновить ручной рейтинг облигации по ISIN."""
    normalized_isin = (isin or "").strip().upper()
    normalized_rating = (rating or "").strip()
    if not normalized_isin:
        raise ValueError("isin is required")
    if not normalized_rating:
        raise ValueError("rating is required")

    with get_db() as conn:
        conn.execute(
            """INSERT INTO bond_ratings
               (isin, issuer, rating, rating_agency, rating_date, source_url, comment, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(isin) DO UPDATE SET
                 issuer=excluded.issuer,
                 rating=excluded.rating,
                 rating_agency=excluded.rating_agency,
                 rating_date=excluded.rating_date,
                 source_url=excluded.source_url,
                 comment=excluded.comment,
                 updated_at=datetime('now')""",
            (
                normalized_isin,
                (issuer or "").strip(),
                normalized_rating,
                (rating_agency or "").strip(),
                (rating_date or "").strip(),
                (source_url or "").strip(),
                (comment or "").strip(),
            ),
        )


def delete_bond_rating(isin: str) -> None:
    """Удалить запись рейтинга облигации по ISIN."""
    normalized_isin = (isin or "").strip().upper()
    if not normalized_isin:
        return
    with get_db() as conn:
        conn.execute("DELETE FROM bond_ratings WHERE isin = ?", (normalized_isin,))


# ─── Instrument FX Overrides ───

FX_DEFAULT_CURRENCY = "RUB"
FX_DEFAULT_EXPOSURE_TYPE = "rub"
FX_ALLOWED_CURRENCIES = {"RUB", "USD", "CNY", "EUR", "GOLD"}
FX_ALLOWED_EXPOSURE_TYPES = {"rub", "fx_substitute", "fx_direct", "gold", "commodity_proxy"}


def _normalize_isin(isin: str) -> str:
    return (isin or "").strip().upper()


def get_instrument_fx(isin: str) -> dict:
    """Получить FX-метаданные по ISIN (или безопасные дефолты, если записи нет)."""
    normalized_isin = _normalize_isin(isin)
    if not normalized_isin:
        return {
            "isin": "",
            "currency": FX_DEFAULT_CURRENCY,
            "exposure_type": FX_DEFAULT_EXPOSURE_TYPE,
            "note": "",
            "updated_at": None,
        }

    with get_db() as conn:
        row = conn.execute(
            "SELECT isin, currency, exposure_type, note, updated_at FROM instrument_fx WHERE isin = ?",
            (normalized_isin,),
        ).fetchone()

    if not row:
        return {
            "isin": normalized_isin,
            "currency": FX_DEFAULT_CURRENCY,
            "exposure_type": FX_DEFAULT_EXPOSURE_TYPE,
            "note": "",
            "updated_at": None,
        }
    return dict(row)


def set_instrument_fx(isin: str, currency: str, exposure_type: str, note: str = "") -> None:
    """Добавить/обновить FX-метаданные по ISIN."""
    normalized_isin = _normalize_isin(isin)
    normalized_currency = (currency or FX_DEFAULT_CURRENCY).strip().upper()
    normalized_exposure_type = (exposure_type or FX_DEFAULT_EXPOSURE_TYPE).strip().lower()
    normalized_note = (note or "").strip()

    if not normalized_isin:
        raise ValueError("isin is required")
    if normalized_currency not in FX_ALLOWED_CURRENCIES:
        raise ValueError(f"unsupported currency: {normalized_currency}")
    if normalized_exposure_type not in FX_ALLOWED_EXPOSURE_TYPES:
        raise ValueError(f"unsupported exposure_type: {normalized_exposure_type}")

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO instrument_fx (isin, currency, exposure_type, note, updated_at)
            VALUES (?, ?, ?, ?, datetime('now'))
            ON CONFLICT(isin) DO UPDATE SET
                currency=excluded.currency,
                exposure_type=excluded.exposure_type,
                note=excluded.note,
                updated_at=datetime('now')
            """,
            (normalized_isin, normalized_currency, normalized_exposure_type, normalized_note),
        )


def list_instrument_fx() -> list[sqlite3.Row]:
    """Все пользовательские FX-override записи."""
    with get_db() as conn:
        return conn.execute(
            "SELECT isin, currency, exposure_type, note, updated_at FROM instrument_fx ORDER BY isin"
        ).fetchall()


# ─── Rebalance Targets ───

def get_rebalance_targets():
    """Целевые доли по типам активов."""
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM rebalance_targets").fetchall()
        return {r["asset_type"]: r["target_pct"] for r in rows}


def set_rebalance_targets(targets: dict):
    """Сохранить целевые доли. targets = {"stock": 30, "bond_ofz_pd": 20, ...}"""
    with get_db() as conn:
        conn.execute("DELETE FROM rebalance_targets")
        for asset_type, pct in targets.items():
            conn.execute(
                "INSERT INTO rebalance_targets (asset_type, target_pct) VALUES (?, ?)",
                (asset_type, pct),
            )


# ─── Bond Maturities ───

def upsert_bond_maturity(isin: str, name: str, maturity_date: str,
                         nominal: float, qty: int, maturity_value: float,
                         coupon_rate: float, has_amortization: bool):
    """Добавить/обновить информацию о погашении облигации."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO bond_maturities
               (isin, name, maturity_date, nominal, qty, maturity_value,
                coupon_rate, has_amortization, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(isin) DO UPDATE SET
                 name=excluded.name,
                 maturity_date=excluded.maturity_date,
                 nominal=excluded.nominal,
                 qty=excluded.qty,
                 maturity_value=excluded.maturity_value,
                 coupon_rate=excluded.coupon_rate,
                 has_amortization=excluded.has_amortization,
                 updated_at=datetime('now')""",
            (isin, name, maturity_date, nominal, qty, maturity_value,
             coupon_rate, int(has_amortization)),
        )


def get_bond_maturities():
    """Все погашения облигаций."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bond_maturities ORDER BY maturity_date"
        ).fetchall()


def upsert_amortization(isin: str, name: str, amort_date: str,
                        value_prc: float, facevalue_after: float,
                        amort_value: float, qty: int):
    """Добавить/обновить амортизацию облигации."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO bond_amortizations
               (isin, name, amort_date, value_prc, facevalue_after, amort_value, qty)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(isin, amort_date) DO UPDATE SET
                 name=excluded.name,
                 value_prc=excluded.value_prc,
                 facevalue_after=excluded.facevalue_after,
                 amort_value=excluded.amort_value,
                 qty=excluded.qty""",
            (isin, name, amort_date, value_prc, facevalue_after, amort_value, qty),
        )


def get_bond_amortizations():
    """Все амортизации."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM bond_amortizations ORDER BY amort_date"
        ).fetchall()


# ─── Cost Basis (средняя цена покупки) ───

def get_cost_basis_all():
    """Все записи средних цен покупки."""
    with get_db() as conn:
        return conn.execute(
            "SELECT * FROM cost_basis ORDER BY name"
        ).fetchall()


def get_cost_basis_map():
    """Словарь ISIN → avg_price."""
    with get_db() as conn:
        rows = conn.execute("SELECT isin, avg_price, total_qty, total_cost FROM cost_basis").fetchall()
        return {r["isin"]: dict(r) for r in rows}


def upsert_cost_basis(isin: str, name: str, avg_price: float,
                      total_qty: int = 0, total_cost: float = 0,
                      source: str = "manual"):
    """Добавить/обновить среднюю цену покупки."""
    with get_db() as conn:
        conn.execute(
            """INSERT INTO cost_basis
               (isin, name, avg_price, total_qty, total_cost, source, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(isin) DO UPDATE SET
                 name=excluded.name,
                 avg_price=excluded.avg_price,
                 total_qty=excluded.total_qty,
                 total_cost=excluded.total_cost,
                 source=excluded.source,
                 updated_at=datetime('now')""",
            (isin, name, avg_price, total_qty, total_cost, source),
        )


def calc_cost_basis_from_trades():
    """
    Рассчитать среднюю цену покупки по всем сделкам в БД.
    Метод FIFO: покупки увеличивают позицию, продажи уменьшают.
    Возвращает dict: {ticker: {avg_price, total_qty, total_cost}}
    """
    with get_db() as conn:
        trades = conn.execute(
            """SELECT name, ticker, side, qty, price, amount, nkd
               FROM trades
               ORDER BY trade_date, trade_time"""
        ).fetchall()

    # Агрегация по тикеру
    positions = {}  # ticker → {qty, cost}

    for t in trades:
        ticker = t["ticker"]
        if not ticker:
            continue

        if ticker not in positions:
            positions[ticker] = {"qty": 0, "cost": 0.0, "name": t["name"]}

        pos = positions[ticker]

        if t["side"] == "Покупка":
            pos["qty"] += t["qty"]
            pos["cost"] += t["amount"] + (t["nkd"] or 0)
        elif t["side"] == "Продажа":
            if pos["qty"] > 0:
                # Уменьшаем пропорционально
                sell_ratio = min(t["qty"] / pos["qty"], 1.0)
                pos["cost"] -= pos["cost"] * sell_ratio
                pos["qty"] -= t["qty"]
                pos["qty"] = max(pos["qty"], 0)

    result = {}
    for ticker, pos in positions.items():
        if pos["qty"] > 0:
            avg_price = pos["cost"] / pos["qty"]
            result[ticker] = {
                "name": pos["name"],
                "avg_price": avg_price,
                "total_qty": pos["qty"],
                "total_cost": pos["cost"],
            }

    return result


def sync_cost_basis_from_trades():
    """Пересчитать и сохранить средние цены из сделок (не перезаписывает manual)."""
    calculated = calc_cost_basis_from_trades()

    with get_db() as conn:
        for ticker, data in calculated.items():
            # Ищем ISIN по тикеру из позиций
            row = conn.execute(
                """SELECT DISTINCT p.isin FROM positions p
                   JOIN (SELECT id FROM reports ORDER BY period_end DESC LIMIT 1) r
                   ON p.report_id = r.id
                   WHERE p.name LIKE ? LIMIT 1""",
                (f"%{ticker}%",)
            ).fetchone()

            isin = row["isin"] if row else ticker

            # Не перезаписываем ручные записи
            existing = conn.execute(
                "SELECT source FROM cost_basis WHERE isin = ?", (isin,)
            ).fetchone()

            if existing and existing["source"] == "manual":
                continue

            upsert_cost_basis(
                isin=isin,
                name=data["name"],
                avg_price=data["avg_price"],
                total_qty=data["total_qty"],
                total_cost=data["total_cost"],
                source="auto",
            )

    return len(calculated)
