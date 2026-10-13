# Catalog to JSON

FastAgent с навыком и инструментами превращает PDF-каталоги в JSON с отдельной проверкой по оригиналу.

- Агент извлекает текст через AnyDoc и таблицы через геометрию PDF, сам открывает страницу и увеличивает сложные участки через Vision.
- JSON сохраняется инструментом с проверкой схемы; ответ агента в чате может быть обычным текстом.
- Проверяющий сначала независимо читает оригинал, затем получает кандидат. Инструмент сопоставляет ячейки и блокирует противоречивый положительный вердикт.
- Замечания возвращаются исполнителю; он сверяется с оригиналом, исправляет JSON и отправляет его на повторную проверку до принятия.
- Сохраняет исходные подписи, пустые поля, чертежи и историю исправлений.
- Excel и читаемый HTML создаются из JSON. Непроверенные результаты не экспортируются по умолчанию.

## Установка

```bash
uv tool install git+https://github.com/megamen32/catalog-to-json
```

## Agent Plugin 1.0

В репозитории находятся `plugin.json`, нативные манифесты Codex/Claude, два навыка и `.mcp.json`. MCP запускается локально через `uvx`; Vision использует вашу настроенную модель. Исходные документы и результаты не входят в плагин. CLI ниже загружает эти же навыки в FastAgent и выдаёт каждому агенту инструменты для его роли.

Для подключения только навыков к существующему FastAgent:

```bash
fast-agent skills add https://github.com/megamen32/catalog-to-json/blob/main/skills/catalog-extract/SKILL.md
fast-agent skills add https://github.com/megamen32/catalog-to-json/blob/main/skills/catalog-review/SKILL.md
```

Добавьте серверы из `.mcp.json` в конфигурацию вашего harness либо используйте CLI, который подключает инструменты сам.

## Первый запуск

Скачайте [пример конфигурации](fast-agent.config.example.yaml) и задайте ключ своей подписки Z.ai в `ZAI_API_KEY`.

```bash
catalog-json convert catalog.pdf --pages 1-3 \
  --config fast-agent.config.example.yaml --output output
catalog-json export output/catalog.json --format xlsx --output catalogue.xlsx
catalog-json export output/catalog.json --format html --output catalogue.html
```

В `output/catalog.json` находятся данные и статусы проверки. Если остаются ошибки или превышено время, команда возвращает код 2 и сохраняет результат для продолжения с `--resume`.

Сейчас по умолчанию используется GLM 5.3 Flash в двух отдельных контекстах. Модели извлекателя и проверяющего заменяются независимо. Проверка моделью уменьшает риск ошибок, но не гарантирует безошибочность каталога.

[Формат и архитектура](docs/ARCHITECTURE.md) · [Конфигурация и MiniMax](docs/CONFIGURATION.md)

## Бенчмарк

Команды `benchmark scan`, `benchmark extract`, `benchmark score` и `benchmark run` выбирают сложные страницы и сравнивают проекты/модели по независимому эталону. Результаты сохраняют ошибки, время и версии; первый проход оценивается отдельно от исправленного результата. [Как запустить сравнение](docs/BENCHMARK.md).

Independent evaluation: [Catalog Extraction Benchmark](https://github.com/megamen32/catalog-extraction-benchmark) provides 15 source-reviewed difficult pages, 500 engineering facts and common grading for canonical JSON and saved JSONL results.

## Full catalogue queue

`catalog-json convert-batch queue.json --output output --config fast-agent.config.example.yaml --extractor YOUR_MINIMAX_MODEL --reviewer YOUR_GLM_MODEL --parallel-stages --resume` converts every physical page of every source-bound entry in `queue.json`. Its `catalogs` array contains `id`, `source` and `source_sha256`. It records the exact program version, source-code/contract digest, model settings and page/run time, and preserves incomplete checkpoints. Each page must pass independent source review. The default per-agent timeout is 1200 seconds; the finite whole-queue deadline is 24 hours. No conversational transcripts are required.

`--parallel-stages` runs extraction and review in separate processes, with one active call per role by default. `--extractor-workers` and `--reviewer-workers` set finite maxima; `--initial-provider-concurrency` starts lower and increases after successful calls. Each provider reduces future admission and backs off independently on429, while admitted calls keep their existing deadlines. Failed reviews return the page for repair without a repair-count limit. `--seed earlier-output` retains matching-source/extractor files and their history; a changed contract requires a fresh extractor save and independent review. Earlier acceptance is never imported.

`tested_program` describes the queue runner. Per-page `candidate_producer` and `review_producer` describe the actual artifact-producing worker only when its receipt matches the saved bytes, source, model and contract. Legacy artifacts without this evidence remain explicitly `producer_unknown`.

`catalog-json native-batch queue.json --output native-output` saves directly readable text, words, image coordinates and parsing hints for every page. These JSON files are explicitly unreviewed source evidence, not an accepted catalogue.

Готовые альтернативы: [список 24 парсеров, MCP и сервисов](docs/READY-PARSERS.md). Подключение локальных Docling/PyMuPDF4LLM: пакет [Agent Plugin 1.0](plugins/catalog-parsers), пример `fast-agent.parsers.config.example.yaml`. Это необязательные источники структурированных данных для агента; окончательная проверка идёт по оригиналу.

В1.4.4 parser-plugin0.2.2 выдаёт JSON порциями до12000байт, чтобы FastAgent не вырезал середину длинных ответов. Переход выполняется по возвращённому next_offset. Native MCP/SDK-проверка восстановила весь Docling JSON страницы30 без потери байтов; точность1.4.4 на полном бенчмарке пока не измерена. [Результаты выбора инструментов](https://github.com/megamen32/catalog-extraction-benchmark/tree/main/examples/agent-routing/2026-10-12-body-routing-v1.4.2).

## Выгрузки каталогов

[Последняя частичная выгрузка:166/980 страниц](examples/catalogs/checkpoint-2026-10-13T003502Z-mixed-guarded15-review148) содержит JSON с фактическими версиями производителей и Excel с широкими таблицами. Принятие моделями и независимый визуальный аудит указаны отдельно; весь набор ещё не завершён. [Прежние версии](examples/catalogs) сохранены.
