# Catalog to JSON

Превращает PDF-каталоги в структурированный JSON с проверкой по оригиналу.

- Прямое извлечение через AnyDoc; Vision для повёрнутых таблиц, сканов и сложных страниц.
- Отдельный проверяющий ищет пропущенные строки, сдвинутые значения, неверные единицы и ошибки объединённых ячеек.
- Сохраняет исходные подписи, пустые поля, чертежи и историю исправлений.
- Excel и читаемый HTML создаются из JSON. Непроверенные результаты не экспортируются по умолчанию.

## Установка

```bash
uv tool install git+https://github.com/megamen32/catalog-to-json
```

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
