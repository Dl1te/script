# macOS — запуск

```bash
cd path/to/script/mac
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python quick_login.py
```

Первый запуск или истекла сессия:

```bash
python setup_sessions.py
```

Капчу нужно решить вручную в открытом окне Chrome.

Профили:

```text
~/Library/Application Support/LeaderIdMultiLogin/profiles
```

Выбор уроков в `config.json`:

```json
"lessons": [
  "https://education.maximumtest.ru/lesson/4916303/subjects/65728/practice/kbs/14293/tests/338793?backPage=/student/courses/113493/lessons&type=online"
]
```

Можно вставить несколько ссылок списком.

Если нужен Yandex Browser:

```json
"browser_binary": "/Applications/Yandex.app/Contents/MacOS/Yandex"
```

Ошибка 403: перезайдите через `setup_sessions.py`, проверьте доступ к уроку и увеличьте `task_pause`.
