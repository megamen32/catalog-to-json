# Готовые решения для PDF-каталогов

Проверено по официальным источникам 12 октября 2026. Список составлен с двумя независимыми исследователями. «Готовое» здесь означает рабочую программу, сервис или агентный пакет; точность на наших инженерных каталогах подтверждается отдельно бенчмарком.

## Наиболее близкие к готовому решению

| Решение | Что уже готово | Подключение | Существенное ограничение |
|---------|----------------|-------------|--------------------------|
| [LlamaParse + LlamaExtract](https://developers.llamaindex.ai/llamaparse/parse/) | Таблицы JSON/HTML/CSV, XLSX; извлечение по JSON Schema | [Официальные MCP + skills и marketplace для Codex/Claude](https://github.com/run-llama/llamaparse-agent-plugins) | Облачная учётная запись/OAuth или API key; единицы, условия и рисунки надо проверить на наших PDF |
| [Docling](https://github.com/docling-project/docling) | Полный PDF→DoclingDocument→JSON, layout, таблицы и OCR | [Официальный MCP](https://github.com/docling-project/docling-mcp), SDK, skills | Не всякая конфигурация восстанавливает узкие/повёрнутые столбцы; требуется адаптация выходной схемы |
| [PaddleOCR PP-StructureV3](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/PP-StructureV3.html) | Layout/OCR/таблицы, JSON; русский ru, анализ ориентации | [Официальный MCP](https://github.com/PaddlePaddle/PaddleOCR/blob/main/docs/version3.x/integrations/mcp_server.md), CLI, skills | Модели и CPU/GPU зависимости; ориентация страницы не равна чтению каждого вертикального заголовка |
| [MinerU](https://github.com/opendatalab/MinerU) | Готовая программа со структурированным содержимым, таблицами и JSON | [Официальная MCP/skills экосистема](https://github.com/opendatalab/MinerU-Ecosystem), CLI | Разные локальные режимы/модели, условия лицензий; качество отдельных режимов проверять отдельно |
| [Unstructured Transform MCP](https://github.com/Unstructured-IO/unstructured-mcp-integrations) | Upload→transform/extract→poll→JSON/HTML/Markdown, schema extraction | Готовый hosted MCP | Credentials; Foundation marketplace относится к source/search/retrieval, не заменяет прямой Transform exporter |
| [LiteParse](https://developers.llamaindex.ai/liteparse/) | Локальное OCR, spatial JSON, bbox, screenshots и routing | Готовый локальный skill/plugin из LlamaParse marketplace, без API key | Товарная схема, сложные объединения и инженерные связи ещё не подтверждены нашим бенчмарком |

## Другие готовые локальные пайплайны и компоненты

| Решение | Готовый результат | Роль в нашем проекте |
|---------|-----------------|---------------------|
| [Marker](https://github.com/datalab-to/marker) | CLI PDF→JSON-дерево блоков/HTML-таблицы; опциональный LLM-проход | Независимый полный parser; надо фиксировать модельный backend и условия использования весов |
| [Chandra OCR 2](https://github.com/datalab-to/chandra) | PDF→HTML/Markdown, JSON-метаданные, сложный layout | Проверка мелких допусков/чертежей; доступный inference backend и адаптация HTML к ячейкам |
| [Surya 2](https://github.com/datalab-to/surya) | OCR/layout/table JSON, расширенный HTML | Компонент OCR и таблиц; не готовая товарная база |
| [Dolphin-v2](https://github.com/bytedance/Dolphin) | Готовые PDF/page/element demos, JSON/Markdown | Альтернативный структурный parser; русский в официальной model card не подтверждён |
| [PyMuPDF4LLM](https://github.com/pymupdf/pymupdf4llm) | Готовые JSON/Markdown/text, layout и OCR | Быстрый взгляд на исходник; сложные таблицы нельзя принимать без проверки |
| [img2table](https://github.com/xavctn/img2table) | PDF/image→таблицы/DataFrame/HTML→XLSX с объединениями | Почти готовый локальный табличный exporter; JSON/MCP обёртка, рисунки и текст остаются агенту |
| [gmft](https://github.com/conjuncts/gmft) / [Table Transformer](https://github.com/microsoft/table-transformer) | PDF→DataFrame/табличная структура, spanning/rotated tables | Отдельный табличный baseline; gmft не имеет собственного полного OCR/figure workflow |
| [Unstructured local](https://docs.unstructured.io/open-source/core-functionality/partitioning) | partition_pdf→элементы/HTML таблиц; JSON-сериализация | Локальная альтернатива cloud, требует inference/OCR зависимостей |
| [deepdoctection](https://github.com/deepdoctection/deepdoctection) | PDF analyzer, layout/table/HTML, OCR | Готовый анализатор, но более сложная установка; наша товарная схема остаётся внешней |
| [Camelot](https://camelot-py.readthedocs.io/en/stable/) | CLI таблицы→JSON/Excel/HTML/CSV | Дешёвый независимый baseline для текстовых PDF; собственный parsing_report не равен инженерной точности |
| [pdfplumber](https://github.com/jsvine/pdfplumber) | Символы/слова/линии/таблицы/bbox | Инструмент геометрии; не полный catalogue workflow и не OCR |
| [Tabula](https://github.com/tabulapdf/tabula-java) | Готовый Java CLI таблицы→CSV/TSV/JSON | Независимый текстовый baseline; scans требуют внешнего OCR |
| [olmOCR](https://github.com/allenai/olmocr) | Массовый PDF pipeline→Dolma JSONL/Markdown | Дорогой по локальным GPU ресурсам; явная ячеечная товарная схема не является готовым результатом |

## Облачные готовые document processors

| Решение | Готовое извлечение | Что потребуется |
|---------|------------------|-----------------|
| [Mistral OCR + Annotations](https://docs.mistral.ai/studio/document-processing/annotations) | OCR JSON/HTML tables, schema annotations | Mistral key и тонкий MCP tool; проверка rotated/merged на наших файлах |
| [Azure Document Intelligence Layout](https://learn.microsoft.com/azure/ai-services/document-intelligence/prebuilt/layout?view=doc-intel-4.0.0) | Ячейки/spans/polygons/рисунки, русский, rotated/merged tables | Azure resource/credentials, SDK→MCP/schema adaptation |
| [Google Document AI Layout Parser](https://docs.cloud.google.com/document-ai/docs/layout-parse-chunk) | Structured document/layout, сложные headers/tables | GCP processor/location/billing/ADC; обычный Form Parser не заменяет complex Layout Parser |
| [AWS Textract + IDP MCP sample](https://github.com/aws-samples/intelligent-document-processing-with-amazon-bedrock/blob/main/mcp/local_server/README.md) | Cells/merged cells и sample Bedrock extraction MCP | AWS credentials; Textract сам по себе не поддерживает русский, поэтому это не первый кандидат для наших каталогов |
| [Firecrawl AnyDoc](https://github.com/firecrawl/anydoc) + [Parse MCP](https://github.com/firecrawl/firecrawl-mcp-server) | Локальный AnyDoc / hosted parsing→Markdown/structured JSON | Уже используется AnyDoc. Hosted OCR и локальный MCP различаются; benchmark подаёт отдельно выбранную страницу |

## Что реально проверено

На сложной странице 78, direct parser без LLM и без исправлений эталоном:

- Docling 2.137.0: 86 из 140 инженерных фактов. Обнаружил две таблицы, но верхняя имеет 14 вместо 15 столбцов.
- PyMuPDF4LLM 1.28.2: 0 из 140 совместных инженерных фактов. Склеил две таблицы в одну; наличие чисел само по себе не даёт корректную связь изделия, поля, единицы и условия. Это не означает нулевую полноту текста.

Эти числа относятся к конкретным настройкам: CPU, native text, OCR disabled, отдельная physical page, source-preserving adapter и frozen инженерные assertions. Они не являются общим рейтингом программ. Полный 15-case direct-parser matrix сохраняет raw JSON, canonical candidates, версии/options, время и детальные ошибки. Отдельно проверяется FastAgent с parser MCP evidence; его показатели нельзя подменять standalone parser результатом.

Следующие наиболее полезные проверки: PP-StructureV3 и MinerU среди локальных полных пайплайнов, LiteParse среди готовых локальных агентных пакетов, LlamaParse MCP среди максимально готовых сервисов при наличии авторизации. Мы не переписываем OCR/layout модели: Agent Plugin 1.0 даёт агенту существующие MCP/skills/CLI, а наш код сохраняет происхождение, приводит форматы и проверяет инженерные данные.

## Полный локальный прогон: 15 страниц, 500 фактов

| Готовый parser | Версия | Инженерные факты | Время 15 запусков |
|---|---|---|---|
| Docling | 2.137.0 | 266/500 (53,2%) | 480,070 с |
| PyMuPDF4LLM | 1.28.2 | 13/500 (2,6%) | 419,758 с |

Все 30 запусков завершены. Один отдельный процесс на страницу, два CPU-потока, native text, OCR выключен, одна попытка; срок одного запуска 180 с, всей матрицы 1800 с. Время включает запуск процесса и адаптацию результата. Модели Docling уже были загружены. Это точность выбранных инженерных фактов, не всей страницы.

Измерен прототип plugin 0.1.0 до публикации catalog-to-json 1.3.0: дерево имело незакоммиченные изменения. В отчётах сохранены Git revision 2eed0ad623df7c308f67f65f4bd2a418865aaa8d, dirty=true, версии backend и hash исходников адаптера. Эти результаты не выдаются за измерение неизменённого релизного тега.

Отдельная проба MiniMax-M3.1-Flash-Preview с parser MCP на странице 78: 140/140 инженерных и 140/140 буквальных табличных проверок, 11/11 подписей рисунков и 3/3 проверок отсутствия ошибочных подписей. Время 167,961 с включает холодный запуск Docling (103,865 с). Это первый проход прототипа без проверяющего, а не доказательство полной правильности страницы. Сравнение скорости с прежним запуском без plugin не является контролируемым сравнением: версии и состояние кэша различались.

Выходные JSON, raw backend JSON, receipts, времена и ошибки сохранены в локальном архиве измерений; документы и результаты извлечения не публикуются. [Протокол независимого бенчмарка](https://github.com/megamen32/catalog-extraction-benchmark/blob/main/docs/READY-SOLUTIONS.md).
