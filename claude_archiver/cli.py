#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Единый CLI для обработки экспортов claude.ai.

Подкоманды:
  auto      — всё сразу: редакция + архивация целого бэкапа (или одного типа);
  redact    — очистить UUID и удалить чувствительные поля из любого экспорта;
  dialogue  — собрать читаемый .md-архив из одного или нескольких чатов;
  project   — распаковать экспорт проекта в головной промпт + файлы-знания;
  memories  — оформить память пользователя в читаемый .md.

Примеры:
  python -m claude_archiver auto example_backup -o out
  python -m claude_archiver auto example_backup -o out --only conversations
  python -m claude_archiver redact conversations.json -o cleaned.json --split-dir dialogs
  python -m claude_archiver dialogue out.md a.json b.json --title "Тема" --brief brief.md
  python -m claude_archiver project project.json ./out_dir/
"""
import argparse
import glob
import json
import sys
from datetime import timezone, timedelta
from pathlib import Path

from .archive import (build_dialogue, extract_project, build_memories,
                      DEFAULT_HUMAN_NAME)
from .redact import Redactor, safe_filename, DEFAULT_DROP_KEYS


def load_json_inputs(pattern: str):
    """Принимает путь к файлу, директории (*.json внутри) или glob-шаблон.
    Возвращает список (Path, data)."""
    path = Path(pattern)
    if path.is_dir():
        files = sorted(path.glob("*.json"))
    elif path.exists():
        files = [path]
    else:
        files = [Path(p) for p in sorted(glob.glob(pattern))]

    if not files:
        raise FileNotFoundError(f"JSON-файлы не найдены: {pattern}")

    return [(f, json.loads(f.read_text(encoding="utf-8"))) for f in files]


def cmd_redact(args):
    redactor = Redactor(drop_keys=set(args.drop_keys) if args.drop_keys else DEFAULT_DROP_KEYS)
    inputs = load_json_inputs(args.input)

    # Несколько входных файлов сворачиваем в один список объектов.
    if len(inputs) == 1:
        cleaned = redactor.redact(inputs[0][1])
    else:
        cleaned = [redactor.redact(data) for _, data in inputs]

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ {out_path}  (UUID заменено: {len(redactor.mapping)}, "
          f"удаляемых ключей: {len(redactor.drop_keys)})")

    if args.mapping:
        Path(args.mapping).write_text(
            json.dumps(redactor.mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ карта UUID: {args.mapping}")

    if args.split_dir:
        split_dir = Path(args.split_dir)
        split_dir.mkdir(parents=True, exist_ok=True)
        items = cleaned if isinstance(cleaned, list) else [cleaned]
        for i, item in enumerate(items, start=1):
            item_id = item.get("uuid") if isinstance(item, dict) else None
            filename = safe_filename(str(item_id or f"item_{i}")) + ".json"
            (split_dir / filename).write_text(
                json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✓ разбито на {len(items)} файл(ов) в {split_dir}")


def load_one(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def cmd_dialogue(args):
    tz = timezone(timedelta(hours=args.tz))
    datas = [load_one(s) for s in args.sources]
    build_dialogue(datas, args.out, args.title, args.subtitle,
                   args.brief, tz=tz, human_name=args.human_name)


def cmd_project(args):
    extract_project(load_one(args.project), args.out_dir)


def cmd_memories(args):
    build_memories(load_one(args.memories), args.out)


def cmd_auto(args):
    """Полный конвейер по целому бэкапу: редактируем и сразу архивируем.
    Один Redactor на всё — UUID согласованы между диалогами/проектами/памятью."""
    src = Path(args.input)
    if not src.is_dir():
        raise NotADirectoryError(f"auto ожидает папку бэкапа, а не файл: {src}")

    out = Path(args.output)
    tz = timezone(timedelta(hours=args.tz))
    only = set(args.only) if args.only else None
    redactor = Redactor()

    def want(kind):
        return only is None or kind in only

    cleaned_dir = out / "cleaned"
    cleaned_dir.mkdir(parents=True, exist_ok=True)

    def save_cleaned(name, data):
        (cleaned_dir / name).write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    # — диалоги —
    conv_file = src / "conversations.json"
    if want("conversations") and conv_file.exists():
        dialogs = redactor.redact(load_one(conv_file))
        save_cleaned("conversations.json", dialogs)
        md_dir = out / "dialogs"
        md_dir.mkdir(parents=True, exist_ok=True)
        print(f"Диалоги: {len(dialogs)}")
        for i, d in enumerate(dialogs, 1):
            title = d.get("name") or f"Диалог {i}"
            fname = safe_filename(f"{i:03d}_{title}")[:80] + ".md"
            build_dialogue([d], str(md_dir / fname), title, tz=tz,
                           human_name=args.human_name)

    # — проекты —
    proj_dir_src = src / "projects"
    proj_files = []
    if proj_dir_src.is_dir():
        proj_files = sorted(proj_dir_src.glob("*.json"))
    elif (src / "projects.json").exists():
        proj_files = [src / "projects.json"]
    if want("projects") and proj_files:
        print(f"Проекты: {len(proj_files)} файл(ов)")
        for pf in proj_files:
            proj = redactor.redact(load_one(pf))
            save_cleaned(f"project_{pf.stem}.json", proj)
            p = proj[0] if isinstance(proj, list) else proj
            name = safe_filename(p.get("name") or pf.stem)[:80]
            extract_project(proj, str(out / "projects" / name))

    # — память —
    mem_file = src / "memories.json"
    if want("memories") and mem_file.exists():
        mem = redactor.redact(load_one(mem_file))
        save_cleaned("memories.json", mem)
        build_memories(mem, str(out / "memories.md"))

    # — пользователи (только редакция, архивировать нечего) —
    users_file = src / "users.json"
    if want("users") and users_file.exists():
        save_cleaned("users.json", redactor.redact(load_one(users_file)))

    if args.mapping:
        Path(args.mapping).write_text(
            json.dumps(redactor.mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        (out / "uuid_map.json").write_text(
            json.dumps(redactor.mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ готово: {out}  (всего заменено UUID: {len(redactor.mapping)})")


def build_parser():
    ap = argparse.ArgumentParser(
        prog="claude_archiver",
        description="Редакция и архивация экспортов claude.ai")
    sub = ap.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("auto", help="редакция + архивация целого бэкапа за один раз")
    a.add_argument("input", help="папка бэкапа (conversations.json, projects/, memories.json, ...)")
    a.add_argument("-o", "--output", default="out", help="папка вывода (по умолчанию out)")
    a.add_argument("--only", nargs="*", default=None,
                   choices=["conversations", "projects", "memories", "users"],
                   help="обработать только указанные типы (по умолчанию — все)")
    a.add_argument("--mapping", default=None,
                   help="путь карты UUID (по умолчанию <output>/uuid_map.json)")
    a.add_argument("--human-name", default=DEFAULT_HUMAN_NAME, help="подпись реплик пользователя")
    a.add_argument("--tz", type=int, default=7, help="часовой пояс вывода, смещение от UTC")
    a.set_defaults(func=cmd_auto)

    r = sub.add_parser("redact", help="очистить UUID и удалить чувствительные поля")
    r.add_argument("input", help="файл / папка / glob с JSON")
    r.add_argument("-o", "--output", default="cleaned.json", help="путь выходного JSON")
    r.add_argument("--split-dir", default=None, help="разбить результат по отдельным файлам")
    r.add_argument("--mapping", default=None, help="сохранить карту UUID->плейсхолдер в JSON")
    r.add_argument("--drop-keys", nargs="*", default=None,
                   help=f"ключи для полного удаления (по умолчанию: {', '.join(sorted(DEFAULT_DROP_KEYS))})")
    r.set_defaults(func=cmd_redact)

    d = sub.add_parser("dialogue", help="собрать .md-архив из одного или нескольких чатов")
    d.add_argument("out", help="путь выходного .md")
    d.add_argument("sources", nargs="+", help="один .json = плоский; несколько = сессиями")
    d.add_argument("--title", required=True)
    d.add_argument("--subtitle", default=None)
    d.add_argument("--brief", default=None, help="опциональный .md-бриф в приложения")
    d.add_argument("--human-name", default=DEFAULT_HUMAN_NAME, help="подпись реплик пользователя")
    d.add_argument("--tz", type=int, default=7, help="часовой пояс вывода, смещение от UTC (по умолчанию 7)")
    d.set_defaults(func=cmd_dialogue)

    p = sub.add_parser("project", help="распаковать экспорт проекта")
    p.add_argument("project", help="project.json")
    p.add_argument("out_dir", help="папка для описания, инструкций и файлов-знаний")
    p.set_defaults(func=cmd_project)

    m = sub.add_parser("memories", help="оформить память пользователя в .md")
    m.add_argument("memories", help="memories.json (очищенный)")
    m.add_argument("-o", "--out", default="memories.md", help="путь выходного .md")
    m.set_defaults(func=cmd_memories)

    return ap


def main(argv=None):
    # На Windows консоль часто в cp1251 — наш вывод (✓, кириллица) её ломает.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
