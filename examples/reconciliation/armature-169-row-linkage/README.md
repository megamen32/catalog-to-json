# Пример согласованного сведения: арматура, физическая страница 169

Это один разобранный случай, не готовое сведение всех 980 страниц и не оценка точности.

Все четыре участника — Codex, native ZCode, GLM 5.3 Flash через CodingEndpoint и MiniMax M3.1 Flash Preview — выбрали наши строки: 150/19 и 150/24 → НАС-150-1Б; 150/34 → НАС-150-2Б. У плоских наблюдений Олега нет однозначной построчной связи. Обе исходные формы и все четыре мнения сохранены в proof.json. Точные источник, страницы, производители, модели, раунд и SHA указаны в JSON.

MiniMax дополнительно записал связи отдельным словарём. Исходный строгий consensus с различными JSON selected_value сохранён как unresolved; дополнительная materialization проверяет каждое значение и каждый ключ словаря по точным JSON-pointer привязкам к выбранным строкам. Она принимает выбранную всеми сторону только после этой проверки. Мнения не исправляются и новые голоса не создаются. Три мнения проецированы с того же побайтно неизменного case; новый вызов был только у MiniMax и занял 23.888 с.

Проверка без моделей из корня репозитория:

```sh
python -m catalog_json.reconciliation.materialize --pack examples/reconciliation/armature-169-row-linkage/pack.json --votes examples/reconciliation/armature-169-row-linkage/votes/codex.json examples/reconciliation/armature-169-row-linkage/votes/zcode.json examples/reconciliation/armature-169-row-linkage/votes/glm.json examples/reconciliation/armature-169-row-linkage/votes/minimax.json --bindings examples/reconciliation/armature-169-row-linkage/bindings.json --output .tmp/armature-169-replayed-proof.json
```

Результат записывается только в новый файл. Сырые транскрипты и PDF здесь не опубликованы.
