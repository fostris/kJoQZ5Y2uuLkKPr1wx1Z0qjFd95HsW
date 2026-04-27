#!/usr/bin/env python3
"""
Импорт HTML-отчётов брокера в SQLite.

Использование:
    # Один файл
    python import_report.py report.html

    # Все файлы из папки
    python import_report.py reports/

    # Автоимпорт новых (для cron)
    python import_report.py --watch ~/Mail/broker-reports/
"""

import sys
import argparse
from pathlib import Path

import db
import parser as bp


def import_file(path: Path) -> bool:
    """Импортировать один HTML-отчёт. Возвращает True если успешно."""
    try:
        report = bp.parse_report(path)
        report_id = db.import_report(report)
        if report_id > 0:
            print(f"  ✅ {path.name} → {report.period_end} "
                  f"({report.total_end:,.2f} ₽, {len(report.positions)} поз.)")
            return True
        elif report_id == -1:
            print(f"  ⏭  {path.name} → уже загружен ({report.period_end})")
            return False
    except Exception as e:
        print(f"  ❌ {path.name} → ошибка: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Импорт HTML-отчётов брокера Сбербанк в базу данных"
    )
    parser.add_argument(
        "path",
        type=str,
        help="Путь к HTML-файлу или папке с отчётами",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Режим наблюдения: импортировать только новые файлы",
    )

    args = parser.parse_args()
    target = Path(args.path)

    # Инициализация БД
    db.init_db()

    if target.is_file():
        print(f"📄 Импорт файла: {target}")
        import_file(target)

    elif target.is_dir():
        html_files = sorted(target.glob("*.HTML")) + sorted(target.glob("*.html")) + sorted(target.glob("*.htm"))

        if not html_files:
            print(f"⚠️  HTML-файлы не найдены в {target}")
            sys.exit(1)

        print(f"📂 Найдено {len(html_files)} файл(ов) в {target}")
        imported = 0
        skipped = 0

        for f in html_files:
            result = import_file(f)
            if result:
                imported += 1
            else:
                skipped += 1

        print(f"\n📊 Итого: импортировано {imported}, пропущено {skipped}")

    else:
        print(f"❌ Путь не найден: {target}")
        sys.exit(1)


if __name__ == "__main__":
    main()
