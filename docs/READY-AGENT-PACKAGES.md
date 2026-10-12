# Дополнительные готовые агентные пакеты

Проверено 12 октября 2026. Девять дополнительных готовых пакетов сверх прежних 24; отдельно проверен доступный Adobe Acrobat app. Plugin, MCP и отдельный skill различаются; не всем нужен облачный ключ. Числа ниже измеряют извлечение парсера, а не запуск полного агента.

| Пакет | Упаковка / лицензия | Что готово | Реальная проверка |
|---|---|---|---|
| [Xberg](https://github.com/xberg-io/xberg) 1.3.8 | Codex/Claude/Cursor/Factory plugin + MCP + skills; MIT | JSON text/tables/cells/bbox, Markdown; Local full document parser; engineering schema/reviewer/Excel not included | MCP initialize and 9 tools confirmed through actual plugin launch script. Official musl CLI1.3.8 --version and15-case extraction completed. GNU binary blocked by GLIBC2.38/2.39 requirement; musl fixes privately. |
| [LandingAI ADE](https://github.com/landing-ai/ade-document-processing-skills) 3.4.0 | Official Claude plugin + Agent Skills; MIT | JSONSchema fields + citations/bboxes/confidence; parse Markdown; dataframe/Excel recipes; Cloud parse→schema extract→classify/split→stitch/export workflow | Manifest and source verified. Not run: protected provider authentication not available to this test; no request/registration/call made. |
| [Reducto CLI](https://github.com/reductoai/claude-plugins) skill1.0.0, plugin version not declared | Official Claude plugin + Agent Skills; CLI; MIT | Parse Markdown; extract JSONSchema; edit document; Ready cloud end-to-end document workflow | Manifest and skill verified. Not run: requires reducto login/authenticated account. |
| [Anthropic document-skills](https://github.com/anthropics/skills) marketplace1.0.0 | Official Claude marketplace document-skills; PDF/XLSX Agent Skills; Document skills proprietary/source-available under Anthropic agreements; NOT repo Apache-2.0 | Agent recipes using pdfplumber/pypdf and XLSX; no universal engineering schema; PDF manipulation/extract+XLSX authoring skill recipes, not standalone digitization engine | Manifest/scripts/license verified. No agent/provider run. Existing pdfplumber measurement is not this skill end-to-end benchmark. |
| [pdf-mcp](https://github.com/jztan/pdf-mcp) 3.5.0 | Ready MCP stdio/HTTP + Claude Desktop MCPB; NOT Agent Plugin1.0; MIT | JSON pages/text/tables/images/rectangles; table backend metadata; Local PDF read/search/render/chart/cache tool workflow; no SKU schema/reviewer/XLSX | Installed exact revision; MCP initialize and13 tools; pdf_read_pages physical78 successful, tables0 with native text. Full15-case calls running/completed; no model warm/provider calls. |
| [Data liberation](https://github.com/CUPIDS-Lab/data-liberation-skill) revision-pinned | Agent SKILL package, no native plugin manifest/MCP; MIT | Tidy CSV/dataframes/JSON recipes, Pandera/provenance; Agent end-to-end survey→extract→tidy→audit→publish recipe, relies on parsers | SKILL/reference/template source verified; no executable catalogue parser or provider run. |

## Версии и доказательства

- Xberg: `b4bdf0b9346188c8b540698f80b359fb9ff60ed0`, `plugin/.codex-plugin/plugin.json; plugin/.claude-plugin/plugin.json; plugin/.mcp.json`; исходник в приватном архиве проверки. Требования: No key; CPU native; optional OCR/VLM disabled
- LandingAI ADE: `f72208154e5534261a9b12f4190bdc843aee191d`, `plugins/ade-document-processing/.claude-plugin/plugin.json`; исходник в приватном архиве проверки. Требования: VISION_AGENT_API_KEY; no local GPU needed
- Reducto CLI: `cbbd7a9673a08f55355f3c9ef156f68cb2245912`, `plugins/reducto-cli/.claude-plugin/plugin.json`; исходник в приватном архиве проверки. Требования: Device-code login/account; no GPU required
- Anthropic document-skills: `dbd4588f9e1033efb41dad4bef2f7947c8993d44`, ` .claude-plugin/marketplace.json; skills/pdf/LICENSE.txt; skills/xlsx/LICENSE.txt`; исходник в приватном архиве проверки. Требования: Local libraries; full agent workflow needs a host model
- pdf-mcp: `a7815534a365c49b3bc08a34865e18a6ed92dc0c`, `pyproject.toml; src/pdf_mcp/server.py; manifest.json MCPB`; исходник в приватном архиве проверки. Требования: No auth for local stdio; native CPU; OCR via local Tesseract rus+eng possible; optional search embeddings
- Data liberation: `acb59c9bf5439f06642768e42a619757314287fa`, `SKILL.md`; исходник в приватном архиве проверки. Требования: Local CPU dependencies; host agent model for orchestration

Статический Xberg musl1.3.8: archive SHA256 `fc0b950353ee7347e6e50c05038e8cdd3fbcb9804b5d3c558adf06634f180352`; исходная GNU-версия не запускается на системной GLIBC2.35. Использован официальный musl выпуск, системные библиотеки не изменены. Старый xberg-io/plugins архивирован; актуален xberg-io/xberg/plugin.

MCP receipts: `plugins/xberg/{initialize,tools-list,receipt}.json`, `plugins/pdf-mcp/{initialize,tools-list,receipt,page78-result}.json`; команды клиента `probe_mcp.py`. Pinned CLI и15-case receipts: `run_plugins.py`, `plugin-executions.json`, `plugin-summary.json`. Исходные ответы сохранены отдельно от canonical candidates.

## CPU parser baseline

| Parser / режим | Факты /500 | Страницы | Время |
|---|---|---|---|
| pdfplumber0.11.10 default native geometry |5|15/15|26.867s|
| Tabula-java1.0.5 lattice, tabula-py2.10.0 |39|14/15|66.083s|
| Tabula-java1.0.5 stream |0|15/15|62.178s|

На странице IZ35 lattice падает с `IllegalArgumentException: lines must be orthogonal, vertical and horizontal`. Ошибка сохранена, не замаскирована нулём таблиц. Denominator500 включает15 недоступных фактов этой страницы. CPU receipts `cpu-summary.json`, `cpu-executions.json`, `cpu/<backend>/<case>/`; wheel snapshot SHA256 `881726c7e27b95b68c6ee825f4d572b56c9d32f504fb4d47c564dc8b2dfd0256`.

Общие условия: физическая страница из PDF, native text, OCR выключен, CPU affinity102,103 / OMP2, RAM12GiB, timeout240s, один собственный тяжёлый процесс; provider/GPU fallback отключён. Все30новыхplugin-экстракций завершаются до чтения fixture для grade. Нативные заголовки сохраняются, отсутствие header-role означает объявленную конвенцию первой строки. Пустой padding у новых backend трактуется unknown; source_blank не выдумывается. Native table matrices не дополняются из gold.

## Покрытие прежних24

Это сверка с текущим docs/READY-PARSERS.md владельца; уже выполненные прогоны Root/Mac/GPU здесь не повторялись.

| Решение | Тип / подключение | Текущий статус этой дополнительной работы |
|---|---|---|
|LlamaParse + LlamaExtract|Official MCP+Codex/Claude plugin|Cloud auth required; existing24|
|Docling|Official MCP+CLI|Root tested266/500; not rerun|
|PaddleOCR|Official MCP+CLI|GPU/CPU pipeline owned by another executor; not rerun|
|MinerU|Official ecosystem MCP/skills+CLI|GPU pipeline owned by another executor; not rerun|
|Unstructured Transform|Hosted MCP|Cloud credentials unavailable|
|LiteParse|Official local LlamaParse plugin/skill|Core8 run owned byRoot; not rerun|
|Marker|CLI, optional LLM|Not benchmarked; CLI/OCR component, not plugin claim|
|Chandra2|CLI OCR|Not benchmarked; CLI/OCR component, not plugin claim|
|Surya2|OCR/layout component|Not benchmarked; CLI/OCR component, not plugin claim|
|Dolphin-v2|CLI demos|Model dependencies; not plugin claim|
|PyMuPDF4LLM|CLI/SDK|Root13/500; not rerun|
|img2table|SDK/XLSX exporter|Root integrating/test isolated native executor|
|gmft/TableTransformer|SDK/table pipeline|Root integrating/test isolated native executor|
|Unstructured local|SDK partition_pdf|No install started after plugin search priority changed|
|deepdoctection|PDF analyzer SDK|Heavy dependencies; no install in this work|
|Camelot|CLI tables|Existing Root Core8; not rerun|
|pdfplumber|Geometry SDK|This run5/500 completed|
|Tabula|Java CLI|This run39/500 lattice;0/500 stream|
|olmOCR|GPU pipeline|Not benchmarked; GPU pipeline, no plugin claim|
|MistralOCR|Cloud API+annotations|Key unavailable|
|AzureLayout|Cloud API+SDK|Resource/auth unavailable|
|GoogleDocAILayout|Cloud API+SDK|ADC/billing unavailable|
|AWS Textract+IDP|API+sampleMCP|AWS auth unavailable; Russian Textract unsupported|
|FirecrawlAnyDoc/Parse|AnyDoc local + hostedParseMCP|Existing nativeadapter; directory Firecrawl plugin found, unconnected|

## Решение для интеграции

Xberg — новый готовый локальный plugin для инструментов агента: сохранить официальный package и фиксированный musl binary, добавить его MCP как независимое evidence. Он ещё не заменяет Docling: на78 нативный JSON даёт две таблицы, но первая начинается с товарной строки без заголовков, другая — обрывок повёрнутого заголовка с отрицательным bbox. pdf-mcp — второй готовый локальный MCP для чтения/рендера/проверки страниц; на78 native tables отсутствуют. Выбирать как инструменты агента, не как доказанных победителей распознавания. ADE и Reducto — наиболее готовые schema-extraction workflows, но без доступной авторизации их качество не измерено. Anthropic PDF/XLSX skills не копировать в публичный пакет из-за явных ограничений лицензии. CUPIDS подходит как MIT workflow recipe, не как самостоятельный extractor.

## Завершённый frozen grade новых локальных пакетов

- xberg: 0/500; 15/15 завершены; native tables 11; 3.280s. Native headers preserved when present; no explicit header metadata means declared first-row convention. Padding remains unknown.
- pdf-mcp: 1/500; 15/15 завершены; native tables 21; 36.922s. Native headers preserved when present; no explicit header metadata means declared first-row convention. Padding remains unknown.

`run_plugins.py` retained native extraction receipts; grading call in its initial suffix had a local helper-signature error after all30 native extracts completed. Fixed standalone `grade_plugins.py` grades preserved native output without rerunning extraction. Scores in `plugin-summary.json`.

## Дополнительный настоящий Agent Plugins1.0 пакет дляExcel

[sbroenne/mcp-server-excel](https://github.com/sbroenne/mcp-server-excel), MIT; revision22438fd33ea20ef3ae1f0d446c9b3af640ff100b. `.github/plugins/excel-mcp/plugin.json` действительно с `$schema:https://agent-plugins.org/schemas/1.0.0/plugin.schema.json`, `mcp.json` поставляется. Runtime prerequisite: Windows + desktopExcel2016+ + interactive desktop. Это готовый Excel automation/export MCP/CLI, неPDF extractor; Linux/Mac benchmark неприменим, запуск здесь не пытался. Source manifest version0.0.0 — build placeholder, не заявляю протестированный бинарный релиз. Exactmanifest/MCP snapshots: research/excel-mcp-manifest.json и research/excel-mcp-mcp.json.

## Ещё два готовых MCP: подтверждённый запуск

- [TableShot](https://github.com/Bespoke34/tableshot)0.1.1 MIT, revisionccb86cc2f14bac877b825b3f91d3cd01f01f3892. MCP initialize и2tools успешны. Нативные таблицы JSON/HTML/CSV/Markdown; ML/OCRextras не установлены. Это MCP, собственного AgentPlugin manifest нет.
- [PDF Capture MCP](https://github.com/ChenHongYu2026/pdf-capture-mcp)0.12.0 alpha MIT, revisionea1aaf366a2c30babab0d067a7a7038a69174333. MCP initialize и14tools успешны; отдельныйprivatecache, setup_vlm(disable) успешен. Более полный готовый extraction→Markdownaudit→QC/repair→knowledgepackage workflow, optionalMarker/MinerU/VLM. Это MCP/CLI, собственного AgentPlugin manifest нет. Runtimeextraction ещё ожидает окончания нашего текущегоCPUhi_resrun.

Receipts: plugins/tableshot иplugins/pdf-capture-mcp/{initialize,tools-list,probe-receipt}.json; probe_more_mcp.py. Никаких install_engine/download_models/setup_embedding/cloudtools не вызывалось.

## Последние реальные прогоны

|Backend|Correct/500|Canonical coverage|Seconds|Native table count|
|---|---:|---:|---:|---:|
|Unstructured0.27.25 hi_res/yolox/rus+eng,CPUtorch|6|13/15|668.773|См.perpage|
|PDF Capture MCP0.12.0 + privateoptionspatch|1|15/15|15.061|62|
|TableShot0.1.1 base native|1|15/15|17.335|38|

Unstructured native partitioning ответил на15страницах, но frozenHTMLadapter отказал ARM103/ARM111 из-за перекрывающихся rowspan/colspan. RawelementJSON сохранён; нативные spans не исправлялись. PeakRSS1.744GiB; torch2.14.1+cpu, inference1.6.13, ONNXRuntime1.31.0. Sourcefixture SHA совпадает с установленным immutablebenchmark0.2.0 для15/15файлов: gold-snapshot/manifest.json; gold snapshot создан только после native extraction.

PDF Capture original0.12.0 на78 возвращает ok:true/table0: extractor передаёт pdfplumber неподдерживаемые settings lattice/stream и глотает ValueError. Privatepatch явного отображения lattice→lines,stream→text восстанавливает3таблицы на78; standaloneAPIproof и originalMCP сохранены. Это patchedforkрезультат, не officialreleaseaccuracy. Patch: pdfcapture-patch/strategy-options.patch, upstream revisionea1aaf366a2c30babab0d067a7a7038a69174333.

Полный patched PDF Capture workflow78 действительно создал Markdown+README+chunksJSONL+metadata+QCpackage; backendexplicitpymupdf, VLM/embedding/indexoff,auto_repairtrue. Native markdown склеивает верх/низ в12columns; QC WARN, а critical MD-105 считает напечатанные50Гц вheader признакомdata row corruption: этот detector нельзя считать engineering gold. Firstworkflow31s сопровождался invalidJSONRPC из native diagnostics на stdout. Первая попытка stdoutpatch ошибочно подменила внутренний StringIOINFO_MESSAGES наstderr и дала toolbodyok:false, хотя MCPisError:false. Сохранена workflow78-transport-attempt1. Новый минимальный stdout-channel.patch направляет только pymupdfmessages вstderr. Финальный workflow78-transport-fixed29.343s: semanticok:true, MCP JSONRPCerrors отсутствуют, QC WARN; Markdown побайтово совпадает с первым успешным workflow. Исходныйresponse и parsernoise сохранены; genericglobalstdoutredirect не использован.

Финальные MCP evidence: more-plugin-summary.json; plugins/pdf-capture-mcp-{official,patched}/<case>; plugins/tableshot/<case>; plugins/pdf-capture-mcp-patched/workflow78{-transport-fixed}. Пакетslibfrozen: final-installed.txt; privatehelpers/runtimeSHA: private-manifest.json.

## Каталог установленного клиента: Adobe

По live plugin-management search_plugins найден настоящий [Adobe Acrobat](https://www.adobe.com/acrobat.html) appplugin, installed:false (available). Directorymetadata обещает PDFconvert/OCR/pageoperations; runtime tools не подключены/не проверены. Snapshotresearch/adobe-plugin-directory.json. Нельзя автоматически приписывать этому app возможности отдельного [AdobePDF ExtractAPI](https://developer.adobe.com/document-services/docs/overview/pdf-extract-api/): именноAPI официально даёт структурныйJSON/cellspans иoptionalCSV/XLSX/PNG. API — готовый cloudprocessor, не AgentPlugin1.0; требует отдельной авторизации, cloudcalls/регистрации в этой работе не выполнялись. Лицензия app/service коммерческая, это не MITпакет длявстраивания.
