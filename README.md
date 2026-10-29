# MAXIMUM Education — автоматизация входа и домашних заданий

Проект содержит две версии скрипта:

| Папка | ОС | Браузер |
| :--- | :--- | :--- |
| `windows_chrome` | Windows | Google Chrome |
| `mac` | macOS | Google Chrome |

Скрипт входит в аккаунты по очереди, открывает выбранные уроки и решает задания. Капчу нужно проходить вручную.

---

## Что нужно

- Python 3.11 или новее
- Google Chrome
- Аккаунты Leader-ID в `config.json`

---

## Windows

```powershell
cd "C:\путь\к\script\windows_chrome"
..\.venv\Scripts\python.exe -m pip install -r requirements.txt
..\.venv\Scripts\python.exe quick_login.py
```

Если виртуальное окружение создаётся заново:

```powershell
cd "C:\путь\к\script\windows_chrome"
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe quick_login.py
```

---

## macOS

```bash
cd ~/путь/к/script/mac
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python quick_login.py
```

Профили браузера хранятся здесь:

```text
~/Library/Application Support/LeaderIdMultiLogin/profiles
```

Если используется Yandex Browser, укажи путь в `mac/config.json`:

```json
"browser_binary": "/Applications/Yandex.app/Contents/MacOS/Yandex"
```

---

## Настройка config.json

Аккаунты:

```json
"accounts": [
  {
    "name": "Аккаунт 1",
    "email": "mail@example.com",
    "password": "пароль",
    "profile": "account1",
    "enabled": true
  }
]
```

У каждого аккаунта должен быть свой `profile`.

Выбор уроков — вставляй ссылки на уроки или задания:

```json
"homework": {
  "enabled": true,
  "auto_discover": true,
  "lessons": [
    "https://education.maximumtest.ru/lesson/4916303/subjects/65728/practice/kbs/14293/tests/338793?backPage=/student/courses/113493/lessons&type=online"
  ],
  "submit": true,
  "skip_completed": true,
  "timeout": 45,
  "submit_timeout": 40
}
```

Можно указать несколько ссылок списком. Скрипт сам извлечёт `lesson`, `subject`, `kb` и `course`.

Полезные параметры:

| Параметр | Значение |
| :--- | :--- |
| `submit` | `true` — отправлять ответы, `false` — только заполнить |
| `skip_completed` | пропускать уже выполненные задания |
| `task_pause` | пауза между заданиями в секундах |
| `headless` | `true` — браузер без окна |

---

## Первый запуск

Если сессии ещё нет или она истекла:

```powershell
# Windows
..\.venv\Scripts\python.exe setup_sessions.py
```

```bash
# macOS
python setup_sessions.py
```

При появлении капчи решите её вручную в открытом окне браузера. После успешного входа сессия сохранится в профиле.

Затем обычный запуск:

```powershell
# Windows
..\.venv\Scripts\python.exe quick_login.py
```

```bash
# macOS
python quick_login.py
```

---

## Ошибка 403

Ошибка 403 означает, что платформа отклонила запрос. Чаще всего:

- истекла сессия или куки;
- у аккаунта нет доступа к этому курсу или уроку;
- ссылка взята от другого аккаунта;
- слишком частые запросы или сработала защита платформы.

Что делать:

1. Перезайдите через `setup_sessions.py`.
2. Проверьте ссылку вручную в браузере этого аккаунта.
3. Увеличьте `task_pause`.
4. Запускайте аккаунты по одному.
5. Перезапустите скрипт — задания с ошибкой будут пропущены, попытки не тратятся.

---

## Ограничения

- Капчу скрипт не решает.
- Пароли хранятся в `config.json` в открытом виде.
- Не запускайте два окна с одним профилем одновременно.
- Не передавайте папку с `config.json` другим людям.
