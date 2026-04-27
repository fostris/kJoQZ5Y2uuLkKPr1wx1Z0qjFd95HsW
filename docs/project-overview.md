# Техническая документация проекта broker-dashboard

## Назначение проекта
Проект — это локальный аналитический дашборд на Streamlit для разбора брокерских HTML-отчётов Сбербанка, хранения исторических данных в SQLite и визуализации состояния портфеля.

Основные пользовательские сценарии:
- импорт нового отчёта через UI ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:103)) или CLI ([import_report.py](/Users/nikita/Desktop/projects/broker-dashboard/import_report.py:41));
- просмотр портфеля и аналитики по вкладкам в дашборде ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:219));
- загрузка купонов, дивидендов, погашений и YTM с MOEX ISS API ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:196), [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:442), [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:301), [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:148));
- управление целями ребалансировки и FIRE-параметрами внутри UI ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1384), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1628));
- автоматический прием отчётов из Gmail по IMAP и автоимпорт ([fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:78)).

С какими данными работает приложение:
- позиции портфеля (цена, стоимость, НКД, тип актива);
- сделки, движения денежных средств, пополнения ИИС;
- календарь купонов/дивидендов;
- погашения и амортизации облигаций;
- внешние активы для FIRE;
- аналитические метрики (YTM, P&L, концентрация рисков, HHI);
- статусы свежести синхронизации MOEX (YTM, эмитенты, купоны, погашения).

## Технологический стек
Подтверждено файлами проекта:
- Язык: Python 3 (кодовая база `.py`).
- UI framework: Streamlit ([requirements.txt](/Users/nikita/Desktop/projects/broker-dashboard/requirements.txt:1), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:6)).
- Табличная обработка: pandas ([requirements.txt](/Users/nikita/Desktop/projects/broker-dashboard/requirements.txt:2), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:7)).
- Графики: plotly (express + graph_objects) ([requirements.txt](/Users/nikita/Desktop/projects/broker-dashboard/requirements.txt:3), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:8)).
- Парсинг HTML: BeautifulSoup4 ([requirements.txt](/Users/nikita/Desktop/projects/broker-dashboard/requirements.txt:4), [parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:10)).
- Хранилище: SQLite (стандартная библиотека `sqlite3`) ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:6)).
- HTTP к внешнему API: `urllib.request` (стандартная библиотека) ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:18)).
- Тестирование: `unittest` (стандартная библиотека) ([tests/test_concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_concentration.py:1), [tests/test_moex_api_ytm.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_moex_api_ytm.py:2)).
- Почта (автоматизация): `imaplib`, `email` (стандартная библиотека), опционально `python-dotenv` ([fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:29)).

Что не найдено в проекте:
- `package.json`, фронтенд-сборщик, TypeScript, React, npm/yarn/pnpm;
- отдельные конфиги lint/typecheck (`ruff`, `flake8`, `mypy`, `pyright`, `pyproject.toml`).

## Структура проекта
Ключевые файлы и каталоги:

| Путь | Назначение |
|---|---|
| [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1) | Основной entry point Streamlit UI и вся визуализация/интерактив. |
| [parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:1) | Парсинг HTML-отчёта брокера в dataclass-модель `BrokerReport`. |
| [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:1) | Схема SQLite, CRUD и upsert-операции для всех сущностей. |
| [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:1) | Клиент MOEX ISS API, синхронизация календарей и рыночных метрик. |
| [concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:1) | Чистые функции анализа концентрации рисков (доли, HHI, предупреждения). |
| [portfolio_metrics.py](/Users/nikita/Desktop/projects/broker-dashboard/portfolio_metrics.py:1) | Чистые расчёты портфельных метрик: стоимость позиции/портфеля, доходность, P&L, агрегаты по типам активов. |
| [portfolio_tables.py](/Users/nikita/Desktop/projects/broker-dashboard/portfolio_tables.py:1) | Подготовка DataFrame для таблицы позиций (обогащение, сортировка, колонки отображения). |
| [ui/charts.py](/Users/nikita/Desktop/projects/broker-dashboard/ui/charts.py:1) | Чистые helpers для графиков Plotly (например, scatter YTM vs срок до погашения). |
| [report_export.py](/Users/nikita/Desktop/projects/broker-dashboard/report_export.py:1) | Генерация краткого HTML-отчёта портфеля с явными пометками отсутствующих данных. |
| [rebalancing.py](/Users/nikita/Desktop/projects/broker-dashboard/rebalancing.py:1) | Чистые расчёты ребалансировки: текущее распределение, отклонения, перевес/недовес. |
| [fire_metrics.py](/Users/nikita/Desktop/projects/broker-dashboard/fire_metrics.py:1) | Чистые FIRE-расчёты: базовые метрики, прогноз, glide path, Monte Carlo-перцентили и окна. |
| [formatters.py](/Users/nikita/Desktop/projects/broker-dashboard/formatters.py:1) | Форматирование рублей/процентов/null-значений для UI. |
| [import_report.py](/Users/nikita/Desktop/projects/broker-dashboard/import_report.py:1) | CLI-импорт одного файла или директории отчётов. |
| [fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:1) | IMAP-загрузка отчётов из Gmail и автоимпорт в БД. |
| [tests/](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_concentration.py:1) | Unit-тесты расчётных модулей (`concentration`, `portfolio_metrics`, `portfolio_tables`, `formatters`), parser-логики, MOEX-логики и SQL-обвязки свежести данных. |
| [tests/fixtures/parser/](/Users/nikita/Desktop/projects/broker-dashboard/tests/fixtures/parser/minimal_report.html) | Синтетические HTML fixtures для тестов парсера без персональных данных. |
| [reports/](/Users/nikita/Desktop/projects/broker-dashboard/reports) | Исходные HTML-отчёты брокера. |
| [portfolio.db](/Users/nikita/Desktop/projects/broker-dashboard/portfolio.db) | SQLite база данных (создается/обновляется кодом). |
| [start_streamlit.sh](/Users/nikita/Desktop/projects/broker-dashboard/start_streamlit.sh:1) | Скрипт запуска Streamlit с параметрами сервера. |
| [restart.sh](/Users/nikita/Desktop/projects/broker-dashboard/restart.sh:1) | Скрипт перезапуска Streamlit-процесса. |

## Архитектура
Точка входа UI:
- [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1).

Поток данных (основной сценарий):
1. Пользователь загружает HTML-отчёт в sidebar ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:103)).
2. Отчёт парсится функцией `parse_report` ([parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:147)).
3. Распарсенная модель сохраняется в SQLite через `db.import_report` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:201)).
4. При каждом рендере выбранного отчёта `app.py` читает данные через `db.get_*` функции ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:164)).
5. Дополнительные данные (MOEX) подгружаются по кнопкам синхронизации и через кешируемые загрузчики (`load_bond_ytm_map`, `load_bond_issuer_map`) ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:74), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:85)).
6. Основные расчёты/подготовка визуализаций выполняются в чистых модулях (`concentration.py`, `portfolio_metrics.py`, `portfolio_tables.py`, `ui/charts.py`, `report_export.py`, `rebalancing.py`, `fire_metrics.py`, `formatters.py`), а `app.py` выступает оркестратором данных и UI-слоем.
7. Результаты отображаются в табах Streamlit (`Обзор`, `Позиции`, `Календарь`, `Ребалансировка`, `FIRE` и т.д.) ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:219)).

Связи модулей:
- `app.py` зависит от `db`, `parser`, `moex_api` и чистых расчётных модулей (`concentration`, `portfolio_metrics`, `portfolio_tables`, `ui.charts`, `report_export`, `rebalancing`, `fire_metrics`, `formatters`).
- `moex_api.py` зависит от `db.py` для сохранения синхронизированных данных.
- `import_report.py` и `fetch_gmail.py` используют `parser.py` + `db.py`.

## Основные модели данных
### 1) Отчёт портфеля
- Где определено: dataclass `BrokerReport` ([parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:81)); таблица `reports` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:34)).
- Основные поля: `period_start`, `period_end`, `report_date`, `total_end`, `total_change`, `investor`, `contract`.
- Обязательность: в SQLite `report_date`, `period_start`, `period_end` — `NOT NULL`; `period_end` уникален.
- Где используется: выбор отчёта в sidebar и заголовок/обзор в UI ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:133), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:206)).

### 2) Позиция
- Где определено: dataclass `Position` ([parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:14)); таблица `positions` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:52)).
- Поля: `name`, `isin`, `qty`, `nominal`, `price_end`, `value_end`, `nkd_end`, `change_value`, `asset_type`.
- Nullable/обязательность: `name` и `report_id` обязательны в БД; большинство числовых полей допускают `NULL`/default.
- Где используется: вкладки `Обзор`, `Позиции`, `Ребалансировка`, `FIRE`, `Календарь` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:590), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1384), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1785)).

### 3) Сделка
- Где определено: dataclass `Trade` ([parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:42)); таблица `trades` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:80)).
- Поля: `trade_date`, `ticker`, `side`, `qty`, `price`, `amount`, комиссии.
- Где используется: вкладка `Сделки` и расчёт средней цены покупки (`cost_basis`) ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1571), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:597)).

### 4) Денежный поток и пополнения
- Где определено: `CashFlow`, `Deposit` ([parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:32), [parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:62)); таблицы `cash_flows`, `deposits` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:70), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:100)).
- Где используется: вкладка `Пополнения и вычет` и разделы обзора ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:822), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:332)).

### 5) Календари выплат
- Купоны: `coupon_calendar` + `upsert_coupon` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:109), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:384)).
- Дивиденды: `dividend_calendar` + `upsert_dividend` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:122), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:449)).
- Где используется: вкладка `Календарь` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:908)).

### 6) Погашения/амортизации облигаций
- Таблицы: `bond_maturities`, `bond_amortizations` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:152), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:165)).
- Где используется: лестница погашений в `Календаре` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1175)).

### 7) Средняя цена покупки (cost basis)
- Таблица: `cost_basis` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:141)).
- Функции: `get_cost_basis_map`, `sync_cost_basis_from_trades` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:570), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:648)).
- Где используется: P&L на вкладке `Позиции` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:596)).

### 8) Метрики концентрации
- Где определено: return-структура `calculate_concentration_metrics` ([concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:171)).
- Ключи: `positions`, `issuers`, `sectors`, `issuer_groups`, `largest_*_share`, `corporate_bonds_share`, `position_hhi`, `issuer_hhi`, `warnings`.
- Nullable: почти все агрегаты могут быть `None` на пустом портфеле.
- Где используется: блок «Концентрация рисков» и колонки в таблице позиций ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:244), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:621)).

### 9) Свежесть синхронизации MOEX
- Таблица: `data_sync_status` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:136)).
- Поля: `data_source`, `entity`, `isin`, `fetched_at`, `status`, `error_message`.
- Функции: `upsert_data_sync_status`, `get_data_sync_freshness` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:491), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:508)).
- Где используется: подписи свежести данных в UI и фиксация статусов синхронизации из `moex_api.py` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:125), [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:115)).

### 10) Версионирование схемы БД
- Таблица: `schema_migrations` (создаётся в `db.py`).
- Функции: `get_schema_version()`, `apply_migrations()` и список `SCHEMA_MIGRATIONS` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:14)).
- Назначение: безопасное добавление новых изменений схемы без ручных `ALTER` в проде; повторный запуск миграций идемпотентен.

### 11) Ручной справочник эмитентов
- Таблица: `issuer_reference`.
- Поля: `issuer_name`, `issuer_group`, `sector`, `issuer_type`, `comment`, `updated_at`.
- Функции: `get_issuer_references`, `get_issuer_reference_map`, `upsert_issuer_reference`, `delete_issuer_reference`.
- Где используется: редактирование в UI на вкладке `Обзор` и расчёт концентрации по секторам/группам.

## Интеграции и внешние API
### MOEX ISS API
Клиент: [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:1).

Используемые endpoint-ы:
- `/securities/{ISIN}/bondization.json` — купоны и амортизации ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:202), [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:277)).
- `/securities/{ISIN}.json?iss.only=boards` — поиск SECID по ISIN ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:482)).
- `/securities.json?q={isin}` — fallback-поиск карточки бумаги + эмитента ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:92)).
- `/engines/stock/markets/bonds/securities/{ticker}.json?iss.only=marketdata` — YTM (`YIELD`) ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:161), [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:114)).
- `/securities/{ticker}/dividends.json` — дивиденды ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:448)).
- `/history/engines/stock/markets/index/securities/IMOEX.json` — история индекса IMOEX ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:648)).

Что извлекается:
- купонные даты, ставка/сумма купона;
- дивиденды, даты отсечки;
- дата погашения, амортизации;
- YTM и эмитент для облигаций;
- временной ряд IMOEX.

Обработка ошибок:
- `_fetch_json` ловит `URLError`/`HTTPError`, делает bounded retry/backoff для временных ошибок, логирует финальный сбой и возвращает `{}` или `(payload, status, error)` при `return_status=True` ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:68)).
- при пустых/неполных данных функции возвращают `[]` или `None`.
- статусы синхронизации (`success`/`error`) по `entity` и `isin` сохраняются в `data_sync_status` и доступны в UI как «свежесть данных» ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:115), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:491)).

Кеширование:
- process-local in-memory кеши в `moex_api.py` для YTM и поиска по ISIN ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:30)).
- Streamlit cache для карт YTM/эмитентов в `app.py` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:74), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:85)).

Ограничения интеграции MOEX:
- явный rate-limit только через `REQUEST_DELAY` между синхронизационными запросами ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:26));
- данные эмитента могут отсутствовать, тогда включается fallback по названию выпуска в модуле концентрации ([concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:107)).

### Gmail IMAP
Клиент: [fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:1).
- Подключение к `imap.gmail.com` через `IMAP4_SSL` ([fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:39)).
- Фильтрация писем по теме/отправителю и сохранение HTML-вложений в `reports/`.
- Затем автоимпорт отчётов в БД через `parser` + `db` ([fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:170)).

## Расчёты и бизнес-логика
### Стоимость позиции и портфеля
- Для отображения в UI используется `value_end + nkd_end` (например, «Полная стоимость» в таблице позиций) ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:676)).
- Суммарная стоимость портфеля по выборке: `filtered["value_end"].sum() + filtered["nkd_end"].sum()` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:669)).
- В модуле концентрации используется `calculate_position_market_value` с fallback на `price_end * qty` (для облигаций учитывается `nominal` и цена в процентах) ([concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:28)).

Edge cases:
- `None`/пустые значения цены, количества, стоимости;
- нулевой total портфеля.

### P&L
- Расчёт в `tab_positions`: `current_val - cost_val`, где `current_val = value_end + nkd_end`, `cost_val = avg_price * qty` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:634)).
- `avg_price` берётся из `cost_basis` ([db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:570)).
- Если средней цены нет, P&L остаётся `None`.

### Доли активов
- По типам активов: `groupby(asset_type)` + `(value + nkd)` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:441)).
- По позициям и эмитентам: `concentration.calculate_concentration_metrics` ([concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:171)).

### НКД
- Значения НКД парсятся из отчёта (`nkd_end`, `nkd_start`) ([parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:267)).
- Используются в расчете полной стоимости, P&L, агрегатах по категориям ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:676)).

### Доходность
- Историческая доходность портфеля рассчитывается на основе `reports.total_end` за разные горизонты ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:321)).
- Сравнение с IMOEX через `moex_api.get_imoex_history` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:529)).

### YTM
- Извлечение YTM из блока `marketdata` поля `YIELD` ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:114)).
- Преобразование в UI-формат через `format_ytm` ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:187)).

### Концентрация рисков и HHI
- Расчёты: [concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:171).
- HHI: `sum(share^2)` в диапазоне долей 0..1 ([concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:49)).
- Предупреждения по порогам вынесены в константы ([concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:8)).
- Поддержаны агрегаты концентрации по `sector` и `issuer_group`; при пустом справочнике используется fallback (`sector = "Не указан"`, `issuer_group = issuer`).

### Календари выплат/погашений
- Синхронизация с MOEX и upsert в SQLite:
  - купоны: `sync_coupons_for_portfolio` + `db.upsert_coupon` ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:371), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:384));
  - дивиденды: `sync_dividends_for_portfolio` + `db.upsert_dividend` ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:519), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:449));
  - погашения: `sync_maturity_for_portfolio` + `db.upsert_bond_maturity`/`db.upsert_amortization` ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:301), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:501), [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:533)).

## UI и компоненты
UI реализован в одном файле `app.py` как набор вкладок Streamlit:
- `Обзор` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:224)): KPI, концентрация рисков, структура, динамика, сравнение с IMOEX.
- `Позиции` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:590)): фильтры, scatter-график `YTM vs срок до погашения` с исключениями, таблица позиций, сортировки, YTM/эмитент/доли, P&L, управление средней ценой.
- `Пополнения и вычет` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:822)): контроль лимита вычета ИИС.
- `Календарь` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:908)): купоны, дивиденды, погашения, амортизации.
- `Ребалансировка` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1384)): цели структуры, отклонения, рекомендации.
- `Сделки` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1571)): таблицы сделок и комиссии.
- `FIRE` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1628)): прогноз, внешние активы, глайд-пат, Monte Carlo.

Где добавлять новые блоки дашборда:
- новый KPI/аналитику портфеля — в `tab_overview`;
- новую колонку таблицы — в `tab_positions` в `display_df`;
- новый календарный раздел по выплатам — в `tab_calendar`.

## Состояние и поток данных
Текущий механизм состояния:
- Streamlit script-based state (перезапуск скрипта при взаимодействии);
- кешируемые функции через `@st.cache_data` для API-карт YTM/эмитентов ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:74)).

Где хранится состояние:
- персистентно: SQLite (`portfolio.db`), доступ через `db.py`;
- в рамках рендера: DataFrame/словарные структуры в `app.py`.

Как обновляются данные:
- кнопки синхронизации в `Календаре` вызывают `moex_api.sync_*`, затем `st.rerun()`;
- импорт отчёта пишет в БД и сразу влияет на последующие рендеры.

Состояния UI:
- loading: `st.spinner` на сетевых операциях;
- empty: `st.info("Нет данных...")` в каждой вкладке;
- error: `st.error`/`st.warning` при парсинге и API-проблемах.

## Тестирование
Текущие тесты:
- [tests/test_concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_concentration.py:1): доли, группировка по эмитентам/сектору/группе, HHI, предупреждения, пустой портфель, fallback.
- [tests/test_moex_api_ytm.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_moex_api_ytm.py:1): парсинг/форматирование YTM, retry/backoff и статусы свежести синхронизации.
- [tests/test_portfolio_metrics.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_portfolio_metrics.py:1): стоимость позиции/портфеля, P&L-сценарии, доли портфеля, edge cases `None`/нулевые значения.
- [tests/test_portfolio_tables.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_portfolio_tables.py:1): подготовка таблицы позиций, колонки полной стоимости и P&L, устойчивость к null, неизменность исходного DataFrame.
- [tests/test_formatters.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_formatters.py:1): форматирование рублей/процентов, `None`/`NaN` в `—`, отрицательные значения.
- [tests/test_ui_charts.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_ui_charts.py:1): подготовка scatter `YTM vs срок до погашения`, исключение неполных строк, проверка состава tooltip и edge case без валидных точек.
- [tests/test_report_export.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_report_export.py:1): генерация краткого HTML-отчёта, включая сценарии с полными и неполными данными.
- [tests/test_data_sync_status.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_data_sync_status.py:1): SQL-обвязка `data_sync_status`, агрегация свежести и сохранение истории ошибок.
- [tests/test_db_migrations.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_db_migrations.py:1): применение миграций на новой/старой БД и идемпотентность повторного запуска.
- [tests/test_parser.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_parser.py:1): базовый парсинг HTML-отчёта, включая даты, позиции/НКД, сделки, денежные потоки, пополнения и неполные таблицы.
- [tests/test_db_integration.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_db_integration.py:1): интеграционные проверки `db.py` на временной SQLite БД (схема, импорт отчёта, upsert-операции, чтение позиций и cost basis).

Чем запускать:
- `python -m unittest discover -s tests -v`

Покрыто:
- чистая бизнес-логика концентрации, портфельных метрик, подготовки таблиц и форматирования;
- YTM-парсинг, retry/backoff и статусы свежести синхронизации MOEX;
- SQL-функции свежести `data_sync_status`;
- миграции БД (`schema_migrations`, `apply_migrations`, `get_schema_version`);
- базовые сценарии парсинга `parser.py` на синтетических fixtures;
- базовые интеграционные сценарии `db.py` на временной БД (без изменения `portfolio.db`).

Не покрыто (по текущему коду):
- `app.py` (UI-ветки, визуализация, интеграционные сценарии);
- `parser.py` (расширенные/реальные HTML-краевые случаи и вариативность вёрстки);
- часть `db.py` (не покрыты все CRUD-ветки и сложные сценарии расчёта cost basis из сделок);
- `fetch_gmail.py` и сетевые сценарии MOEX.

Как добавить новый тест:
- создать файл в `tests/` в формате `test_*.py`;
- использовать `unittest.TestCase`;
- запускать всей пачкой через `discover`.

## Команды разработки
Подтвержденные команды в проекте:

| Задача | Команда | Источник |
|---|---|---|
| Установка зависимостей | `pip install -r requirements.txt` | [README.md](/Users/nikita/Desktop/projects/broker-dashboard/README.md:10) |
| Запуск дашборда (dev) | `streamlit run app.py` | [README.md](/Users/nikita/Desktop/projects/broker-dashboard/README.md:16) |
| Импорт одного отчёта | `python import_report.py /path/to/report.html` | [README.md](/Users/nikita/Desktop/projects/broker-dashboard/README.md:13) |
| Импорт папки отчётов | `python import_report.py reports/` | [import_report.py](/Users/nikita/Desktop/projects/broker-dashboard/import_report.py:10) |
| Gmail-выгрузка отчётов | `python fetch_gmail.py --days 30` | [fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:13) |
| Запуск тестов | `python -m unittest discover -s tests -v` | [tests/test_concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_concentration.py:1) |
| Запуск через shell-скрипт | `./start_streamlit.sh` | [start_streamlit.sh](/Users/nikita/Desktop/projects/broker-dashboard/start_streamlit.sh:1) |
| Перезапуск сервиса | `./restart.sh` | [restart.sh](/Users/nikita/Desktop/projects/broker-dashboard/restart.sh:1) |

Что не найдено:
- команды `build`, `preview`, `lint`, `typecheck` в конфигурационных файлах проекта.

## Текущие ограничения и технический долг
Факты по текущему коду:
- `app.py` очень большой и совмещает UI, часть бизнес-логики и оркестрацию сетевых запросов ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1)).
- Слой миграций БД присутствует, но всё ещё остаётся смешанный подход: базовая схема создаётся в `init_db()`, а эволюционные изменения — через `SCHEMA_MIGRATIONS`.
- UI-ветки (`app.py`) остаются без прямых автоматизированных тестов.
- В `README` и `fetch_gmail.py` упоминается `.env.example`, но файла в репозитории нет.
- `fetch_gmail.py` использует `python-dotenv` как опциональную зависимость, но она отсутствует в `requirements.txt`.
- Вызовы внешнего API из UI зависят от сетевой доступности и выполняются синхронно в пользовательском потоке (через кнопки синхронизации в `app.py`).

## Где добавлять будущие улучшения
### YTM и облигационные рыночные метрики
- API-логика и парсинг: [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:114), [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:148).
- UI-колонки/сортировки: [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:615), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:651).
- Тесты: [tests/test_moex_api_ytm.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_moex_api_ytm.py:7).

### Анализ концентрации рисков
- Расчетные функции: [concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:171).
- Блок обзора и таблицы: [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:244), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:671).
- Тесты: [tests/test_concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_concentration.py:6).

### Новые метрики портфеля
- Общие KPI и визуализация: `tab_overview` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:224)).
- Исторические агрегаты: запросы к `reports`/`positions` в [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:333).

### Новые колонки таблиц
- Позиции: `display_df` в `tab_positions` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:671)).
- Календари выплат: таблицы в `tab_calendar` ([app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1019), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1132), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:1278)).

### Новые API-запросы
- Добавлять в `moex_api.py` с использованием `_fetch_json`, `_iss_to_rows`, и при необходимости кешей/`REQUEST_DELAY` ([moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:59)).

### Новые тесты
- Расчетные: в `tests/` по шаблону `unittest`;
- Интеграционные/DB: использовать существующий модуль `tests/test_db_integration.py` как основу и расширять сценарии.

## Карта проекта для быстрого старта
- Добавить новую метрику портфеля -> [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:224), [concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:171)
- Добавить колонку в таблицу позиций -> [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:671)
- Изменить парсинг HTML-отчёта -> [parser.py](/Users/nikita/Desktop/projects/broker-dashboard/parser.py:147)
- Изменить схему/запросы SQLite -> [db.py](/Users/nikita/Desktop/projects/broker-dashboard/db.py:30)
- Изменить запросы к MOEX API -> [moex_api.py](/Users/nikita/Desktop/projects/broker-dashboard/moex_api.py:59)
- Добавить расчет концентрации/HHI -> [concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/concentration.py:49)
- Добавить новый календарный блок -> [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:908)
- Добавить/изменить график Plotly для UI -> [ui/charts.py](/Users/nikita/Desktop/projects/broker-dashboard/ui/charts.py:1), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:875)
- Добавить/изменить краткий HTML-экспорт -> [report_export.py](/Users/nikita/Desktop/projects/broker-dashboard/report_export.py:1), [app.py](/Users/nikita/Desktop/projects/broker-dashboard/app.py:680)
- Добавить логику импорта из CLI -> [import_report.py](/Users/nikita/Desktop/projects/broker-dashboard/import_report.py:41)
- Добавить автоматизацию загрузки почты -> [fetch_gmail.py](/Users/nikita/Desktop/projects/broker-dashboard/fetch_gmail.py:78)
- Добавить тест расчёта -> [tests/test_concentration.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_concentration.py:6)
- Добавить тест парсинга рыночных данных -> [tests/test_moex_api_ytm.py](/Users/nikita/Desktop/projects/broker-dashboard/tests/test_moex_api_ytm.py:7)
