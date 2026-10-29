from __future__ import annotations

import json
import os
import random
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"

EMAIL_SELECTOR = 'input[dataqa="loginEmail"]'
PASSWORD_SELECTOR = 'input[data-qa="loginPassword"]'
SUBMIT_SELECTOR = 'button[data-qa="loginSubmitBtn"]'

PRINT_LOCK = threading.Lock()
DRIVERS_LOCK = threading.Lock()
DRIVERS: list[tuple[str, webdriver.Chrome]] = []


def log(name: str, message: str) -> None:
    with PRINT_LOCK:
        print(f"[{time.strftime('%H:%M:%S')}] [{name}] {message}", flush=True)


@dataclass
class Account:
    name: str
    email: str
    password: str
    profile: Path


DEFAULTS = {
    "target_url": "https://education.maximumtest.ru/student/courses",
    "headless": False,
    "tile_windows": True,
    "window_margin": 8,
    "typing_delay": 0.01,
    "refresh_before_login": 2,
    "refresh_delay": 2.0,
    "start_timeout": 180,
    "login_timeout": 180,
    "captcha_timeout": 300,
    "page_load_timeout": 90,
    "keep_open": True,
    "browser_binary": "",
    "driver_path": "",
    "profiles_dir": "%LOCALAPPDATA%/LeaderIdMultiLogin/profiles",
}


def load_config(path: Path) -> dict:
    if not path.is_file():
        raise SystemExit(f"Не найден конфиг: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Ошибка в config.json: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit("config.json должен содержать объект JSON.")
    cfg = {**DEFAULTS, **raw}
    target = str(cfg.get("target_url") or "").strip()
    if not target.startswith(("http://", "https://")):
        raise SystemExit("В config.json не задан корректный target_url.")
    return cfg


def get_profiles_dir(cfg: dict) -> Path:
    profiles_dir = Path(
        os.path.expandvars(str(cfg.get("profiles_dir") or "profiles"))
    ).expanduser()
    if not profiles_dir.is_absolute():
        profiles_dir = ROOT / profiles_dir
    return profiles_dir


def resolve_profile_path(cfg: dict, name: str) -> Path:
    path = Path(name)
    if not path.is_absolute():
        path = get_profiles_dir(cfg) / path
    return path.resolve()


def parse_accounts(cfg: dict) -> list[Account]:
    raw_accounts = cfg.get("accounts") or []
    if not isinstance(raw_accounts, list):
        raise SystemExit("Поле accounts в config.json должно быть массивом.")

    accounts: list[Account] = []
    seen_profiles: set[str] = set()

    for index, item in enumerate(raw_accounts, start=1):
        if not isinstance(item, dict):
            log("config", f"Аккаунт #{index} пропущен: это не объект JSON.")
            continue
        if not item.get("enabled", True):
            continue

        name = str(item.get("name") or f"Аккаунт {index}").strip()
        email = str(item.get("email") or "").strip()
        password = str(item.get("password") or "")

        if not email or not password:
            log(name, "пропущен: не заполнены email/password в config.json.")
            continue
        if email.endswith("@example.com") or password.startswith("CHANGE_ME"):
            log(name, "пропущен: замените тестовые email/password в config.json.")
            continue

        profile_name = str(item.get("profile") or f"account{index}").strip()
        profile_path = resolve_profile_path(cfg, profile_name)

        key = os.path.normcase(str(profile_path))
        if key in seen_profiles:
            raise SystemExit(
                f"Профиль {profile_path} указан у нескольких аккаунтов. "
                "У каждого аккаунта должен быть свой profile."
            )
        seen_profiles.add(key)
        accounts.append(Account(name, email, password, profile_path))

    return accounts


def resolve_driver_path(cfg: dict | None = None) -> str | None:
    cfg = cfg or {}
    candidates: list[Path] = []

    custom = str(cfg.get("driver_path") or "").strip()
    if custom:
        custom_path = Path(
            os.path.expandvars(os.path.expanduser(custom))
        ).resolve()
        if custom_path.is_file():
            return str(custom_path)
        log("driver", f"ChromeDriver из config.json не найден: {custom_path}")

    env_path = os.environ.get("CHROMEDRIVER", "").strip()
    if env_path:
        candidates.append(
            Path(os.path.expandvars(os.path.expanduser(env_path))).resolve()
        )

    if sys.platform == "darwin":
        candidates.extend(
            [
                Path("/opt/homebrew/bin/chromedriver"),
                Path("/usr/local/bin/chromedriver"),
            ]
        )

    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)

    try:
        from selenium.webdriver.common.selenium_manager import SeleniumManager

        result = SeleniumManager().binary_paths(["--browser", "chrome"])
        driver_path = result.get("driver_path")
        if driver_path and Path(driver_path).is_file():
            return str(driver_path)
    except Exception as exc:
        log("driver", f"Не удалось заранее найти ChromeDriver: {exc}")
    return None


def build_options(account: Account, cfg: dict) -> Options:
    options = Options()
    binary = str(cfg.get("browser_binary") or "").strip()
    if binary:
        options.binary_location = os.path.expandvars(os.path.expanduser(binary))
    options.add_argument(f"--user-data-dir={account.profile}")
    options.add_argument("--profile-directory=Default")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")
    options.add_argument("--disable-notifications")
    options.add_argument("--disable-popup-blocking")
    options.add_argument("--disable-infobars")
    options.add_argument("--disable-session-crashed-bubble")
    options.add_argument("--hide-crash-restore-bubble")
    options.add_argument("--lang=ru-RU")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    if cfg.get("headless"):
        options.add_argument("--headless=new")
    if not cfg.get("tile_windows", True):
        options.add_argument("--start-maximized")
    return options


def launch_driver(
    account: Account, cfg: dict, driver_path: str | None
) -> webdriver.Chrome:
    service = Service(executable_path=driver_path) if driver_path else Service()
    driver = webdriver.Chrome(
        service=service, options=build_options(account, cfg)
    )
    driver.set_page_load_timeout(int(cfg.get("page_load_timeout") or 90))
    return driver


def get_screen_size(driver: webdriver.Chrome | None = None) -> tuple[int, int]:
    if driver is not None:
        try:
            size = driver.execute_script(
                "return [window.screen.availWidth, window.screen.availHeight];"
            )
            if size and int(size[0]) > 0 and int(size[1]) > 0:
                return int(size[0]), int(size[1])
        except WebDriverException:
            pass
    if sys.platform == "win32":
        try:
            import ctypes

            user32 = ctypes.windll.user32
            width = int(user32.GetSystemMetrics(0))
            height = int(user32.GetSystemMetrics(1))
            if width > 0 and height > 0:
                return width, height
        except Exception:
            pass
    return 1920, 1080


def tile_window(
    driver: webdriver.Chrome, index: int, total: int, cfg: dict
) -> None:
    if not cfg.get("tile_windows", True) or total <= 1:
        return
    margin = int(cfg.get("window_margin", 8))
    screen_w, screen_h = get_screen_size(driver)
    available = screen_w - margin * (total + 1)
    width = max(380, available // total)
    height = max(600, screen_h - margin * 2)
    x = margin + index * (width + margin)
    y = margin
    try:
        driver.set_window_rect(x=x, y=y, width=width, height=height)
    except WebDriverException:
        pass


def field_wrapper_class(driver: webdriver.Chrome, element) -> str:
    try:
        return str(
            driver.execute_script(
                """
                const wrapper = arguments[0].closest('.app-input');
                return wrapper ? wrapper.className : '';
                """,
                element,
            )
            or ""
        )
    except WebDriverException:
        return ""


def field_value(driver: webdriver.Chrome, element) -> str:
    try:
        return str(
            driver.execute_script("return arguments[0].value;", element) or ""
        )
    except WebDriverException:
        return ""


def set_field_value_js(
    driver: webdriver.Chrome, element, value: str
) -> None:
    driver.execute_script(
        """
        const el = arguments[0];
        const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'value'
        ).set;
        setter.call(el, arguments[1]);
        el.dispatchEvent(new Event('input',  {bubbles: true}));
        el.dispatchEvent(new Event('change', {bubbles: true}));
        """,
        element,
        value,
    )


def wait_field_focused(
    driver: webdriver.Chrome, element, timeout: float = 10.0
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if "focused" in field_wrapper_class(driver, element):
            return True
        try:
            element.click()
        except WebDriverException:
            try:
                driver.execute_script("arguments[0].focus();", element)
            except WebDriverException:
                return False
        time.sleep(0.5)
    return False


def fill_field(
    driver: webdriver.Chrome, element, value: str, cfg: dict
) -> bool:
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block: 'center'});", element
        )
        time.sleep(0.1)
    except WebDriverException:
        pass

    try:
        element.click()
    except (ElementClickInterceptedException, WebDriverException):
        driver.execute_script("arguments[0].click();", element)

    wait_field_focused(driver, element)

    try:
        element.clear()
    except WebDriverException:
        pass

    if field_value(driver, element):
        try:
            set_field_value_js(driver, element, "")
        except WebDriverException:
            pass

    delay = float(cfg.get("typing_delay") or 0)
    if delay > 0:
        for char in value:
            element.send_keys(char)
            time.sleep(random.uniform(delay * 0.4, delay * 1.4))
    else:
        element.send_keys(value)

    try:
        driver.execute_script(
            """
            const el = arguments[0];
            el.dispatchEvent(new Event('input',  {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
            el.dispatchEvent(new Event('blur',   {bubbles: true}));
            """,
            element,
        )
    except WebDriverException:
        pass

    for attempt in range(2):
        deadline = time.time() + 3.0
        while time.time() < deadline:
            current = field_value(driver, element)
            classes = field_wrapper_class(driver, element)
            if current == value and "value" in classes.split():
                return True
            time.sleep(0.2)
        if attempt == 0:
            try:
                set_field_value_js(driver, element, value)
            except WebDriverException:
                return False

    return False


def captcha_snapshot(driver: webdriver.Chrome) -> dict:
    try:
        return driver.execute_script(
            """
            const frames = [];
            const containers = [];
            const visit = (root) => {
              root.querySelectorAll('iframe').forEach((f) => {
                const r = f.getBoundingClientRect();
                const s = getComputedStyle(f);
                frames.push({
                  src: f.src || '',
                  w: Math.round(r.width),
                  h: Math.round(r.height),
                  display: s.display,
                  visibility: s.visibility
                });
              });
              root.querySelectorAll(
                '.smart-captcha, [data-testid="smartCaptcha-container"]'
              ).forEach((el) => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                containers.push({
                  w: Math.round(r.width),
                  h: Math.round(r.height),
                  display: s.display,
                  visibility: s.visibility,
                  opacity: s.opacity
                });
              });
              root.querySelectorAll('*').forEach((el) => {
                if (el.shadowRoot) visit(el.shadowRoot);
              });
            };
            visit(document);

            const findToken = (root) => {
              const direct = root.querySelector(
                'input[name="smart-token"], input[data-testid="smart-token"]'
              );
              if (direct) return direct;
              for (const el of root.querySelectorAll('*')) {
                if (!el.shadowRoot) continue;
                const found = findToken(el.shadowRoot);
                if (found) return found;
              }
              return null;
            };
            const tokenEl = findToken(document);
            const text = (document.body ? document.body.innerText : '').toLowerCase();
            return {
              frames: frames,
              containers: containers,
              token: tokenEl ? (tokenEl.value || '') : '',
              text: text
            };
            """
        )
    except WebDriverException:
        return {"frames": [], "containers": [], "token": "", "text": ""}


def snapshot_has_captcha(data: dict) -> bool:
    for container in data.get("containers", []):
        if (
            container.get("w", 0) > 0
            and container.get("h", 0) > 20
            and container.get("display") != "none"
            and container.get("visibility") != "hidden"
            and container.get("opacity") != "0"
        ):
            return True

    for frame in data.get("frames", []):
        src = (frame.get("src") or "").lower()
        if "captcha" not in src and "smartcaptcha" not in src:
            continue
        if (
            frame.get("w", 0) > 0
            and frame.get("h", 0) > 0
            and frame.get("display") != "none"
            and frame.get("visibility") != "hidden"
        ):
            return True

    text = data.get("text", "")
    markers = (
        "подтвердите, что вы не робот",
        "я не робот",
        "капча",
        "smartcaptcha",
        "captcha",
    )
    return any(marker in text for marker in markers)


def has_captcha(driver: webdriver.Chrome) -> bool:
    return snapshot_has_captcha(captcha_snapshot(driver))


def scroll_to_captcha(driver: webdriver.Chrome) -> None:
    try:
        driver.execute_script(
            """
            const el = document.querySelector(
              '.smart-captcha, [data-testid="smartCaptcha-container"]'
            );
            if (el) {
              el.scrollIntoView({block: 'center', behavior: 'smooth'});
              el.style.outline = '3px solid #ff4d4f';
              el.style.outlineOffset = '2px';
              setTimeout(() => {
                el.style.outline = '';
                el.style.outlineOffset = '';
              }, 3500);
            }
            """
        )
    except WebDriverException:
        pass


def notify_captcha() -> None:
    print("\a", end="", flush=True)
    if sys.platform == "win32":
        try:
            import winsound

            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            pass
    elif sys.platform == "darwin":
        try:
            import subprocess

            subprocess.run(
                ["afplay", "/System/Library/Sounds/Glass.aiff"],
                check=False,
                timeout=5,
            )
        except Exception:
            pass


def save_debug_artifacts(driver: webdriver.Chrome, account: Account) -> None:
    try:
        logs_dir = ROOT / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r"[^\w.-]+", "_", account.name).strip("_") or "account"
        base = logs_dir / f"{stamp}_{safe_name}"
        try:
            driver.save_screenshot(str(base.with_suffix(".png")))
            log(account.name, f"Скриншот: {base.with_suffix('.png')}")
        except Exception:
            pass
        try:
            base.with_suffix(".html").write_text(
                driver.page_source, encoding="utf-8"
            )
        except Exception:
            pass
    except Exception:
        pass


def visible_error(driver: webdriver.Chrome) -> str | None:
    selectors = (
        ".app-validate.is-error",
        ".el-message--error",
        ".el-notification--error",
        ".app-notification--error",
    )
    for selector in selectors:
        try:
            for element in driver.find_elements(By.CSS_SELECTOR, selector):
                if element.is_displayed():
                    text = (element.text or "").strip()
                    if text:
                        return text
        except WebDriverException:
            pass
    return None


def body_text(driver: webdriver.Chrome, limit: int = 3000) -> str:
    try:
        text = driver.find_element(By.TAG_NAME, "body").text or ""
        return text[:limit]
    except WebDriverException:
        return ""


def is_maximum_logged_in(driver: webdriver.Chrome) -> bool:
    try:
        url = driver.current_url
        if "education.maximumtest.ru/student/courses" not in url:
            return False
        text = body_text(driver, 5000)
        if not text or len(text) < 40:
            return False
        if "Войдите или зарегистрируйтесь" in text:
            return False
        return "Мои курсы" in text and (
            "Расписание" in text or "Цифровое портфолио" in text
        )
    except WebDriverException:
        return False


def click_maximum_2035(driver: webdriver.Chrome, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for element in driver.find_elements(By.CSS_SELECTOR, ".u2035-button"):
                if element.is_displayed():
                    log("maximum", "Кнопка «Войти через 20.35» найдена.")
                    try:
                        driver.execute_script(
                            "arguments[0].scrollIntoView({block: 'center'});",
                            element,
                        )
                        time.sleep(0.3)
                        element.click()
                    except WebDriverException:
                        driver.execute_script("arguments[0].click();", element)
                    return True
            for element in driver.find_elements(By.CSS_SELECTOR, "[role='button']"):
                text = (element.text or "").strip()
                if "Войти через" in text and "2035" in text and element.is_displayed():
                    element.click()
                    return True
        except WebDriverException:
            pass
        time.sleep(0.5)
    return False


def click_leader_id_consent(
    driver: webdriver.Chrome, timeout: float = 30.0
) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            for element in driver.find_elements(
                By.CSS_SELECTOR, "button, [role='button']"
            ):
                if not element.is_displayed():
                    continue
                text = (element.text or "").strip().lower()
                if text in ("авторизоваться", "разрешить"):
                    try:
                        element.click()
                    except WebDriverException:
                        driver.execute_script("arguments[0].click();", element)
                    return True
        except WebDriverException:
            pass
        time.sleep(0.5)
    return False


def click_2035_consent(
    driver: webdriver.Chrome, clicked_urls: set[str]
) -> bool:
    try:
        url = driver.current_url
        if url in clicked_urls:
            return False
        text = body_text(driver, 1200).lower()
        if "некорректная социальная регистрация" in text:
            return False
        for element in driver.find_elements(
            By.CSS_SELECTOR, "button, [role='button'], a"
        ):
            try:
                if not element.is_displayed():
                    continue
                label = (element.text or "").strip().lower()
                if not label:
                    continue
                if any(x in label for x in ("сменить аккаунт", "выйти", "отмена")):
                    continue
                if any(
                    x in label
                    for x in (
                        "авторизоваться",
                        "продолжить",
                        "разрешить",
                        "войти через leader-id",
                        "войти через leader id",
                    )
                ):
                    element.click()
                    clicked_urls.add(url)
                    log("2035", f"Нажата кнопка «{label}».")
                    return True
            except WebDriverException:
                continue
    except WebDriverException:
        pass
    return False


def leader_login_form_present(driver: webdriver.Chrome) -> bool:
    try:
        return any(
            element.is_displayed()
            for element in driver.find_elements(By.CSS_SELECTOR, EMAIL_SELECTOR)
        )
    except WebDriverException:
        return False


def handle_leader_id_login(
    driver: webdriver.Chrome, account: Account, cfg: dict
) -> bool:
    log(account.name, "Форма Leader-ID: перезагружаю страницу перед вводом...")
    refreshes = int(cfg.get("refresh_before_login") or 0)
    refresh_delay = float(cfg.get("refresh_delay") or 0)
    for attempt in range(refreshes):
        if "/partner/login" not in driver.current_url and not leader_login_form_present(
            driver
        ):
            break
        if refresh_delay > 0:
            time.sleep(random.uniform(refresh_delay * 0.7, refresh_delay * 1.3))
        log(
            account.name,
            f"Перезагружаю страницу перед входом ({attempt + 1}/{refreshes})...",
        )
        driver.refresh()
        if refresh_delay > 0:
            time.sleep(random.uniform(refresh_delay * 0.7, refresh_delay * 1.3))

    if "/partner/login" not in driver.current_url and not leader_login_form_present(
        driver
    ):
        return True

    wait = WebDriverWait(driver, int(cfg["login_timeout"]))
    try:
        email_field = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, EMAIL_SELECTOR))
        )
    except TimeoutException:
        if "/partner/login" not in driver.current_url and not leader_login_form_present(
            driver
        ):
            return True
        log(
            account.name,
            "ОШИБКА: не нашёл поле email на странице Leader-ID.",
        )
        return False

    log(account.name, f"Ввожу email: {account.email}")
    if not fill_field(driver, email_field, account.email, cfg):
        log(account.name, "ОШИБКА: email не попал в поле (форма не готова).")
        return False
    time.sleep(random.uniform(0.2, 0.5))

    log(account.name, "Ввожу пароль...")
    try:
        password_field = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, PASSWORD_SELECTOR))
        )
    except TimeoutException:
        log(account.name, "ОШИБКА: не нашёл поле пароля.")
        return False
    if not fill_field(driver, password_field, account.password, cfg):
        log(account.name, "ОШИБКА: пароль не попал в поле (форма не готова).")
        return False
    time.sleep(random.uniform(0.2, 0.5))

    log(account.name, "Нажимаю «Войти»...")
    try:
        submit = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SUBMIT_SELECTOR))
        )
        try:
            submit.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", submit)
    except TimeoutException:
        log(account.name, "ОШИБКА: не нашёл кнопку «Войти».")
        return False

    deadline = time.time() + int(cfg["login_timeout"])
    captcha_seen = False
    captcha_submitted = False
    last_note = 0.0

    while time.time() < deadline:
        if "/partner/login" not in driver.current_url:
            log(account.name, "OK: форма Leader-ID пройдена.")
            return True

        snap = captcha_snapshot(driver)
        captcha_now = snapshot_has_captcha(snap)
        token = str(snap.get("token") or "").strip()

        if captcha_now:
            now = time.time()
            if not captcha_seen:
                captcha_seen = True
                deadline = now + int(cfg["captcha_timeout"])
                scroll_to_captcha(driver)
                notify_captcha()
                log(
                    account.name,
                    "ВНИМАНИЕ: появилась капча. Пройдите её ВРУЧНУЮ "
                    "(галочка «Я не робот»). "
                    f"Жду до {int(cfg['captcha_timeout'])} сек. "
                    "После решения скрипт сам нажмёт «Войти» ещё раз.",
                )
                last_note = now
            elif now - last_note > 30:
                last_note = now
                left = max(0, int(deadline - now))
                log(
                    account.name,
                    f"Всё ещё жду решения капчи... осталось ~{left} сек.",
                )

            if captcha_submitted and not token:
                captcha_submitted = False

            if not captcha_submitted and token:
                log(account.name, "Капча решена. Нажимаю «Войти» ещё раз...")
                time.sleep(0.6)
                try:
                    submit_again = driver.find_element(
                        By.CSS_SELECTOR, SUBMIT_SELECTOR
                    )
                    try:
                        submit_again.click()
                    except WebDriverException:
                        driver.execute_script(
                            "arguments[0].click();", submit_again
                        )
                    captcha_submitted = True
                except WebDriverException:
                    pass
        else:
            error = visible_error(driver)
            if error:
                lowered = error.lower()
                if not any(
                    word in lowered for word in ("капч", "captcha", "робот")
                ):
                    log(account.name, f"ОШИБКА: {error}")
                    return False

        time.sleep(1.0)

    if captcha_seen:
        log(account.name, "ОШИБКА: капча не решена за отведённое время.")
    else:
        log(
            account.name,
            f"ОШИБКА: вход Leader-ID не завершился. URL: {driver.current_url}",
        )
    return False


def login_flow(driver: webdriver.Chrome, account: Account, cfg: dict) -> bool:
    target = str(cfg["target_url"])
    log(account.name, "Открываю MAXIMUM...")
    try:
        driver.get(target)
    except WebDriverException as exc:
        log(account.name, f"ОШИБКА открытия MAXIMUM: {str(exc).splitlines()[0]}")
        return False
    time.sleep(0.8)

    deadline = time.time() + int(cfg.get("start_timeout") or 180)
    login_timeout = int(cfg.get("login_timeout") or 180)
    last_url = ""
    last_note = time.time()
    max_clicked = False
    leader_started = False
    leader_consent_clicked = False
    consent_urls: set[str] = set()

    while time.time() < deadline:
        try:
            url = driver.current_url
        except WebDriverException:
            log(account.name, "Браузер закрыт — вход прерван.")
            return False

        if url != last_url:
            log(account.name, f"URL: {url}")
            last_url = url
            if "2035.university" in url or "leader-id.ru" in url:
                deadline = max(deadline, time.time() + login_timeout)

        if is_maximum_logged_in(driver):
            log(account.name, "OK: MAXIMUM открыт, вход выполнен.")
            return True

        if "/partner/login" in url or (
            "leader-id.ru" in url and leader_login_form_present(driver)
        ):
            if not leader_started:
                leader_started = True
                if not handle_leader_id_login(driver, account, cfg):
                    save_debug_artifacts(driver, account)
                    return False
                deadline = max(deadline, time.time() + login_timeout)
            time.sleep(0.5)
            continue

        if "login.maximumtest.ru/oauth/authorize" in url:
            if not max_clicked:
                log(account.name, "Нажимаю «Войти через 20.35 Университет»...")
                if not click_maximum_2035(driver):
                    log(account.name, "ОШИБКА: не нашёл кнопку 20.35.")
                    save_debug_artifacts(driver, account)
                    return False
                max_clicked = True
                deadline = max(deadline, time.time() + login_timeout)
            time.sleep(0.5)
            continue

        if "leader-id.ru/oauth/authorize" in url:
            if not leader_consent_clicked:
                if click_leader_id_consent(driver, timeout=5):
                    leader_consent_clicked = True
                    log(account.name, "Вход в Leader-ID подтверждён.")
                    deadline = max(deadline, time.time() + login_timeout)
            time.sleep(0.5)
            continue

        if "2035.university" in url:
            text = body_text(driver, 1500).lower()
            if "некорректная социальная регистрация" in text:
                log(
                    account.name,
                    "ОШИБКА 2035: некорректная социальная регистрация. "
                    "Попробуйте начать с education.maximumtest.ru заново.",
                )
                save_debug_artifacts(driver, account)
                return False
            if click_2035_consent(driver, consent_urls):
                deadline = max(deadline, time.time() + login_timeout)
            time.sleep(0.5)
            continue

        if "login.maximumtest.ru/oauth-result" in url:
            time.sleep(0.5)
            continue

        time.sleep(0.5)
        if time.time() - last_note > 20:
            last_note = time.time()
            left = max(0, int(deadline - time.time()))
            log(account.name, f"Жду перенаправление... осталось ~{left} сек.")

    log(account.name, "ОШИБКА: вход не завершился за отведённое время.")
    save_debug_artifacts(driver, account)
    return False


def browser_alive(driver: webdriver.Chrome) -> bool:
    try:
        return bool(driver.window_handles)
    except WebDriverException:
        return False


def clear_browser_session(driver: webdriver.Chrome) -> None:
    try:
        driver.execute_cdp_cmd("Network.clearBrowserCookies", {})
    except WebDriverException:
        try:
            driver.delete_all_cookies()
        except WebDriverException:
            pass

    origins = (
        "https://leader-id.ru",
        "https://www.leader-id.ru",
        "https://sso.2035.university",
        "https://steps.2035.university",
        "https://2035.university",
        "https://www.2035.university",
        "https://my.2035.university",
        "https://login.maximumtest.ru",
        "https://education.maximumtest.ru",
        "https://maximumtest.ru",
        "https://www.maximumtest.ru",
    )
    for origin in origins:
        try:
            driver.execute_cdp_cmd(
                "Storage.clearDataForOrigin",
                {"origin": origin, "storageTypes": "all"},
            )
        except WebDriverException:
            pass

    try:
        driver.execute_cdp_cmd("Network.clearBrowserCache", {})
    except WebDriverException:
        pass

    try:
        driver.get("about:blank")
    except WebDriverException:
        pass


def quick_login_account(
    account: Account,
    cfg: dict,
    index: int,
    total: int,
    driver_path: str | None,
) -> None:
    driver = None
    try:
        account.profile.mkdir(parents=True, exist_ok=True)
        log(account.name, "Запускаю Chrome...")
        driver = launch_driver(account, cfg, driver_path)
        with DRIVERS_LOCK:
            DRIVERS.append((account.name, driver))
        tile_window(driver, index, total, cfg)

        log(account.name, "Открываю MAXIMUM...")
        driver.get(str(cfg["target_url"]))
        deadline = time.time() + int(cfg.get("start_timeout") or 180)
        max_renew_tried = False

        while time.time() < deadline:
            if is_maximum_logged_in(driver):
                log(account.name, "OK: курсы открыты. Окно оставлено открытым.")
                return

            url = driver.current_url
            if "login.maximumtest.ru/oauth/authorize" in url:
                if not max_renew_tried:
                    max_renew_tried = True
                    log(
                        account.name,
                        "Сессия MAXIMUM не активна, пробую войти через 20.35...",
                    )
                    if click_maximum_2035(driver, timeout=20):
                        deadline = max(deadline, time.time() + 60)
                else:
                    log(
                        account.name,
                        "ВНИМАНИЕ: сессия не готова. "
                        "Запустите setup_sessions.py для этого аккаунта.",
                    )
                    save_debug_artifacts(driver, account)
                    return
            elif "/partner/login" in url:
                log(
                    account.name,
                    "ВНИМАНИЕ: требуется вход Leader-ID. "
                    "Запустите setup_sessions.py для этого аккаунта.",
                )
                save_debug_artifacts(driver, account)
                return

            time.sleep(1.0)

        log(
            account.name,
            "ВНИМАНИЕ: не дождался страницы курсов. Проверьте окно вручную.",
        )
        save_debug_artifacts(driver, account)
    except WebDriverException as exc:
        message = str(exc).splitlines()[0]
        log(account.name, f"ОШИБКА Chrome/Selenium: {message}")
        lowered = str(exc).lower()
        if "user data directory is already in use" in lowered or "lock" in lowered:
            log(
                account.name,
                "Закройте предыдущее окно Chrome с этим профилем и запустите снова.",
            )
    except Exception as exc:
        log(account.name, f"ОШИБКА: {type(exc).__name__}: {exc}")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    from pipeline import run

    return run(do_homework=True)


if __name__ == "__main__":
    raise SystemExit(main())
