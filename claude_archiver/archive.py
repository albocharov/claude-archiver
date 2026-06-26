# -*- coding: utf-8 -*-
"""Превращает экспорты чатов claude.ai (JSON) в читаемые Markdown-архивы,
а экспорты проектов — в описание + инструкции + файлы-знания.

Возможности:
  - один плоский диалог            -> один .md (метаданные + обзор + переписка)
  - несколько диалогов в один файл -> сессиями (для связанных тем)
  - встраивание брифа (.md) в «Приложения»
  - thinking-блоки -> цитатой с пометкой «Размышления» перед ответом
  - вложения -> в раздел «Приложения»
  - чистка экспортных заглушек инструментов
  - понижение заголовков внутри реплик (чтобы не ломали структуру)
  - распаковка экспорта проекта (head prompt + docs)

Если у чата пустое поле summary — раздел «Обзор» не добавляется и печатается
предупреждение (обзор по такому чату пишется вручную).
"""
import json
import os
import re
from datetime import datetime, timezone, timedelta

# Часовой пояс вывода и подпись пользовательских реплик. Подменяются из CLI.
DEFAULT_TZ = timezone(timedelta(hours=7))   # НСК = UTC+7
DEFAULT_HUMAN_NAME = "Александр"

PLACEHOLDER = "This block is not supported on your current device yet."
MONTHS = {1: "января", 2: "февраля", 3: "марта", 4: "апреля", 5: "мая",
          6: "июня", 7: "июля", 8: "августа", 9: "сентября", 10: "октября",
          11: "ноября", 12: "декабря"}


def dt(s, tz):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(tz)


def rudate(d):
    return f"{d.day} {MONTHS[d.month]} {d.year}"


def process_body(txt):
    """Чистка заглушек + понижение markdown-заголовков (+3, максимум 6),
    не трогая заголовки/комментарии внутри блоков кода ```."""
    txt = re.sub(r"```\s*" + re.escape(PLACEHOLDER) + r"\s*```",
                 "_(вызов инструмента)_", txt)
    txt = txt.replace(PLACEHOLDER, "_(вызов инструмента)_")
    out, fence = [], False
    for ln in txt.split("\n"):
        if ln.lstrip().startswith("```"):
            fence = not fence
            out.append(ln)
            continue
        if not fence:
            m = re.match(r"^(#{1,6}) ", ln)
            if m:
                ln = "#" * min(len(m.group(1)) + 3, 6) + ln[len(m.group(1)):]
        out.append(ln)
    return "\n".join(out)


def blockquote(text):
    return "\n".join((("> " + ln) if ln.strip() else ">") for ln in text.split("\n"))


def demote(md, add=3):
    """Понизить все заголовки markdown-документа (для встраивания брифа)."""
    return re.sub(r"(?m)^(#{1,6}) ",
                  lambda m: "#" * min(len(m.group(1)) + add, 6) + " ", md)


def render_body(msg):
    """Тело сообщения из блоков content: thinking -> цитата, text -> текст,
    служебные tool-блоки пропускаются. Fallback на поле text."""
    parts = []
    for c in msg.get("content", []):
        if not isinstance(c, dict):
            continue
        if c.get("type") == "thinking":
            th = process_body((c.get("thinking") or "").strip())
            if th:
                parts.append("> **Размышления**\n>\n" + blockquote(th))
        elif c.get("type") == "text":
            tx = process_body((c.get("text") or "").strip())
            if tx:
                parts.append(tx)
    if not parts:
        return process_body((msg.get("text") or "").strip())
    return "\n\n".join(parts)


def render_transcript(out, msgs, appendix, tz, human_name):
    """Дописывает переписку (по датам) в out; вложения собирает в appendix."""
    cur = None
    for m in msgs:
        t = dt(m["created_at"], tz)
        if t.date() != cur:
            cur = t.date()
            out.append(f"\n### {rudate(t)}\n")
        who = human_name if m["sender"] == "human" else "Claude"
        out.append(f"**{who}** · {t:%H:%M}")
        body = render_body(m)
        out.append("\n" + (body if body else "_(без текста)_") + "\n")
        for a in m.get("attachments", []):
            c = a.get("extracted_content")
            if c:
                tag = f"A{len(appendix) + 1}"
                name = a.get("file_name") or "без имени"
                kb = round(a.get("file_size", len(c)) / 1024, 1)
                out.append(f"> 📎 **Вложение {tag}** · {name} · {kb} КБ → см. Приложения\n")
                appendix.append((tag, name, kb, c, rudate(t)))


def build_dialogue(datas, out_path, title, subtitle=None, brief_path=None,
                   tz=DEFAULT_TZ, human_name=DEFAULT_HUMAN_NAME):
    """datas — список уже загруженных диалогов (dict). Один = плоский архив,
    несколько = архив сессиями."""
    combined = len(datas) > 1
    out, appendix = [], []

    out.append(f"# Архив диалога «{title}»\n")
    if subtitle:
        out.append(f"_{subtitle}_\n")
    elif not combined:
        out.append(f"_Бэкап переписки с Claude (claude.ai). Тема: {datas[0].get('name', '')}._\n")

    # метаданные
    out.append("## Метаданные\n")
    first = dt(datas[0]["chat_messages"][0]["created_at"], tz)
    last = dt(datas[-1]["chat_messages"][-1]["created_at"], tz)
    total = sum(len(d["chat_messages"]) for d in datas)
    if combined:
        out.append(f"- **Период:** {rudate(first)} — {rudate(last)}")
        out.append(f"- **Всего сообщений:** {total}")
        for i, d in enumerate(datas, 1):
            m = d["chat_messages"]
            a, b = dt(m[0]["created_at"], tz), dt(m[-1]["created_at"], tz)
            h = sum(1 for x in m if x["sender"] == "human")
            out.append(f"- **Сессия {i} — «{d.get('name', '')}»:** {len(m)} сообщ. "
                       f"({a.day} {MONTHS[a.month]} → {b.day} {MONTHS[b.month]}), реплик {human_name} — {h}")
    else:
        m = datas[0]["chat_messages"]
        h = sum(1 for x in m if x["sender"] == "human")
        if first.date() == last.date():
            out.append(f"- **Дата:** {rudate(first)} ({first:%H:%M}–{last:%H:%M})")
        else:
            out.append(f"- **Период:** {rudate(first)} — {rudate(last)}")
        out.append(f"- **Всего сообщений:** {len(m)} (реплик {human_name} — {h})")
    out.append(f"- **Время:** UTC+{int(tz.utcoffset(None).total_seconds() // 3600)} (НСК)\n")

    # обзор (из summary)
    overviews = [(d.get("name", ""), (d.get("summary") or "").strip()) for d in datas]
    if any(s for _, s in overviews):
        out.append("## Обзор\n")
        for i, (name, s) in enumerate(overviews, 1):
            if not s:
                continue
            if combined:
                out.append(f"### Сессия {i} — «{name}»\n")
            out.append(s + "\n")
    for d in datas:
        if not (d.get("summary") or "").strip():
            print(f"  ⚠ ПУСТОЙ summary у «{d.get('name', '')}» — обзор не добавлен, напиши вручную")

    # переписка
    out.append("\n---\n")
    out.append("## Полная переписка\n")
    for i, d in enumerate(datas, 1):
        if combined:
            out.append(f"\n## Сессия {i} — «{d.get('name', '')}»\n")
        render_transcript(out, d["chat_messages"], appendix, tz, human_name)

    # приложения (+ опциональный бриф)
    if appendix or brief_path:
        out.append("\n---\n")
        out.append("## Приложения\n")
        if brief_path:
            out.append("\n_Вложения из переписки и отдельный бриф (без истории сообщений) — для контекста._\n")
        for tag, name, kb, c, date in appendix:
            out.append(f"\n### {tag} · {name} · {kb} КБ · ({date})\n")
            out.append("```text")
            out.append(c.replace("\r\n", "\n").rstrip())
            out.append("```\n")
        if brief_path:
            brief = open(brief_path, encoding="utf-8").read().replace("\r\n", "\n").strip()
            out.append("\n### Бриф (составлен отдельно, без истории сообщений)\n")
            out.append(demote(brief) + "\n")

    md = "\n".join(out)
    open(out_path, "w", encoding="utf-8").write(md)
    print(f"✓ {out_path}  ({total} сообщ., {len(md.encode()) / 1024:.1f} КБ, вложений {len(appendix)})")


def extract_project(proj, out_dir):
    """proj — загруженный экспорт проекта (dict или список из одного dict)."""
    if isinstance(proj, list):
        proj = proj[0]   # бывает обёрнут в список
    os.makedirs(out_dir, exist_ok=True)
    name = proj.get("name", "проект")
    print(f"Проект: «{name}»")

    # description и prompt_template — разные сущности: первое описывает проект,
    # второе задаёт инструкции. Кладём в отдельные файлы.
    description = (proj.get("description") or "").strip()
    if description:
        p = os.path.join(out_dir, f"Проект {name} — описание.md")
        open(p, "w", encoding="utf-8").write(description + "\n")
        print(f"  ✓ описание: {os.path.basename(p)}")

    prompt = (proj.get("prompt_template") or "").strip()
    if prompt:
        p = os.path.join(out_dir, f"Проект {name} — инструкции.md")
        open(p, "w", encoding="utf-8").write(prompt + "\n")
        print(f"  ✓ инструкции: {os.path.basename(p)}")

    for d in proj.get("docs", []):
        fn = d.get("filename") or "doc.md"
        base = os.path.splitext(fn)[0] + ".md"   # извлечённый текст -> .md
        content = (d.get("content") or "").replace("\r\n", "\n").rstrip() + "\n"
        open(os.path.join(out_dir, base), "w", encoding="utf-8").write(content)
        print(f"  ✓ файл-знание: {base} ({len(content)} симв.)")


def build_memories(data, out_path):
    """data — экспорт памяти. Текст памяти уже в Markdown, просто оформляем его в читаемый файл."""
    accounts = data if isinstance(data, list) else [data]
    out = ["# Память Claude\n"]
    written = 0
    multi = sum(1 for a in accounts if (a.get("conversations_memory") or "").strip()) > 1
    for i, acc in enumerate(accounts, 1):
        mem = (acc.get("conversations_memory") or "").strip()
        if not mem:
            continue
        if multi:
            out.append(f"## Аккаунт {i}\n")
        out.append(mem.replace("\r\n", "\n") + "\n")
        written += 1

    if not written:
        print("  ⚠ память пустая — файл не создан")
        return

    md = "\n".join(out)
    open(out_path, "w", encoding="utf-8").write(md)
    print(f"✓ {out_path}  ({len(md.encode()) / 1024:.1f} КБ)")
