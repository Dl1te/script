from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

from selenium.common.exceptions import (
    NoAlertPresentException,
    TimeoutException,
    UnexpectedAlertPresentException,
    WebDriverException,
)

BASE_URL = "https://education.maximumtest.ru"
ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"

DEFAULTS: dict[str, Any] = {
    "enabled": True,
    "auto_discover": True,
    "course": 113493,
    "lesson": 4916426,
    "submit": True,
    "skip_completed": True,
    "timeout": 45,
    "submit_timeout": 40,
    "task_pause": 0.4,
}

PRACTICE_LINK_RE = re.compile(
    r"/lesson/(?P<lesson>\d+)/subjects/(?P<subject>\d+)/practice/kbs"
)
TEST_URL_RE = re.compile(
    r"/lesson/(?P<lesson>\d+)/subjects/(?P<subject>\d+)"
    r"/practice/kbs/(?P<kb>\d+)/tests/(?P<test>\d+)"
)



WebDriverLike = Any


class HomeworkError(RuntimeError):
    pass


class NotEnrolledError(HomeworkError):
    pass


class AccessDeniedError(HomeworkError):
    pass


def log(name: str, message: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] [{name}] {message}", flush=True)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return default


def _normalize(value: Any) -> str:
    return " ".join(str(value or "").split())


def _int_setting(raw: dict[str, Any], key: str, default: int) -> int:
    value = _to_int(raw.get(key), 0)
    return value if value > 0 else default


def parse_lesson_link(value: Any, default_course: int) -> dict[str, Any] | None:
    text = str(value or "").strip()
    if not text:
        return None
    match = TEST_URL_RE.search(text) or PRACTICE_LINK_RE.search(text)
    if match:
        lesson = _to_int(match.groupdict().get("lesson"), 0)
        subject = _to_int(match.groupdict().get("subject"), 0)
        kb = _to_int(match.groupdict().get("kb"), 0)
    else:
        lesson_match = re.search(r"/lesson/(\d+)", text)
        if not lesson_match:
            return None
        lesson = _to_int(lesson_match.group(1), 0)
        subject = 0
        kb = 0
    course_match = re.search(r"/student/courses/(\d+)", text)
    course = _to_int(course_match.group(1), 0) if course_match else default_course
    if lesson <= 0:
        return None
    return {
        "lesson": lesson,
        "subject": subject,
        "kb": kb,
        "course": course,
        "url": text,
    }


def homework_settings(cfg: dict[str, Any]) -> dict[str, Any]:
    raw = cfg.get("homework")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        log("config", "Поле homework должно быть объектом JSON; использую значения по умолчанию.")
        raw = {}

    merged = {**DEFAULTS, **raw}
    if not merged.get("enabled", True):
        return {}

    course = _int_setting(merged, "course", 0)
    if course <= 0:
        log("config", "В homework не задан course; домашка отключена.")
        return {}

    lesson_ids: list[int] = []
    link_items: list[dict[str, Any]] = []
    raw_lessons = merged.get("lessons")
    if isinstance(raw_lessons, list):
        for value in raw_lessons:
            text = str(value or "").strip()
            if text.startswith(("http://", "https://")) or "/lesson/" in text:
                parsed = parse_lesson_link(text, course)
                if parsed is None:
                    log("config", f"Не удалось разобрать ссылку урока: {text}")
                    continue
                link_items.append(parsed)
                if parsed["lesson"] not in lesson_ids:
                    lesson_ids.append(parsed["lesson"])
                continue
            lesson_id = _to_int(text, 0)
            if lesson_id > 0 and lesson_id not in lesson_ids:
                lesson_ids.append(lesson_id)
    lesson = lesson_ids[0] if len(lesson_ids) == 1 else 0

    items: list[dict[str, Any]] = []
    raw_items = merged.get("items")
    if isinstance(raw_items, list):
        for index, item in enumerate(raw_items, start=1):
            if not isinstance(item, dict):
                continue
            subject = _int_setting(item, "subject", 0)
            kb = _int_setting(item, "kb", 0)
            if subject <= 0 or kb <= 0:
                continue
            items.append(
                {
                    "name": str(item.get("name") or f"Домашка {index}"),
                    "course": _int_setting(item, "course", course),
                    "lesson": _int_setting(item, "lesson", lesson),
                    "subject": subject,
                    "kb": kb,
                    "url": "",
                    "total": None,
                    "solved": None,
                }
            )

    for link in link_items:
        items.append(
            {
                "name": f"Урок {link['lesson']}",
                "course": link["course"],
                "lesson": link["lesson"],
                "subject": link["subject"],
                "kb": link["kb"],
                "url": link["url"],
                "total": None,
                "solved": None,
            }
        )

    if not items:
        subject = _int_setting(merged, "subject", 0)
        kb = _int_setting(merged, "kb", 0)
        if subject > 0 and kb > 0:
            items.append(
                {
                    "name": "Домашка",
                    "course": course,
                    "lesson": lesson,
                    "subject": subject,
                    "kb": kb,
                    "url": "",
                    "total": None,
                    "solved": None,
                }
            )

    auto_discover = bool(merged.get("auto_discover", True))
    if not items and not auto_discover:
        log("config", "В homework нет ни auto_discover, ни items; домашка отключена.")
        return {}

    return {
        "enabled": True,
        "auto_discover": auto_discover,
        "course": course,
        "lesson": lesson,
        "lesson_ids": lesson_ids,
        "submit": bool(merged.get("submit", True)),
        "skip_completed": bool(merged.get("skip_completed", True)),
        "timeout": max(10, _to_int(merged.get("timeout"), 45)),
        "submit_timeout": max(10, _to_int(merged.get("submit_timeout"), 40)),
        "task_pause": max(0.0, _to_float(merged.get("task_pause"), 0.4)),
        "items": items,
    }






def _api_fetch(
    driver: WebDriverLike,
    method: str,
    path: str,
    body: Any = None,
    timeout_ms: int = 20000,
) -> Any:
    result = driver.execute_async_script(
        """
        const method = arguments[0];
        const path = arguments[1];
        const body = arguments[2];
        const timeoutMs = arguments[3];
        const done = arguments[4];
        const timer = setTimeout(() => done({ok: false, error: 'таймаут запроса'}), timeoutMs);
        const options = {
          method: method,
          credentials: 'same-origin',
          headers: { 'Accept': 'application/json' }
        };
        if (body !== null && body !== undefined) {
          options.headers['Content-Type'] = 'application/json';
          options.body = JSON.stringify(body);
        }
        fetch(path, options)
          .then(async (response) => {
            clearTimeout(timer);
            if (!response.ok) throw new Error('HTTP ' + response.status);
            return await response.json();
          })
          .then((data) => done({ok: true, data}))
          .catch((error) => {
            clearTimeout(timer);
            done({ok: false, error: String((error && error.message) || error)});
          });
        """,
        method,
        path,
        body,
        timeout_ms,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        error = (result or {}).get("error") if isinstance(result, dict) else result
        raise HomeworkError(f"API {method} {path}: {error}")
    return result.get("data")


def fetch_tests(driver: WebDriverLike, subject_id: int, kb_id: int) -> list[dict[str, Any]]:
    try:
        driver.set_script_timeout(30)
    except WebDriverException:
        pass
    data = _api_fetch(
        driver,
        "GET",
        f"/api/v1/content/practice/curriculumsubject/{subject_id}"
        f"/knowledgebase/{kb_id}/online/tests",
        timeout_ms=25000,
    )
    if not isinstance(data, list):
        raise HomeworkError(f"API заданий вернул не массив: {type(data).__name__}")
    return data


def fetch_api_result(
    driver: WebDriverLike, subject_id: int, kb_id: int, test_id: int | str
) -> dict[str, Any] | None:
    for item in fetch_tests(driver, subject_id, kb_id):
        if str(item.get("id")) == str(test_id):
            result = item.get("studentTestResult")
            return result if isinstance(result, dict) else None
    return None






def _is_right_answer(item: dict[str, Any]) -> bool:
    value = item.get("isRightAnswer", True)
    if value is False or value == 0:
        return False
    if isinstance(value, str) and value.strip().lower() in {"false", "0", "no", "нет"}:
        return False
    return True


def extract_answer_items(test: dict[str, Any]) -> list[dict[str, Any]]:
    raw = test.get("educationTestAnswers")
    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict):
        items = [raw]
    else:
        items = []

    correct = [
        item
        for item in items
        if isinstance(item, dict) and item.get("variants") and _is_right_answer(item)
    ]
    correct.sort(key=lambda item: _to_int(item.get("sort"), 0))

    result: list[dict[str, Any]] = []
    for item in correct:
        variants = item.get("variants")
        if isinstance(variants, list) and variants:
            text = str(variants[0])
        elif variants is not None:
            text = str(variants)
        else:
            continue
        result.append(
            {
                "id": str(item.get("id") or "").strip(),
                "text": text,
            }
        )
    return result


def extract_answers(test: dict[str, Any]) -> list[str]:
    return [item["text"] for item in extract_answer_items(test)]


def make_test_url(settings: dict[str, Any], test_id: int | str) -> str:
    back_page = quote(f"/student/courses/{settings['course']}/lessons", safe="/")
    return (
        f"{BASE_URL}/lesson/{settings['lesson']}/subjects/{settings['subject']}"
        f"/practice/kbs/{settings['kb']}/tests/{test_id}"
        f"?backPage={back_page}&type=online"
    )






def _accept_alert(driver: WebDriverLike, account_name: str) -> bool:
    try:
        alert = driver.switch_to.alert
        text = (alert.text or "").strip()
        alert.accept()
        if text:
            log(account_name, f"Закрыл диалог браузера: {text[:120]}")
        return True
    except (NoAlertPresentException, WebDriverException):
        return False


def navigate(
    driver: WebDriverLike, url: str, account_name: str, timeout: int
) -> None:
    for attempt in range(2):
        _accept_alert(driver, account_name)
        try:
            driver.get(url)
            return
        except UnexpectedAlertPresentException:
            _accept_alert(driver, account_name)
            time.sleep(0.5)
        except TimeoutException:
            
            try:
                driver.execute_script("window.stop();")
            except WebDriverException:
                pass
            return
        except WebDriverException as exc:
            message = str(exc).splitlines()[0]
            if attempt == 0:
                log(account_name, f"Повторяю переход после ошибки: {message}")
                time.sleep(1.0)
                continue
            raise HomeworkError(f"Не удалось открыть страницу: {message}") from exc


def _wait_for_lesson_items(driver: WebDriverLike, timeout: int) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            count = driver.execute_script(
                "return document.querySelectorAll('.lesson-entity-item').length;"
            )
            if count:
                return True
        except WebDriverException:
            pass
        time.sleep(0.4)
    return False


def discover_practice_links(
    driver: WebDriverLike,
    course: int,
    account_name: str,
    timeout: int,
) -> list[dict[str, Any]]:
    url = f"{BASE_URL}/student/courses/{course}/lessons"
    navigate(driver, url, account_name, timeout)
    if not _wait_for_lesson_items(driver, timeout):
        current = ""
        try:
            current = driver.current_url
        except WebDriverException:
            pass
        if f"/student/courses/{course}/lessons" not in current:
            raise NotEnrolledError(
                f"курс {course} недоступен для аккаунта "
                f"(платформа открыла {current or 'другую страницу'})"
            )
        raise HomeworkError("На странице курса не найдены занятия (.lesson-entity-item)")

    
    for _ in range(40):
        try:
            clicked = driver.execute_script(
                """
                const items = [...document.querySelectorAll('.lesson-entity-item')];
                for (const item of items) {
                  if (item.dataset.mxPracticeTried === '1') continue;
                  if (item.querySelector('a[href*="/practice/kbs"]')) continue;
                  const button = item.querySelector('[role="button"]') || item;
                  item.dataset.mxPracticeTried = '1';
                  button.scrollIntoView({block: 'center'});
                  button.click();
                  return true;
                }
                return false;
                """
            )
        except WebDriverException:
            clicked = False
        if not clicked:
            break
        time.sleep(0.7)

    raw_links = driver.execute_script(
        """
        return [...document.querySelectorAll('a[href*="/practice/kbs"]')].map((a) => ({
          href: a.getAttribute('href') || '',
          text: (a.textContent || '').replace(/\\s+/g, ' ').trim()
        }));
        """
    )
    if not isinstance(raw_links, list):
        return []

    found: dict[int, dict[str, Any]] = {}
    for raw in raw_links:
        if not isinstance(raw, dict):
            continue
        href = str(raw.get("href") or "").strip()
        text = _normalize(raw.get("text"))
        match = PRACTICE_LINK_RE.search(href)
        if not match:
            continue
        subject = int(match.group("subject"))
        lesson = int(match.group("lesson"))
        if subject in found:
            continue

        name_match = re.search(r"<([^>]+)>", text)
        name = name_match.group(1).strip() if name_match else f"Домашка {subject}"
        total_match = re.search(r"Заданий:\s*(\d+)", text)
        solved_match = re.search(r"Решено:\s*(\d+)", text)
        total = _to_int(total_match.group(1), -1) if total_match else None
        solved = _to_int(solved_match.group(1), -1) if solved_match else None

        if href.startswith("/"):
            href = BASE_URL + href

        found[subject] = {
            "name": name,
            "course": course,
            "lesson": lesson,
            "subject": subject,
            "kb": 0,
            "url": href,
            "total": total if total is not None and total >= 0 else None,
            "solved": solved if solved is not None and solved >= 0 else None,
        }

    return list(found.values())


def wait_for_surface(
    driver: WebDriverLike, account_name: str, timeout: int
) -> dict[str, Any]:
    deadline = time.time() + timeout
    last_state: dict[str, Any] | None = None

    while time.time() < deadline:
        _accept_alert(driver, account_name)
        try:
            state = driver.execute_script(
                """
                const visible = (el) => {
                  if (!el) return false;
                  const style = getComputedStyle(el);
                  if (style.display === 'none' || style.visibility === 'hidden') return false;
                  const rect = el.getBoundingClientRect();
                  return rect.width > 0 && rect.height > 0;
                };
                const zones = [...document.querySelectorAll(
                  '.answer-drop-zone, [data-test-id="dragDropInput"]'
                )].filter(visible);
                const fields = [...document.querySelectorAll(
                  'textarea.mx-input__textarea, input.mx-input__input, [contenteditable="true"]'
                )].filter((el) => {
                  if (!visible(el) || el.disabled || el.readOnly) return false;
                  if (el.getAttribute('type') === 'hidden') return false;
                  const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
                  if (placeholder.includes('поиск') || placeholder.includes('search')) return false;
                  return true;
                });
                const choices = [...document.querySelectorAll(
                  'input[type="radio"], input[type="checkbox"]'
                )].filter((el) => {
                  if (el.disabled) return false;
                  if (visible(el)) return true;
                  const label = el.id
                    ? document.querySelector('label[for="' + el.id + '"]')
                    : null;
                  return visible(label);
                });
                return {
                  zones: zones.length,
                  fields: fields.length,
                  choices: choices.length,
                  body: (document.body ? document.body.innerText : '').slice(0, 800)
                };
                """
            )
        except WebDriverException as exc:
            last_state = {"error": str(exc).splitlines()[0]}
            time.sleep(0.5)
            continue

        if state.get("zones") or state.get("fields") or state.get("choices"):
            return state

        text = (state.get("body") or "").lower()
        for marker in (
            "задание недоступно",
            "попытки закончились",
            "нет попыток",
            "страница не найдена",
            "ошибка 404",
        ):
            if marker in text:
                raise HomeworkError(f"Задание недоступно: {marker}")

        last_state = state
        time.sleep(0.3)

    body = (last_state or {}).get("body", "")
    raise HomeworkError(
        f"Не дождался полей/ячеек за {timeout} сек. "
        f"Фрагмент страницы: {body[:200]!r}"
    )


def fill_text_fields(driver: WebDriverLike, answers: list[str]) -> dict[str, Any]:
    result = driver.execute_script(
        """
        const answers = arguments[0].map((value) => String(value));
        const visible = (el) => {
          if (!el) return false;
          const style = getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };
        const fields = [...document.querySelectorAll(
          'textarea.mx-input__textarea, input.mx-input__input, [contenteditable="true"]'
        )]
          .filter((el) => {
            if (!visible(el) || el.disabled || el.readOnly) return false;
            if (el.getAttribute('type') === 'hidden') return false;
            const placeholder = (el.getAttribute('placeholder') || '').toLowerCase();
            if (placeholder.includes('поиск') || placeholder.includes('search')) return false;
            return true;
          })
          .sort((a, b) => {
            const ra = a.getBoundingClientRect();
            const rb = b.getBoundingClientRect();
            return Math.round(ra.top / 12) - Math.round(rb.top / 12) || ra.left - rb.left;
          });

        const setValue = (el, value) => {
          if (el.isContentEditable) {
            el.focus();
            el.textContent = value;
            el.dispatchEvent(new InputEvent('input', {
              bubbles: true,
              inputType: 'insertText',
              data: value
            }));
          } else {
            const proto = el instanceof HTMLTextAreaElement
              ? HTMLTextAreaElement.prototype
              : HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, value);
            el.dispatchEvent(new Event('input', {bubbles: true}));
          }
          el.dispatchEvent(new Event('change', {bubbles: true}));
        };

        const count = Math.min(answers.length, fields.length);
        for (let i = 0; i < count; i += 1) setValue(fields[i], answers[i]);
        if (document.activeElement && document.activeElement.blur) {
          document.activeElement.blur();
        }
        return {filled: count, total: fields.length};
        """,
        answers,
    )
    return result if isinstance(result, dict) else {"filled": 0, "total": 0}


def fill_choices(
    driver: WebDriverLike, answers: list[dict[str, Any]]
) -> dict[str, Any]:
    texts = [str(item.get("text") or "") for item in answers]
    ids = [str(item.get("id") or "") for item in answers]
    result = driver.execute_async_script(
        """
        const texts = arguments[0].map((value) => String(value));
        const ids = arguments[1].map((value) => String(value));
        const done = arguments[2];
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const normalize = (value) => String(value == null ? '' : value)
          .replace(/\\s+/g, ' ')
          .trim();
        const visible = (el) => {
          if (!el) return false;
          const style = getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };

        (async () => {
          const options = [...document.querySelectorAll(
            'input[type="radio"], input[type="checkbox"]'
          )]
            .filter((input) => {
              if (input.disabled) return false;
              if (visible(input)) return true;
              const label = input.id
                ? document.querySelector('label[for="' + input.id + '"]')
                : null;
              return visible(label);
            })
            .map((input) => {
              const label = input.id
                ? document.querySelector('label[for="' + input.id + '"]')
                : null;
              const container = input.closest(
                'li, .m-radio, .m-checkbox, .radio-item, .checkbox-item'
              ) || label || input;
              const textNode = container.querySelector(
                '[data-test-id^="mRadioText"], [data-test-id^="mCheckboxText"], .m-radio__text, .m-checkbox__text'
              );
              return {
                input,
                label,
                value: String(input.value || ''),
                type: input.type,
                text: normalize((textNode || label || container).textContent)
              };
            });

          if (!options.length) throw new Error('Не найдены варианты radio/checkbox');

          const findOption = (text, id) => {
            const expected = normalize(text);
            let found = options.find((option) => option.text === expected);
            if (!found && expected) {
              found = options.find(
                (option) => option.text.includes(expected) || expected.includes(option.text)
              );
            }
            if (!found && id) found = options.find((option) => option.value === id);
            return found;
          };

          const selected = [];
          const missed = [];
          const seen = new Set();
          for (let index = 0; index < texts.length; index += 1) {
            const option = findOption(texts[index], ids[index]);
            if (!option) {
              missed.push(texts[index]);
              continue;
            }
            if (seen.has(option.input)) continue;
            seen.add(option.input);

            option.input.scrollIntoView({block: 'center'});
            await sleep(80);
            if (!option.input.checked) {
              option.input.click();
              await sleep(120);
            }
            if (!option.input.checked && option.label) {
              option.label.click();
              await sleep(120);
            }
            if (!option.input.checked) {
              missed.push(texts[index] + ' (не удалось отметить)');
              continue;
            }
            selected.push(option.text);
            if (option.type === 'radio') break;
          }

          done({
            ok: missed.length === 0,
            selected,
            missed,
            options: options.map((option) => ({text: option.text, value: option.value, type: option.type}))
          });
        })().catch((error) => {
          done({ok: false, error: String((error && error.message) || error)});
        });
        """,
        texts,
        ids,
    )
    if not isinstance(result, dict):
        raise HomeworkError(f"Выбор варианта вернул неожиданный ответ: {result!r}")
    if not result.get("ok"):
        error = result.get("error")
        if error:
            raise HomeworkError(f"Ошибка выбора варианта: {error}")
        raise HomeworkError(
            f"Не удалось выбрать варианты: {result.get('missed')}. "
            f"Доступные: {result.get('options')}"
        )
    return result


def fill_drop_zones(driver: WebDriverLike, answers: list[str]) -> dict[str, Any]:
    result = driver.execute_async_script(
        """
        const rawAnswers = arguments[0].map((value) => String(value));
        const done = arguments[1];
        const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
        const normalize = (value) => String(value == null ? '' : value)
          .replace(/\\s+/g, ' ')
          .trim();
        const visible = (el) => {
          if (!el) return false;
          const style = getComputedStyle(el);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
          const rect = el.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        };

        (async () => {
          const zones = [...document.querySelectorAll(
            '.answer-drop-zone, [data-test-id="dragDropInput"]'
          )]
            .filter(visible)
            .sort((a, b) => {
              const ra = a.getBoundingClientRect();
              const rb = b.getBoundingClientRect();
              return Math.round(ra.top / 12) - Math.round(rb.top / 12) || ra.left - rb.left;
            });

          if (!zones.length) throw new Error('Не найдены ячейки drag-and-drop');
          if (rawAnswers.length < zones.length) {
            throw new Error(
              `Ответов меньше, чем ячеек: ${rawAnswers.length} < ${zones.length}`
            );
          }

          const filled = [];
          let answerIndex = 0;

          for (const zone of zones) {
            const expected = normalize(rawAnswers[answerIndex]);
            const current = normalize(zone.textContent);

            if (current) {
              if (current !== expected) {
                throw new Error(
                  `Ячейка уже заполнена другим ответом: «${current}», ожидался «${expected}»`
                );
              }
              filled.push({answer: expected, skipped: true});
              answerIndex += 1;
              continue;
            }

            const tokens = [...document.querySelectorAll(
              '[data-test-id="dragDropVariant"]'
            )].filter(visible);
            const token = tokens.find((item) => normalize(item.textContent) === expected);
            if (!token) throw new Error(`Не найден токен «${expected}»`);

            token.scrollIntoView({block: 'center'});
            await sleep(80);
            token.click();
            await sleep(180);
            zone.scrollIntoView({block: 'center'});
            await sleep(80);
            zone.click();
            await sleep(260);

            const placed = normalize(zone.textContent);
            if (placed !== expected) {
              throw new Error(
                `Не удалось вставить «${expected}» (получилось «${placed}»)`
              );
            }
            filled.push({answer: expected, skipped: false});
            answerIndex += 1;
          }

          done({ok: true, zones: zones.length, filled: answerIndex, log: filled});
        })().catch((error) => {
          done({ok: false, error: String((error && error.message) || error)});
        });
        """,
        answers,
    )
    if not isinstance(result, dict) or not result.get("ok"):
        error = (result or {}).get("error") if isinstance(result, dict) else result
        raise HomeworkError(f"Ошибка drag-and-drop: {error}")
    return result


def wait_submit_enabled(
    driver: WebDriverLike, account_name: str, timeout: int
) -> None:
    deadline = time.time() + timeout
    last_state: dict[str, Any] | None = None

    while time.time() < deadline:
        _accept_alert(driver, account_name)
        try:
            state = driver.execute_script(
                """
                const normalize = (value) => String(value == null ? '' : value)
                  .replace(/\\s+/g, ' ')
                  .trim();
                const buttons = [...document.querySelectorAll('button, [role="button"]')];
                const button = buttons.find(
                  (el) => normalize(el.textContent).toUpperCase() === 'ОТВЕТИТЬ'
                );
                if (!button) return {found: false};
                return {
                  found: true,
                  disabled: !!button.disabled,
                  aria: button.getAttribute('aria-disabled') || '',
                  text: normalize(button.textContent)
                };
                """
            )
        except WebDriverException as exc:
            last_state = {"error": str(exc).splitlines()[0]}
            time.sleep(0.4)
            continue

        last_state = state
        if (
            state.get("found")
            and not state.get("disabled")
            and str(state.get("aria")).lower() != "true"
        ):
            return
        time.sleep(0.3)

    raise HomeworkError(
        f"Кнопка «ОТВЕТИТЬ» неактивна за {timeout} сек. Состояние: {last_state}"
    )


def click_submit(driver: WebDriverLike, account_name: str) -> None:
    _accept_alert(driver, account_name)
    clicked = driver.execute_script(
        """
        const normalize = (value) => String(value == null ? '' : value)
          .replace(/\\s+/g, ' ')
          .trim();
        const button = [...document.querySelectorAll('button, [role="button"]')]
          .find((el) => normalize(el.textContent).toUpperCase() === 'ОТВЕТИТЬ');
        if (!button) return false;
        button.scrollIntoView({block: 'center'});
        button.click();
        return true;
        """
    )
    if not clicked:
        raise HomeworkError("Кнопка «ОТВЕТИТЬ» не найдена")


def wait_result(
    driver: WebDriverLike,
    settings: dict[str, Any],
    test_id: int | str,
    account_name: str,
    timeout: int,
) -> dict[str, Any] | None:
    deadline = time.time() + timeout
    saw_ui_result = False

    while time.time() < deadline:
        _accept_alert(driver, account_name)
        try:
            result = fetch_api_result(
                driver, settings["subject"], settings["kb"], test_id
            )
        except HomeworkError:
            result = None
        if result:
            return result

        if not saw_ui_result:
            try:
                saw_ui_result = bool(
                    driver.execute_script(
                        "return document.body ? "
                        "document.body.innerText.includes('Набранный балл') : false;"
                    )
                )
            except WebDriverException:
                pass
        time.sleep(1.0)

    return None


def read_ui_result(driver: WebDriverLike) -> dict[str, Any]:
    try:
        text = str(
            driver.execute_script(
                "return document.body ? document.body.innerText : '';"
            )
            or ""
        )
    except WebDriverException:
        return {}

    match = re.search(
        r"Набранный балл\s*([\d.,]+)\s*(?:верно|неверно)?\s*/\s*([\d.,]+)",
        text,
        re.IGNORECASE,
    )
    if not match:
        return {"text": text[:300]}
    return {
        "points": match.group(1).replace(",", "."),
        "max": match.group(2).replace(",", "."),
        "text": text[:300],
    }


def save_error_screenshot(
    driver: WebDriverLike, account_name: str, test_id: int | str
) -> Path | None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe = re.sub(r"[^\w.-]+", "_", account_name).strip("_") or "account"
        path = LOG_DIR / f"homework_{stamp}_{safe}_{test_id}.png"
        driver.save_screenshot(str(path))
        log(account_name, f"Скриншот ошибки: {path}")
        return path
    except Exception:
        return None






def process_test(
    driver: WebDriverLike,
    account_name: str,
    settings: dict[str, Any],
    test: dict[str, Any],
) -> dict[str, Any]:
    test_id = _to_int(test.get("id"), 0)
    title = _normalize(test.get("title"))
    test_type = str(test.get("type") or "").strip()
    max_points = _to_float(test.get("maxPoints"), 1.0)
    existing = test.get("studentTestResult")

    if isinstance(existing, dict) and settings["skip_completed"]:
        points = _to_float(existing.get("points"), 0.0)
        percent = existing.get("percent")
        log(
            account_name,
            f"⏭ Задание {test_id} «{title}» уже выполнено "
            f"({points:g}/{max_points:g}, {percent}%) — пропускаю.",
        )
        return {
            "test_id": test_id,
            "skipped": True,
            "reason": "already_done",
            "points": points,
            "max": max_points,
            "percent": percent,
        }

    attempts = _to_int(test.get("attemptsCountLeft"), 0)
    if attempts <= 0 and not existing:
        log(
            account_name,
            f"⏭ Задание {test_id} «{title}»: попытки закончились — пропускаю.",
        )
        return {
            "test_id": test_id,
            "skipped": True,
            "reason": "no_attempts",
            "max": max_points,
        }

    answer_items = extract_answer_items(test)
    answers = [item["text"] for item in answer_items]
    if not answers:
        log(
            account_name,
            f"⏭ Задание {test_id} «{title}»: в API нет правильных ответов — пропускаю.",
        )
        return {
            "test_id": test_id,
            "skipped": True,
            "reason": "no_answers",
            "max": max_points,
        }

    log(
        account_name,
        f"▶ Задание {test_id} «{title}» ({test_type}), "
        f"ответов: {len(answers)}, попыток: {attempts}",
    )

    url = make_test_url(settings, test_id)
    navigate(driver, url, account_name, settings["timeout"])
    try:
        current = driver.current_url
    except WebDriverException:
        current = ""
    if "/lesson/" not in current:
        raise AccessDeniedError(
            f"задание {test_id} недоступно, платформа открыла {current or 'другую страницу'}"
        )
    surface = wait_for_surface(driver, account_name, settings["timeout"])

    if surface.get("zones"):
        result = fill_drop_zones(driver, answers)
        log(
            account_name,
            f"  Заполнено ячеек: {result.get('filled')}/{result.get('zones')}",
        )
    elif surface.get("choices"):
        result = fill_choices(driver, answer_items)
        log(
            account_name,
            f"  Выбрано вариантов: {len(result.get('selected') or [])}"
            f"/{len(answer_items)}",
        )
    else:
        result = fill_text_fields(driver, answers)
        filled = _to_int(result.get("filled"), 0)
        total = _to_int(result.get("total"), 0)
        log(account_name, f"  Заполнено полей: {filled}/{total}")
        if filled < len(answers):
            log(
                account_name,
                f"  ⚠ Ответов больше, чем полей: {len(answers)} > {filled}",
            )

    if settings["task_pause"]:
        time.sleep(settings["task_pause"])

    if not settings["submit"]:
        log(account_name, "  Отправка отключена в config.json.")
        return {
            "test_id": test_id,
            "skipped": False,
            "submitted": False,
            "max": max_points,
        }

    wait_submit_enabled(driver, account_name, settings["submit_timeout"])
    click_submit(driver, account_name)
    log(account_name, "  Нажал «ОТВЕТИТЬ», жду результат...")

    api_result = wait_result(
        driver, settings, test_id, account_name, settings["submit_timeout"]
    )
    if api_result:
        points = _to_float(api_result.get("points"), 0.0)
        percent = api_result.get("percent")
        log(account_name, f"  ✅ Результат: {points:g}/{max_points:g} ({percent}%)")
        return {
            "test_id": test_id,
            "skipped": False,
            "submitted": True,
            "points": points,
            "max": max_points,
            "percent": percent,
            "api": api_result,
        }

    ui = read_ui_result(driver)
    if ui.get("points") is not None:
        points = _to_float(ui.get("points"), 0.0)
        max_value = _to_float(ui.get("max"), max_points)
        log(
            account_name,
            f"  ✅ Результат (со страницы): {points:g}/{max_value:g}",
        )
        return {
            "test_id": test_id,
            "skipped": False,
            "submitted": True,
            "points": points,
            "max": max_value,
            "percent": None,
            "ui": ui,
        }

    log(account_name, "  ⚠ Ответ отправлен, но результат не удалось прочитать.")
    return {
        "test_id": test_id,
        "skipped": False,
        "submitted": True,
        "points": None,
        "max": max_points,
        "percent": None,
        "ui": ui,
    }


def _discover_kb(
    driver: WebDriverLike,
    item: dict[str, Any],
    account_name: str,
    timeout: int,
) -> tuple[int, int, int, int | None]:
    navigate(driver, item["url"], account_name, timeout)
    deadline = time.time() + timeout
    last_url = ""

    while time.time() < deadline:
        try:
            last_url = driver.current_url
        except WebDriverException:
            last_url = ""

        match = TEST_URL_RE.search(last_url)
        if match:
            return (
                int(match.group("lesson")),
                int(match.group("subject")),
                int(match.group("kb")),
                int(match.group("test")),
            )

        
        kb_match = re.search(r"/practice/kbs/(\d+)", last_url)
        if kb_match:
            try:
                first_test = driver.execute_script(
                    """
                    const a = [...document.querySelectorAll('a')].find((el) =>
                      /\\/tests\\/\\d+/.test(el.getAttribute('href') || '')
                    );
                    return a ? a.href : '';
                    """
                )
            except WebDriverException:
                first_test = ""
            if first_test:
                test_match = TEST_URL_RE.search(str(first_test))
                if test_match:
                    return (
                        int(test_match.group("lesson")),
                        int(test_match.group("subject")),
                        int(test_match.group("kb")),
                        int(test_match.group("test")),
                    )
            return (
                item.get("lesson", 0),
                item.get("subject", 0),
                int(kb_match.group(1)),
                None,
            )

        time.sleep(0.5)

    raise HomeworkError(
        f"Не удалось определить kb для «{item.get('name')}». URL: {last_url}"
    )


def run_one_homework(
    driver: WebDriverLike,
    account_name: str,
    settings: dict[str, Any],
    item: dict[str, Any],
    number: int,
    total_items: int,
) -> dict[str, Any]:
    subject = _to_int(item.get("subject"), 0)
    lesson = _to_int(item.get("lesson"), 0)
    kb = _to_int(item.get("kb"), 0)
    total_on_page = item.get("total")
    solved_on_page = item.get("solved")

    log(
        account_name,
        f"Домашка {number}/{total_items}: «{item.get('name')}» "
        f"(subject={subject})",
    )

    if (
        isinstance(total_on_page, int)
        and isinstance(solved_on_page, int)
        and total_on_page > 0
        and solved_on_page >= total_on_page
    ):
        log(
            account_name,
            f"  ⏭ По данным страницы все задания уже выполнены "
            f"({solved_on_page}/{total_on_page}) — пропускаю.",
        )
        return {
            "name": item.get("name"),
            "subject": subject,
            "lesson": lesson,
            "kb": kb,
            "total": total_on_page,
            "already_done": total_on_page,
            "solved_now": 0,
            "skipped": 0,
            "errors": [],
            "points": 0.0,
            "max_points": 0.0,
            "percent": None,
            "note": "все задания уже выполнены",
        }

    if not kb and item.get("url"):
        lesson, subject, kb, _first_test = _discover_kb(
            driver, item, account_name, settings["timeout"]
        )
        log(account_name, f"  Определил параметры: lesson={lesson}, kb={kb}")

    if subject <= 0 or kb <= 0:
        raise HomeworkError(
            f"Не заданы subject/kb для «{item.get('name')}» и не удалось их определить"
        )
    if lesson <= 0:
        lesson = settings["lesson"]
    if lesson <= 0:
        raise HomeworkError(f"Не задан lesson для «{item.get('name')}»")

    test_settings = {
        **settings,
        "course": _to_int(item.get("course"), settings["course"]),
        "lesson": lesson,
        "subject": subject,
        "kb": kb,
    }

    tests = fetch_tests(driver, subject, kb)
    tests.sort(key=lambda test: _to_int(test.get("positionInFile"), 0))

    summary: dict[str, Any] = {
        "name": item.get("name"),
        "subject": subject,
        "lesson": lesson,
        "kb": kb,
        "total": len(tests),
        "already_done": 0,
        "solved_now": 0,
        "skipped": 0,
        "errors": [],
        "points": 0.0,
        "max_points": 0.0,
        "percent": None,
    }

    if not tests:
        log(account_name, "  В этой домашке нет заданий.")
        return summary

    already = sum(
        1 for test in tests if isinstance(test.get("studentTestResult"), dict)
    )
    log(
        account_name,
        f"  Заданий: {len(tests)}, уже выполнено: {already}, "
        f"осталось: {len(tests) - already}",
    )

    for index, test in enumerate(tests, start=1):
        test_id = _to_int(test.get("id"), 0)
        log(account_name, f"  [{index}/{len(tests)}]")
        try:
            result = process_test(driver, account_name, test_settings, test)
        except Exception as exc:
            log(
                account_name,
                f"  ❌ Задание {test_id}: {type(exc).__name__}: {exc}",
            )
            save_error_screenshot(driver, account_name, test_id)
            summary["errors"].append(
                {"test_id": test_id, "error": f"{type(exc).__name__}: {exc}"}
            )
            continue

        if result.get("skipped"):
            if result.get("reason") == "already_done":
                summary["already_done"] += 1
            else:
                summary["skipped"] += 1
        elif result.get("submitted"):
            summary["solved_now"] += 1

    
    try:
        final_tests = fetch_tests(driver, subject, kb)
        for test in final_tests:
            summary["max_points"] += _to_float(test.get("maxPoints"), 1.0)
            result = test.get("studentTestResult")
            if isinstance(result, dict):
                summary["points"] += _to_float(result.get("points"), 0.0)
        if summary["max_points"]:
            summary["percent"] = round(
                summary["points"] / summary["max_points"] * 100, 1
            )
    except Exception as exc:
        log(account_name, f"  Не удалось пересчитать итог по API: {exc}")

    log(account_name, "  " + "─" * 46)
    log(
        account_name,
        f"  ИТОГО: уже было {summary['already_done']}, "
        f"решено сейчас {summary['solved_now']}, "
        f"пропущено {summary['skipped']}, "
        f"ошибок {len(summary['errors'])}",
    )
    if summary["max_points"]:
        log(
            account_name,
            f"  Баллы: {summary['points']:g}/{summary['max_points']:g} "
            f"({summary['percent']}%)",
        )
    log(account_name, "  " + "─" * 46)
    return summary


def run_homework(
    driver: WebDriverLike, account: Any, cfg: dict[str, Any]
) -> dict[str, Any]:
    settings = homework_settings(cfg)
    summary: dict[str, Any] = {
        "account": getattr(account, "name", str(account)),
        "enabled": bool(settings),
        "homeworks": [],
        "total": 0,
        "already_done": 0,
        "solved_now": 0,
        "skipped": 0,
        "errors": [],
        "points": 0.0,
        "max_points": 0.0,
        "percent": None,
    }
    if not settings:
        log(summary["account"], "Домашка отключена в config.json.")
        return summary

    account_name = summary["account"]
    items: list[dict[str, Any]] = []

    lesson_ids = {
        _to_int(lesson_id, 0) for lesson_id in (settings.get("lesson_ids") or [])
    }
    lesson_ids.discard(0)
    has_explicit_selected = any(
        _to_int(item.get("lesson"), 0) in lesson_ids
        for item in settings["items"]
    ) if lesson_ids else False

    if settings["auto_discover"] and not has_explicit_selected:
        try:
            items = discover_practice_links(
                driver, settings["course"], account_name, settings["timeout"]
            )
            if items:
                log(
                    account_name,
                    f"На странице курса найдено практических работ: {len(items)}",
                )
            else:
                log(account_name, "На странице курса не найдено ссылок на практику.")
        except NotEnrolledError as exc:
            log(
                account_name,
                f"Курс {settings['course']} недоступен для этого аккаунта "
                f"({exc}). Использую явный список items из config.json.",
            )
            summary["skipped_reason"] = "not_enrolled"
        except Exception as exc:
            log(
                account_name,
                f"Не удалось автоматически найти домашки: "
                f"{type(exc).__name__}: {exc}",
            )

    
    known_subjects = {item["subject"] for item in items}
    for item in settings["items"]:
        if item["subject"] not in known_subjects:
            items.append(item)
            known_subjects.add(item["subject"])

    if lesson_ids:
        before = len(items)
        items = [
            item
            for item in items
            if _to_int(item.get("lesson"), 0) in lesson_ids
        ]
        log(
            account_name,
            f"Выбраны уроки: {', '.join(str(item) for item in sorted(lesson_ids))}. "
            f"Домашек к решению: {len(items)} из {before}.",
        )

    if not items:
        log(account_name, "Нет домашних работ для обработки.")
        return summary

    for index, item in enumerate(items, start=1):
        try:
            item_summary = run_one_homework(
                driver, account_name, settings, item, index, len(items)
            )
        except Exception as exc:
            log(
                account_name,
                f"❌ Домашка «{item.get('name')}»: "
                f"{type(exc).__name__}: {exc}",
            )
            save_error_screenshot(
                driver, account_name, f"hw_{item.get('subject', 'unknown')}"
            )
            summary["errors"].append(
                {
                    "homework": item.get("name"),
                    "subject": item.get("subject"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue

        summary["homeworks"].append(item_summary)
        summary["total"] += _to_int(item_summary.get("total"), 0)
        summary["already_done"] += _to_int(item_summary.get("already_done"), 0)
        summary["solved_now"] += _to_int(item_summary.get("solved_now"), 0)
        summary["skipped"] += _to_int(item_summary.get("skipped"), 0)
        summary["errors"].extend(item_summary.get("errors") or [])
        summary["points"] += _to_float(item_summary.get("points"), 0.0)
        summary["max_points"] += _to_float(item_summary.get("max_points"), 0.0)

    if summary["max_points"]:
        summary["percent"] = round(
            summary["points"] / summary["max_points"] * 100, 1
        )

    log(account_name, "=" * 50)
    log(
        account_name,
        f"ИТОГО ПО ВСЕМ ДОМАШКАМ: заданий {summary['total']}, "
        f"уже было {summary['already_done']}, "
        f"решено сейчас {summary['solved_now']}, "
        f"пропущено {summary['skipped']}, "
        f"ошибок {len(summary['errors'])}",
    )
    if summary["max_points"]:
        log(
            account_name,
            f"Баллы: {summary['points']:g}/{summary['max_points']:g} "
            f"({summary['percent']}%)",
        )
    log(account_name, "=" * 50)
    return summary
