# Офлайн-архивы «Граф денег»

Проект + портативный Python 3.11.16 со всеми библиотеками. Установка Python и интернет не нужны (кроме macOS: см. ниже).
Код и инструкция — в ветке `beketkz` (README, раздел «Установка и запуск»).
Собрано из коммита `ff2943bb017a146c309c31551d3d0f138a63906a` скриптом `tools/build_portable_win.sh`. Контрольные суммы — `SHA256SUMS`, версии пакетов — `BUILD_INFO.txt`.

**Целые архивы одним файлом** — в [GitHub Release `offline-bundles`](https://github.com/BAITC-Hacks/hack-d4a071e9-mydream/releases/tag/offline-bundles). Это основной способ скачать.
Здесь те же архивы частями по 25 МБ (лимит файла в git — 100 МБ) на случай, если релиз недоступен.

Ключа OpenAI в архивах нет: для ассистента через модель скопируйте `openai_key.txt` из ветки `beketkz` в распакованную папку `moneygraph`.

## Windows x64 (7 частей)
1. Скачать все `moneygraph-win-x64.zip.part00`…`part06`, `SHA256SUMS` и `join_win.bat` в одну папку
   (или склонировать только эту ветку: `git clone --single-branch -b offline-bundles https://github.com/BAITC-Hacks/hack-d4a071e9-mydream`).
2. Запустить `join_win.bat` — хэш из certutil должен совпасть со строкой в SHA256SUMS.
3. Распаковать **через tar**, не Проводником: `tar -xf moneygraph-win-x64.zip -C C:\mg`
4. `cd /d C:\mg\moneygraph` → `run_offline.bat run | test | explain <gid> | app`

## Linux x64 (8 частей)
```bash
bash join_linux.sh                       # склеит части и проверит SHA256
tar -xzf moneygraph-linux-x64.tar.gz && cd moneygraph && ./run_offline.sh run
```

## macOS (Apple Silicon и Intel) — нужен интернет при первом запуске
`moneygraph-macos.tar.gz` лежит здесь целиком (≈1 МБ): интерпретатора внутри нет, `run_mac.sh` скачает портативный Python 3.11 и библиотеки из PyPI при первом запуске.
```bash
tar -xzf moneygraph-macos.tar.gz && cd moneygraph && ./run_mac.sh run
```
