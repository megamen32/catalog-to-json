# Сведение арматуры: физическая страница 169

Текущие участники: **Codex, native ZCode (он же GLM) и MiniMax M3.1 Flash Preview**. Отдельный GLM не вызывается и не учитывается. Это один согласованный случай, не итог всего сведения 980 страниц и не оценка точности.

Все трое выбрали наши строки: 150/19 и 150/24 → НАС-150-1Б; 150/34 → НАС-150-2Б. У плоских наблюдений Олега нет однозначной построчной связи. Текущий результат — `proof-three-reviewers.json`: обе исходные формы, три настоящих мнения, источник, страница, модели и версии сохранены. Мнения переиспользованы только для неизменного case; новых модельных вызовов для перехода к трём участникам не было.

MiniMax записал связи кратким словарём. Материализация проверяет каждый ключ и значение словаря по точным привязкам к исходным строкам. Строгий результат сравнения разных JSON-форм тоже сохранён; исходные мнения и извлечённые значения не переписываются.

Проверка текущей схемы из корня репозитория, без моделей:

```sh
python -m catalog_json.reconciliation.materialize --pack examples/reconciliation/armature-169-row-linkage/pack.json --votes examples/reconciliation/armature-169-row-linkage/votes/codex.json examples/reconciliation/armature-169-row-linkage/votes/zcode.json examples/reconciliation/armature-169-row-linkage/votes/minimax.json --bindings examples/reconciliation/armature-169-row-linkage/bindings.json --output .tmp/armature-169-three-reviewers.json
```

Файл `proof.json` и `votes/glm.json` — неизменная история прежней ошибочной схемы с четырьмя участниками. Для её воспроизведения добавьте `--role-profile legacy4` и четвёртый файл `votes/glm.json`. Исторический proof воспроизводится с прежним SHA; он не входит в текущий консенсус. Сырых транскриптов и PDF здесь нет.
