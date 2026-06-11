# MD Reader

[![CI](https://github.com/gramotun-droid/markdown_reader/actions/workflows/ci.yml/badge.svg)](https://github.com/gramotun-droid/markdown_reader/actions/workflows/ci.yml)

MD Reader - простой Windows-просмотрщик Markdown-файлов и локальных файловых wiki.

Приложение не является редактором. Основной сценарий: открыть `.md` или папку с Markdown-документами, читать отрендеренный HTML, переходить по относительным ссылкам и искать по текущей странице.

## Скачать (Windows)

Готовую сборку под Windows собирает GitHub Actions. На выходе два варианта:

- **`MdReader-Setup.exe`** — лёгкий установщик (Inno Setup): ставит приложение, создаёт ярлык в меню «Пуск» и uninstaller. Рекомендуемый способ.
- **`MdReader-windows.zip`** — портативная сборка: распакуйте и запустите `MdReader.exe` (рядом должна лежать папка `_internal` — это обычная PyInstaller-сборка «одной папкой»).

Где скачать:

- **Последняя сборка из `main`:** вкладка [Actions](https://github.com/gramotun-droid/markdown_reader/actions/workflows/ci.yml) → последний успешный запуск → раздел **Artifacts** → `MdReader-windows`.
- **Релизы по версиям:** запушьте тег `vX.Y.Z` (`git tag v1.0.0 && git push origin v1.0.0`) — workflow соберёт установщик и портативный архив и приложит их к [Releases](https://github.com/gramotun-droid/markdown_reader/releases).

## Возможности

- Открытие `.md` и `.markdown` файлов.
- Открытие папки как wiki с деревом файлов слева.
- Рендер Markdown в HTML через `markdown-it-py`.
- Таблицы, списки, blockquote, inline code, fenced code blocks, task lists.
- Подсветка кода через Pygments (палитра следует теме интерфейса).
- Автоматическое оглавление (TOC) и якоря заголовков с рабочими `#fragment`-ссылками.
- Относительные изображения через `baseUrl`.
- Относительные ссылки на Markdown-файлы открываются внутри приложения.
- Внешние `http` и `https` ссылки открываются в системном браузере.
- Светлая и тёмная темы с переключением в интерфейсе (`Ctrl+Shift+D`).
- Режим редактирования: правка Markdown с live-предпросмотром, пошаговые
  отмена/повтор, кнопки «Сохранить» и «Отменить».
- Автоперезагрузка просмотра при изменении файла на диске.
- Список недавних файлов и навигация назад/вперёд по истории.
- Поиск по текущему документу (`Ctrl+F`) и полнотекстовый поиск по папке (`Ctrl+Shift+F`).
- Масштабирование через `Ctrl++`, `Ctrl+-`, `Ctrl+0`.
- Все действия доступны через меню (**Файл / Вид / Поиск / Справка**) и контекстное меню значка в трее — отдельной панели инструментов нет.
- Меню **Файл → Диски**: открытие локальных и сетевых дисков, а также подключённых дистрибутивов **WSL**.
- Иконка приложения в углу окна, на панели задач и в системном трее.
- Запуск из консоли командой `mdreader` с аргументом файла или папки.
- Сборка `.exe` через PyInstaller.
- Автообновление: приложение проверяет новые релизы на GitHub и устанавливает их в фоне с прогрессом, без лишних вопросов.

## Обновления

При запуске приложение проверяет последний релиз на GitHub. Если доступна новая
версия, установщик скачивается в фоне (прогресс в статусной строке), запускается
в тихом режиме и приложение перезапускается уже обновлённым — подтверждать ничего
не нужно. Ручная проверка — меню **Справка → Проверить обновления** или тот же
пункт в меню значка в трее. Автопроверку при старте можно отключить настройкой
`check_updates_on_start`. Самоустановка работает только в собранной под Windows
версии; при запуске из исходников кнопка открывает страницу релизов в браузере.

## Структура

```text
md-reader/
├─ app/
│  ├─ main.py          # точка входа + разбор аргументов CLI
│  ├─ window.py        # главное окно, меню, режимы просмотра/правки
│  ├─ editor.py        # редактор Markdown с подсветкой синтаксиса
│  ├─ renderer.py      # Markdown → HTML, TOC, Pygments
│  ├─ web_page.py      # перехват кликов по ссылкам
│  ├─ folder_search.py # полнотекстовый поиск по папке
│  ├─ icon.py          # сборка иконки приложения из логотипа
│  ├─ settings.py      # QSettings: путь, масштаб, тема, недавние файлы
│  ├─ assets/
│  │  ├─ style-light.css
│  │  ├─ style-dark.css
│  │  ├─ logo.svg
│  │  └─ app.ico
│  └─ templates/
│     └─ page.html
├─ tests/
│  ├─ test_renderer.py
│  ├─ test_folder_search.py
│  └─ test_settings.py
├─ tools/
│  └─ make_icon.py     # регенерация app.ico из logo.svg
├─ .github/workflows/ci.yml
├─ requirements.txt
├─ pyproject.toml
├─ build.bat
├─ README.md
└─ mdreader.spec
```

## Установка для разработки

Требуется Python 3.11+.

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Либо установка как пакета (даёт консольную команду `mdreader` и dev-инструменты):

```bat
python -m pip install -e .[dev]
```

## Запуск

Пустое окно:

```bat
python -m app.main
```

Открыть файл:

```bat
python -m app.main C:\docs\README.md
```

Открыть папку wiki:

```bat
python -m app.main C:\docs\wiki
```

Можно открыть папку из WSL через Windows UNC-путь:

```bat
python -m app.main \\wsl.localhost\Ubuntu\root\projects\dev\site_main
```

Сборку `.exe` для Windows запускайте из Windows-окружения, а не из WSL.

Также можно запускать точку входа напрямую:

```bat
python app\main.py C:\docs\README.md
```

### Команда `mdreader`

После `pip install -e .` доступна консольная команда — открыть файл в окне можно прямо из терминала:

```bat
mdreader C:\docs\README.md
mdreader C:\docs\wiki
mdreader --theme dark C:\docs\README.md
mdreader --version
```

## Сборка EXE

На Windows:

```bat
build.bat
```

Или вручную:

```bat
pyinstaller mdreader.spec
```

Результат сборки:

```text
dist\MdReader\MdReader.exe
```

Важно: не запускайте `build\mdreader\MdReader.exe`. Это промежуточный файл PyInstaller, он не содержит рядом нужный каталог `_internal` и может показать ошибку вида:

```text
Failed to load Python DLL ...\build\mdreader\_internal\python314.dll
```

Запускать нужно только финальный файл:

```bat
dist\MdReader\MdReader.exe
```

Если ошибка появилась после старой сборки, удалите `build` и `dist`, затем запустите `build.bat` заново.

## Горячие клавиши

- `Ctrl+O` - открыть файл.
- `Ctrl+Shift+O` - открыть папку.
- `Ctrl+E` - редактировать текущий файл.
- `Ctrl+F` - поиск по странице.
- `Ctrl+Shift+F` - поиск по папке.
- `Ctrl+R` - обновить текущий документ.
- `Ctrl+Shift+D` - переключить тему.
- `Alt+←` / `Alt+→` - назад / вперёд по истории.
- `Ctrl++` - увеличить масштаб.
- `Ctrl+-` - уменьшить масштаб.
- `Ctrl+0` - сбросить масштаб.
- `Esc` - закрыть панель поиска.

В режиме редактирования: `Ctrl+S` - сохранить, `Ctrl+Z` / `Ctrl+Shift+Z` - отменить / повторить шаг.

## Режим редактирования

Кнопка «Редактировать» (`Ctrl+E`) открывает текущий файл в редакторе с
подсветкой Markdown и live-предпросмотром справа. Доступны пошаговые
отмена/повтор. Кнопка «Сохранить» перезаписывает файл и обновляет окно
просмотра, «Отменить» закрывает редактор без сохранения.

## Архитектура

- `app/main.py` разбирает аргументы CLI, создаёт `QApplication`, открывает окно и применяет тему.
- `app/window.py` содержит главное окно: меню, дерево wiki, режимы просмотра/правки, историю, трей.
- `app/drives.py` перечисляет доступные корни: локальные и сетевые диски, дистрибутивы WSL.
- `app/editor.py` — редактор Markdown (`QPlainTextEdit`) с подсветкой синтаксиса и панелью действий.
- `app/renderer.py` преобразует Markdown в HTML, строит оглавление, подключает CSS, шаблон и Pygments по теме.
- `app/folder_search.py` — независимая от Qt функция полнотекстового поиска по дереву папки.
- `app/web_page.py` перехватывает клики по ссылкам: Markdown-файлы открываются внутри viewer, внешние ссылки - в браузере.
- `app/icon.py` собирает иконку приложения из `logo.svg`.
- `app/settings.py` хранит последний путь, масштаб, тему и недавние файлы через `QSettings`.

## Иконка

Логотип задаётся в `app/assets/logo.svg`. Иконка окна и трея рендерится из него
на лету. Для exe-сборки `.ico` регенерируется из логотипа:

```bat
python tools\make_icon.py
```

## Тесты

```bat
pytest -q
```

Тесты рендера, поиска и настроек не требуют Qt и проходят без `PySide6`.

## Известные ограничения

- Mermaid, MathJax и экспорт PDF не реализованы.
- `app.ico` является минимальной технической иконкой; для branded-сборки стоит заменить её полноценной дизайнерской `.ico`.
