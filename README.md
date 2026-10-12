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

`catalog-json convert-batch queue.json --output output --config fast-agent.config.example.yaml --extractor YOUR_MINIMAX_MODEL --reviewer YOUR_GLM_MODEL --resume` converts every physical page of every source-bound entry in `queue.json`. Its `catalogs` array contains `id`, `source` and `source_sha256`. It records the exact program version, source-code/contract digest, model settings and page/run time, and preserves incomplete checkpoints. Each page must pass independent source review. The default per-agent timeout is 1200 seconds; the finite whole-queue deadline is 24 hours. No conversational transcripts are required.
