# Архитектура Dota 2 Copilot

Документ описывает слой Copilot поверх базового приложения d2bg v2. Как устроено само d2bg,
написано в `docs/DESIGN.md`. Что приложение трогает в системе, написано в `docs/SAFETY.md`.
Порядок дальнейшей работы описан в `docs/IMPLEMENTATION_PLAN.md`. Техническое задание лежит в
`DOTA2_COPILOT_TZ.md`.

Состояние на 2026-11-06: выполнены этап 0 и минимальный каркас этапа 1.

## Основа

База — `Tajaddin/dota2-build-generator`, ветка `main` (`9d8cdfb`) плюс ветка автора
`fix-live-draft` (`0cfd08c`). Эта ветка — fast-forward от `main` с тестами. Она добавляет то, что
GSI реально присылает игроку в ranked: своего героя и сторону, баны из событий чата, союзников и
замеченных врагов с миникарты после загрузки. В ней же лежат две анонимизированные записи
настоящих игр (`tests/d2bg/fixtures/`). Код v1 (`main.py`, `logic/`, `ui/`, `ml/`) не используется.

## Поток данных

```text
Dota 2 --POST /gsi--> LiveEngine.ingest            (без изменений: таймеры, сборки, алерты, драфт)
                            |
                            +-- on_payload --> Services._on_payload
                                                 |-- Recorder.write        сырой GSI в .jsonl.gz (как было)
                                                 +-- Copilot.observe
                                                       |-- build_context   GameState + драфт движка -> GameContext
                                                       |-- diff_events     предыдущий и новый контекст -> события
                                                       |-- CopilotStore    matches, gsi_events_index (SQLite, WAL)
                                                       |-- baseline        подсказки LiveEngine -> Recommendation
                                                       |-- проверка        evidence_ids только из контекста
                                                       +-- CopilotStore    recommendations (журнал решений)

GET /api/copilot/status            GSI, режим (game/demo/replay), патч, GameContext с источниками, журнал
GET /api/copilot/recommendations   журнал рекомендаций текущего или указанного матча
```

Copilot подключён через уже существующий хук `LiveEngine(on_payload=...)`. Поведение движка
не изменилось: все его исходные тесты проходят без правок. Если Copilot падает, ошибка
попадает в поле `error` ответа `/api/copilot/status`, а живой экран продолжает работать.

## Компоненты ТЗ и их реализация

| Компонент из ТЗ | Где он сейчас | Комментарий |
|---|---|---|
| GSI parser | `gsi/state.py` (база) | Переиспользован без изменений |
| GameStateNormalizer | `copilot/pipeline.py: build_context` | Каждая группа полей помечена источником |
| EventBus | `copilot/pipeline.py: diff_events` + `Copilot.observe` | Синхронная функция. Потребитель пока один, шина не нужна |
| Recorder / SQLite | `gsi/recorder.py` (база) + `copilot/store.py` | Сырой GSI лежит в `.jsonl.gz`. В SQLite лежат только ссылки (файл и номер кадра) |
| StateFusion | `build_context` | Сейчас сливает GSI и позицию из настроек. CV и ручной драфт появятся на этапе 3 |
| CandidateGenerator | `copilot/pipeline.py: baseline` | Пока только переупаковывает подсказки LiveEngine (порядок pro-сборки и самый частый pro-скилл) |
| Validator | проверка `evidence_ids ⊆ context.evidence_ids` | Полный валидатор (ранги, уровни, дубли предметов) — этап 2 |
| DecisionJournal | таблица `recommendations` | Одна активная рекомендация на тип, предыдущие получают статус `expired` |
| Jev / Groq / DeepSeek | нет | Этапы 4 и 5 |

## Контракты (`copilot/models.py`)

`GameContext` — единый источник правды. Все поля необязательные. Поле `sources` хранит источник
для каждой группы полей: `match`, `patch`, `hero`, `position`, `draft`, `economy`. Возможные значения:
`gsi`, `cv`, `opendota`, `manual`, `snapshot`, `unknown`. Неизвестное остаётся `None` или `unknown`.

- `time_s` — игровые часы так, как их видит игрок (`map.clock_time`, до горна отрицательные). Системное
  время в контекст не попадает. Отсчёт OpenDota тоже идёт от горна, поэтому таймкоды совпадут.
- `learned_skills` — все способности, которые прислал GSI, с уровнем (0 = ещё не изучена).
- `allies` и `enemies_visible` заполняются только внутри матча. Вне матча движок помнит прошлый
  драфт, но в контекст он не попадает.
- `draft_confidence` равен `None`, пока нет CV-источника.
- `evidence_ids` — словарь фактов, на которые разрешено ссылаться: `hero:<key>`, `build:<key>` (есть
  pro-сборка), `level:<n>`, `inventory:<item>` (инвентарь, рюкзак, тайник), `ally:<key>`, `enemy:<key>`.
  Рекомендация, которая ссылается на отсутствующий факт, отбрасывается.

`CopilotEvent`: `match_started`, `phase_changed`, `hero_selected`, `skill_point_gained`,
`skill_leveled`, `item_changed`, `draft_changed`, `death`, `respawn`, `match_finished`. Новый матч
(в том числе запуск приложения посреди игры) даёт только `match_started`: текущее состояние
восстанавливается как есть и не превращается в поток старых событий. Перенос предмета в тайник
событием не считается.

`Recommendation` повторяет поля из раздела 4 ТЗ. `confidence_kind` объясняет, что означает
`confidence`: `none`, `pro_pick_share` (доля pro-матчей с этим выбором) или `unverified_model_score`.
Это никогда не вероятность победы. `id` вычисляется из матча, типа, кандидата и `context_hash`,
поэтому повторный прогон того же матча ничего не дублирует.

## Хранилище (`copilot/store.py`)

Файл `%LOCALAPPDATA%\d2bg\copilot.sqlite3` (в тестах — `D2BG_HOME`). Режимы `WAL`,
`synchronous=NORMAL`, `foreign_keys=ON`. Миграции — список SQL-скриптов, номер версии хранится в
`PRAGMA user_version`. Каждый скрипт выполняется один раз в своей транзакции.

| Таблица | Содержимое | Индексы |
|---|---|---|
| `matches` | матч, источник (`game`/`demo`/`replay`), герой, сторона, патч, первое и последнее появление, файл записи | PK `match_id` |
| `gsi_events_index` | событие, игровое время, деталь, файл записи и номер кадра | уникальный `(match_id, type, detail, time)`, `(match_id, game_time_s)` |
| `recommendations` | все поля `Recommendation` и `created_at` | `(match_id, game_time_s)`, `type`, `created_at` |

Запись идёт только при событиях, а не на каждом пакете GSI. Замер на демо-матче (2 286 пакетов,
этот ПК): `ingest` без Copilot — p50 0.39 мс, p95 0.45 мс; с Copilot и файловой SQLite — p50 0.47 мс,
p95 0.59 мс. Ориентир ТЗ — 500 мс.

## Принятые решения и отличия от ТЗ

| # | Решение | Почему |
|---|---|---|
| C1 | Основа — `main` плюс `fix-live-draft` | Ветка того же автора с тестами и реальными записями. Без неё драфт игрока из GSI почти пуст |
| C2 | Миграции через `PRAGMA user_version` вместо Alembic | ТЗ допускает эквивалент. Alembic потянул бы SQLAlchemy ради трёх таблиц |
| C3 | Без отдельной шины событий | Потребитель один. Шину стоит добавить, когда появится второй независимый потребитель |
| C4 | Таблицы `draft_observations`, `provider_calls`, `postmatch_*`, `practice_goals` добавляются миграциями своих этапов | Пустые таблицы впрок пришлось бы менять позже |
| C5 | Флаги функций — в существующем `settings.json`, а не в таблице `feature_flags` | Настройки уже есть, атомарно сохраняются и проходят валидацию |
| C6 | Демо и replay пишутся в журнал с меткой источника | Конвейер проверяется без игры. В UI метка не даст выдать демо за реальность |

## Что готово, что расширить, что получить нельзя

| Возможность | Статус | Где / почему |
|---|---|---|
| Установка, удаление, токен и health GSI; Setup-страница | готово | `gsi/installer.py`, `/api/gsi/*`, `web/src/pages/Setup.tsx` |
| Запись GSI, replay, демо-матч | готово | `gsi/recorder.py`, `gsi/demo.py`, `/api/replay`, `/api/demo` |
| Статус Copilot: подключение, режим, патч, источники полей, ошибки, `stale` | готово (API) | `/api/copilot/status`. В UI пока нет |
| Свой герой, сторона, баны, союзники после загрузки, замеченные враги | готово | `fix-live-draft`, `live/engine.py` |
| Пики врагов во время ranked-драфта | **нельзя из GSI** | Блок `draft` у игрока пустой (проверено на записях автора). Варианты — ручной ввод или CV (этап 3) |
| Предметы, кулдауны и позиции врагов в своей игре | **нельзя** | GSI присылает их только зрителю. Использовать запрещено ТЗ и SAFETY |
| Подбор героя (контрпики, синергия, мета, пул, позиции, баны) | готово | `draft/advisor.py`, `draft/service.py` |
| Процент победы драфта | расширить | Модель есть (`draft/model.py`). Нужна явная пометка «оценка модели», а не факт |
| Следующая способность | расширить | Индекс по всем потраченным очкам и доле pro. Нет проверки максимального ранга, уровней ульты и талантов, позиции. Этап 2 |
| Следующий предмет, остаток золота с учётом компонентов, ETA, ситуативные предметы против драфта, buyback-предупреждение | готово, расширить | `builds/guide.py`, `knowledge/counters.py`, `live/engine.py`. Нужны категории Core / Situational / Defensive / Buyback и исключение дублей. Этап 2 |
| Quickbuy | новое | Только инструкция в UI, без кликов. Этап 2 |
| `/compact` для второго монитора | готово, расширить | Есть страница. Нужен блок Copilot. Этап 2 |
| Always-on-top окно | есть, не проверено | `d2bg window` реализован прямо в `cli.py` (pywebview). ТЗ ошибочно считает его отсутствующим: отсутствует только отдельный файл `window.py`, на который ссылается `[tool.coverage.run] omit` |
| Послематчевый отчёт | готово базово | `matches/postgame.py`, `matches/review.py`, `profile/analytics.py`. Модель находок с `evidence_ids` и `certainty` — этап 5 |
| Провайдеры Jev / Groq / DeepSeek, лимиты, кэш | нет | Этап 4 и 5 |
| Хранение ключей | расширить | Сейчас `settings.json` в папке пользователя, наружу ключ маскируется (`public_view`). Для облачных ключей нужен keyring (Windows Credential Manager). Этап 4 |
| Статическая проверка запрета памяти, ввода и захвата | готово | `tests/d2bg/test_safety.py` проверяет `pymem`, `pyautogui`, `pynput`, `keyboard`, `mss`, `ctypes`, `ReadProcessMemory`, `SendInput` и другие |
| MMR | нельзя точно | OpenDota отдаёт медаль, а не MMR |
| Причинное влияние совета на победу | нельзя | Только наблюдаемые факты «совет был — игрок сделал — что произошло дальше» |
