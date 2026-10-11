# Catalog to JSON

FastAgent с навыком и инструментами превращает PDF-каталоги в JSON с отдельной проверкой по оригиналу.

- Агент извлекает доступное через AnyDoc, сам открывает страницу и увеличивает сложные участки через Vision.
- JSON сохраняется инструментом с проверкой схемы; ответ агента в чате может быть обычным текстом.
- Проверяющий сначала независимо читает оригинал, затем получает кандидат. Инструмент сопоставляет ячейки и блокирует противоречивый положительный вердикт.
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
