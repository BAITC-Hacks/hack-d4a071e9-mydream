# Контекст проекта для Claude Code

Хакатон HackAlem AI, кейс «Граф денег» (трек Freedom, AML). 5 часов, команда 3 чел. Общаемся по-русски.
Репозиторий: https://github.com/BAITC-Hacks/hack-d4a071e9-mydream, ветка `beketkz`.

## Что уже сделано (проверено на чистом venv)
- `python -m moneygraph run --data data --out output` → 3 валидных CSV за 4 с, детерминированно.
- `python -m moneygraph explain <gid>` — объяснение роли за минуту (must-have 3).
- `python -m pytest -q tests` — 7 тестов проходят (must-have + обрезанные + дробление/устойчивость + ассистент без сети).
- `streamlit run app/streamlit_app.py` — экран просмотра, vis.js встроен (работает офлайн).
- README.md — запуск, таблица правил и порогов, ловушки данных, масштабирование, сценарий демо.
- DESIGN.md — требования, архитектура, компромиссы, план по часам.
- Офлайн-запуск без установки Python: `run_offline.bat` / `run_offline.sh` / `run_mac.sh`.
  Сборка: на Windows (Git Bash) `bash tools/build_portable_win.sh` (+ `tools/pack_bundles.py`, `tools/check_deps.py`),
  на Linux `bash tools/build_portable.sh`. python-build-standalone 3.11.16 (релиз 20260901).
  Готовые архивы целиком — GitHub Release `offline-bundles`; частями по 25 МБ — ветка `offline-bundles`.
  macOS-архив без интерпретатора: `run_mac.sh` скачивает Python и библиотеки при первом запуске (нужен интернет).
  На Windows распаковывать только `tar -xf`, Проводник обрывает распаковку ~18 тыс. файлов.
  Windows-архив проверяется на этой машине; Linux и macOS собираются из колёс PyPI без запуска (см. BUILD_INFO.txt в dist/).
- `.streamlit/config.toml` отключает вопрос Streamlit про e-mail при первом запуске.

## Правила работы
- Все пороги и веса — только в `moneygraph/config.py`. Не хардкодить gid.
- Роли — правилами с порогами; LLM (OpenAI) допустим только в гипотезах/ассистенте, не в присвоении роли.
- `truncated` (444 узла на 4-м колене) никогда не `terminal`. У seed не использовать `pass_through`.
- Формулировки — «признаки консолидации», «гипотеза для проверки», не утверждения о виновности.
- После любой правки: `run` → `pytest` → md5 CSV не должны меняться без причины.
- UI и explain читают только `output/`, ничего не пересчитывают.
- Файлы в UTF-8. Коммитить после каждого этапа.

## Сделано дополнительно
- Экран: вкладки «Правила ролей», «Дробление», «Устойчивость», «Ассистент», «Схема решения», «Демо».
- `moneygraph/extras.py` → `output/bursts.csv`, `output/resilience.csv` (считаются в `run`, UI только читает).
- Ассистент на OpenAI (`moneygraph/assistant.py`, `python -m moneygraph ask`); ключ в `openai_key.txt`
  (по просьбе команды, репозиторий приватный) — после хакатона отозвать ключ и удалить файл.
- Обрезанные 4-м коленом различаются: `terminal_likeness`, `truncated_candidate` (33 из 444), роль не меняется.
- 7 тестов. Офлайн-архивы пересобраны 2026-09-23 из актуального коммита ветки (с различением обрезанных);
  ключа в архивах нет — `openai_key.txt` копируется в распакованную папку вручную.
- На машине пользователя системного Python нет; для сборки и проверок используется portable-интерпретатор
  (`portable/win/python.exe` после сборки или `C:/Users/User/claude/moneygraph/portable/win/python.exe`).

## Что осталось
1. ~~Проверить ассистента с ключом на ноутбуке~~ — проверено 2026-09-23: `ask` отвечает через `openai:gpt-5-mini`.
2. Репетиция демо по вкладке «Демо».
3. Проверить Linux- и macOS-архивы на реальных машинах (собраны на Windows без запуска).
4. После хакатона: отозвать ключ OpenAI, удалить `openai_key.txt`, ветку `offline-bundles` и релиз `offline-bundles`.
