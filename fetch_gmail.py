#!/usr/bin/env python3
"""
Автоматическое получение отчётов брокера из Gmail (IMAP).

Настройка:
1. В mail.ru создай правило пересылки на Gmail
2. В Gmail включи IMAP: Настройки → Пересылка и POP/IMAP → Включить IMAP
3. Создай пароль приложения: https://myaccount.google.com/apppasswords
4. Заполни .env файл (см. .env.example)

Запуск:
    python fetch_gmail.py              # Проверить новые отчёты
    python fetch_gmail.py --days 30    # За последние 30 дней

Автоматизация (crontab):
    # Каждый будний день в 10:00
    0 10 * * 1-5 cd /path/to/broker-dashboard && python fetch_gmail.py && python import_report.py reports/
"""

import os
import sys
import imaplib
import email
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from email.header import decode_header

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv опционален


REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

GMAIL_HOST = "imap.gmail.com"
GMAIL_USER = os.getenv("GMAIL_USER", "")
GMAIL_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")

# Критерии поиска писем от брокера
BROKER_SUBJECTS = ["Отчет брокера", "Брокерский отчет", "Отчёт брокера"]
BROKER_SENDERS = ["sberbank", "broker"]  # Частичное совпадение


def connect_gmail():
    """Подключение к Gmail IMAP."""
    if not GMAIL_USER or not GMAIL_PASSWORD:
        print("❌ Не заданы GMAIL_USER / GMAIL_APP_PASSWORD")
        print("   Создай .env файл по образцу .env.example")
        sys.exit(1)

    try:
        mail = imaplib.IMAP4_SSL(GMAIL_HOST)
        mail.login(GMAIL_USER, GMAIL_PASSWORD)
        print(f"✅ Подключено к {GMAIL_USER}")
        return mail
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        sys.exit(1)


def decode_subject(msg) -> str:
    """Декодирование темы письма."""
    subject = msg.get("Subject", "")
    decoded = decode_header(subject)
    parts = []
    for part, enc in decoded:
        if isinstance(part, bytes):
            parts.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            parts.append(part)
    return " ".join(parts)


def fetch_broker_reports(days: int = 7):
    """Получить HTML-вложения отчётов брокера за последние N дней."""
    mail = connect_gmail()
    mail.select("INBOX")

    since_date = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")

    # Поиск по дате
    _, message_ids = mail.search(None, f'(SINCE "{since_date}")')
    ids = message_ids[0].split()

    if not ids:
        print(f"📭 Писем за последние {days} дн. не найдено")
        mail.logout()
        return []

    print(f"📬 Найдено {len(ids)} писем, ищу отчёты брокера...")

    saved_files = []

    for mid in ids:
        _, msg_data = mail.fetch(mid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        subject = decode_subject(msg)
        sender = msg.get("From", "").lower()
        msg_date = msg.get("Date", "")

        # Проверяем — похоже ли на отчёт брокера
        is_broker = any(s.lower() in subject.lower() for s in BROKER_SUBJECTS)
        is_from_broker = any(s in sender for s in BROKER_SENDERS)

        if not (is_broker or is_from_broker):
            continue

        print(f"  📧 {subject} ({msg_date})")

        # Ищем HTML-вложения
        for part in msg.walk():
            content_disposition = part.get("Content-Disposition", "")
            if "attachment" not in content_disposition:
                continue

            filename = part.get_filename()
            if filename:
                # Декодируем имя файла
                decoded_fn = decode_header(filename)
                fn_parts = []
                for fp, enc in decoded_fn:
                    if isinstance(fp, bytes):
                        fn_parts.append(fp.decode(enc or "utf-8", errors="replace"))
                    else:
                        fn_parts.append(fp)
                filename = "".join(fn_parts)

            if not filename:
                filename = f"report_{mid.decode()}.html"

            # Проверяем расширение
            if not filename.lower().endswith((".html", ".htm")):
                continue

            filepath = REPORTS_DIR / filename

            if filepath.exists():
                print(f"    ⏭  {filename} — уже скачан")
                continue

            payload = part.get_payload(decode=True)
            if payload:
                filepath.write_bytes(payload)
                print(f"    💾 {filename} — сохранён ({len(payload)} байт)")
                saved_files.append(filepath)

    mail.logout()

    if saved_files:
        print(f"\n✅ Скачано {len(saved_files)} новых отчётов")
    else:
        print("\n📭 Новых отчётов не найдено")

    return saved_files


def main():
    parser = argparse.ArgumentParser(description="Получение отчётов брокера из Gmail")
    parser.add_argument("--days", type=int, default=7, help="За сколько дней искать (по умолчанию 7)")
    args = parser.parse_args()

    saved = fetch_broker_reports(args.days)

    # Автоматически импортируем скачанные отчёты
    if saved:
        print("\n📥 Импорт в базу данных...")
        import db
        import parser as bp

        db.init_db()
        for f in saved:
            try:
                report = bp.parse_report(f)
                report_id = db.import_report(report)
                if report_id > 0:
                    print(f"  ✅ {report.period_end} → импортирован")
                else:
                    print(f"  ⏭  {report.period_end} → уже в базе")
            except Exception as e:
                print(f"  ❌ {f.name} → {e}")


if __name__ == "__main__":
    main()
