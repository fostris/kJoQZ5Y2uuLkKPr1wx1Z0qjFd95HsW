# Project Documentation

## 7.3 Схема БД (SQLite)

### Новая таблица `instrument_fx`

```sql
CREATE TABLE IF NOT EXISTS instrument_fx (
    isin TEXT PRIMARY KEY,
    currency TEXT NOT NULL DEFAULT 'RUB',
    exposure_type TEXT NOT NULL DEFAULT 'rub',
    note TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

- Назначение: ручная разметка валютной экспозиции по ISIN.
- Если запись отсутствует: используется безопасный дефолт `currency='RUB'`, `exposure_type='rub'`.
- Типы:
  - `currency`: `RUB | USD | CNY | EUR | GOLD`
  - `exposure_type`: `rub | fx_substitute | fx_direct | gold | commodity_proxy`
- Миграция: `SCHEMA_MIGRATIONS` версия `5` (`add_instrument_fx`).
- API-слой `db.py`:
  - `get_instrument_fx(isin)`
  - `set_instrument_fx(isin, currency, exposure_type, note)`
  - `list_instrument_fx()`

## 9 FIRE-модель

### Обновлённый расчёт

- FIRE-модель вынесена в чистые функции:
  - `build_fire_projection(...)`
  - `build_fire_scenarios(...)`
- Добавлены пресеты сценариев:
  - `base`
  - `stagflation`
  - `optimistic`
- Расчёт ведётся в реальных рублях.
- Одновременно считаются две цели:
  - `SWR target` (целевой капитал)
  - `SWR withdrawal` (оперативное изъятие)

### UI FIRE

- Параметры пользователя:
  - текущий капитал,
  - ежемесячное пополнение,
  - целевые траты,
  - горизонт,
  - SWR target / SWR withdrawal.
- Разделена инфляция:
  - официальная (информационная),
  - личная (используется в расчёте; для сценариев как `inflation_rate`).
- Для каждого сценария отображаются:
  - целевой капитал по двум SWR,
  - годы до FIRE по двум SWR,
  - реальная доходность.
- График: три траектории капитала (реальные рубли).
- Добавлена явная подпись:
  - «Все суммы — в реальных рублях (с поправкой на инфляцию). Целевой капитал считается по SWR target; оперативное изъятие — по SWR withdrawal.»

## 12 Тестирование

### Запуск

```bash
python -m unittest discover -s tests
```

### Новые/обновлённые тесты

- `tests/test_fire_metrics.py`
  - целевой капитал по двум SWR;
  - отрицательная реальная доходность;
  - достижимость/недостижимость цели в горизонте;
  - набор сценариев (`base`, `stagflation`, `optimistic`).
- `tests/test_fx_exposure.py`
  - дефолт `RUB/rub` без overrides;
  - `fx_substitute` 20% портфеля;
  - `commodity_proxy` не входит в `fx_share`;
  - сумма `by_currency == total_value`.
- `tests/test_concentration.py`
  - раздельный учёт `bond_ofz_pd` и `bond_ofz_in` в `asset_type`-распределении;
  - агрегация ОФЗ-ПД и ОФЗ-ИН в эмитента «Минфин РФ».
- `tests/test_decision_scenarios.py`
  - лимит эмитента для ОФЗ-ПД/ОФЗ-ИН учитывается совместно через «Минфин РФ».
- `tests/test_db_migrations.py` и `tests/test_db_integration.py`
  - наличие таблицы `instrument_fx`;
  - CRUD для `instrument_fx`.
