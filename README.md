# claude-archiver

Утилиты для обработки экспортов из claude.ai. Берут сырой JSON-экспорт (диалоги,
проекты, память) и превращают его в очищенные данные и читаемые Markdown-архивы,
которые удобно хранить локально как бэкап.

**Зачем:** держать все переписки и проекты в человекочитаемом виде, без риска
что-то потерять, и без чувствительных данных в файлах.

## Как это работает

Два шага:

1. **Редакция** (`redact`) — приводит экспорт в безопасный вид: все UUID
   заменяются на стабильные `uuid_1`, `uuid_2`, … (один и тот же UUID всегда
   получает один плейсхолдер), а поля `email_address` и `verified_phone_number`
   удаляются полностью. ФИО не трогаются.
2. **Архивация** (`dialogue` / `project` / `memories`) — превращает очищенный
   JSON в аккуратный Markdown: метаданные, обзор, переписку с разбивкой по датам,
   thinking-блоки и вложения.

Оба шага для целого бэкапа можно сделать одной командой `auto` — это
рекомендуемый путь, ручные `redact` + `dialogue`/`project`/`memories` нужны
только для тонкого контроля.

## Установка

Зависимостей нет, нужен Python 3.9+. Запускать можно прямо из папки:

```bash
python -m claude_archiver --help
```

Либо поставить как пакет (появится команда `claude-archiver`):

```bash
pip install -e .
```

## Использование

### Быстрый путь: `auto`

Обрабатывает целую папку бэкапа (с `conversations.json`, `projects/`,
`memories.json`) за один проход: редактирует диалоги, проекты и память
и сразу собирает Markdown. UUID согласованы между всеми типами (общая карта).

```bash
# всё сразу
python -m claude_archiver auto path/to/backup -o out

# только нужный тип
python -m claude_archiver auto path/to/backup -o out --only conversations
python -m claude_archiver auto path/to/backup -o out --only projects memories
```

На выходе:

```
out/
  dialogs/        # один .md на каждый чат (название из темы)
  projects/<имя>/ # описание + инструкции + файлы-знания
  memories.md     # память пользователя
  cleaned/        # очищенные исходные JSON
  uuid_map.json   # карта UUID (секрет)
```

Флаги: `--only conversations|projects|memories|users`, `--mapping`,
`--human-name`, `--tz`.

### 1. Редакция (вручную)

```bash
# диалоги: + разбить по отдельным файлам + сохранить карту UUID
python -m claude_archiver redact path/to/backup/conversations.json \
    -o out/conversations_cleaned.json \
    --split-dir out/dialogs \
    --mapping out/uuid_map.json

# проекты (папка с *.json)
python -m claude_archiver redact path/to/backup/projects -o out/projects_cleaned.json

# память пользователя
python -m claude_archiver redact path/to/backup/memories.json -o out/memories_cleaned.json
```

Вход — файл, папка (берутся все `*.json`) или glob-шаблон.

| Флаг | Назначение |
|------|------------|
| `-o, --output` | путь выходного JSON (по умолчанию `cleaned.json`) |
| `--split-dir` | разбить результат на отдельные файлы (по `uuid` объекта) |
| `--mapping` | сохранить карту `UUID → плейсхолдер` в JSON |
| `--drop-keys` | переопределить список удаляемых полей |

> **Карта UUID (`uuid_map.json`) — секретная.** Она содержит исходные UUID,
> храните её отдельно и не коммитьте (уже в `.gitignore`).

### 2. Архивация в Markdown

```bash
# один диалог
python -m claude_archiver dialogue out/dialog.md out/dialogs/uuid_1.json --title "Тема"

# несколько диалогов в один файл (сессиями) + бриф в приложения
python -m claude_archiver dialogue out/dialog.md out/dialogs/a.json out/dialogs/b.json \
    --title "Тема" --brief brief.md

# распаковать проект: описание + инструкции + файлы-знания
python -m claude_archiver project out/projects_cleaned.json out/project_dir

# память пользователя -> читаемый .md
python -m claude_archiver memories out/memories_cleaned.json -o out/memories.md
```

Параметры `dialogue`: `--title` (обязателен), `--subtitle`, `--brief`,
`--human-name` (подпись реплик пользователя, по умолчанию «Александр»),
`--tz` (смещение от UTC для дат, по умолчанию 7).

## Структура

```
claude_archiver/
  redact.py     # замена UUID + удаление чувствительных полей
  archive.py    # сборка Markdown из диалогов, проектов и памяти
  cli.py        # единый CLI (auto / redact / dialogue / project / memories)
```
