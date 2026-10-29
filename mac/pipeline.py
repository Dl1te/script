from __future__ import annotations

import sys
import time
from typing import Any

import homework
import quick_login as core


def _reconfigure_stdout() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _format_homework(item: dict[str, Any]) -> str:
    if not item:
        return "домашка не запускалась"
    if item.get("enabled") is False:
        return "домашка отключена"

    homeworks = item.get("homeworks") or []
    if not homeworks:
        if item.get("errors"):
            return f"домашка: ошибок {len(item['errors'])}"
        return "домашка: нет заданий"

    max_points = float(item.get("max_points") or 0)
    if max_points:
        return (
            f"домашка {float(item.get('points') or 0):g}/{max_points:g} "
            f"({item.get('percent')}%)"
        )

    total = _to_int(item.get("total"), 0)
    already = _to_int(item.get("already_done"), 0)
    solved = _to_int(item.get("solved_now"), 0)
    errors = len(item.get("errors") or [])
    if total and already >= total and not solved and not errors:
        return f"домашка: все {total} заданий уже выполнены"
    return (
        f"домашка: всего {total}, уже было {already}, "
        f"решено сейчас {solved}, ошибок {errors}"
    )


def _print_summary(results: list[dict[str, Any]]) -> None:
    print("\n" + "=" * 68)
    print("ИТОГ ПО АККАУНТАМ")
    print("=" * 68)

    for item in results:
        if item.get("ok"):
            print(f"  OK   {item['name']}: вход выполнен, {_format_homework(item.get('homework'))}")
        else:
            error = item.get("error") or "вход не выполнен"
            print(f"  НЕТ  {item['name']}: {error}")

    print("=" * 68)
    if all(item.get("ok") for item in results):
        print("Все аккаунты обработаны.")
    else:
        failed = [item["name"] for item in results if not item.get("ok")]
        print("Не удалось войти: " + ", ".join(failed))
        print("Повторите запуск — уже выполненные задания будут пропущены.")


def run(do_homework: bool = True) -> int:
    _reconfigure_stdout()

    cfg = core.load_config(core.CONFIG_PATH)
    accounts = core.parse_accounts(cfg)
    if not accounts:
        raise SystemExit(
            "Нет готовых аккаунтов. Заполните email/password в config.json."
        )

    print("=" * 68)
    print("MAXIMUM: аккаунты по очереди" + (" — вход и домашка" if do_homework else " — только вход"))
    print(f"Цель: {cfg['target_url']}")
    print(f"Аккаунтов: {len(accounts)}")
    for number, account in enumerate(accounts, start=1):
        print(f"  {number}. {account.name}")
        print(f"     профиль: {account.profile}")
    print("=" * 68)

    driver_path = core.resolve_driver_path(cfg)
    if driver_path:
        core.log("driver", f"ChromeDriver: {driver_path}")
    else:
        core.log(
            "driver",
            "ChromeDriver не найден заранее — Selenium Manager попробует сам.",
        )

    attempts_limit = max(1, _to_int(cfg.get("login_attempts"), 1))
    results: list[dict[str, Any]] = []

    for number, account in enumerate(accounts, start=1):
        print("\n" + "=" * 68)
        print(f"Аккаунт {number}/{len(accounts)}: {account.name}")
        print("=" * 68)

        account_result: dict[str, Any] = {
            "name": account.name,
            "ok": False,
            "homework": None,
            "error": None,
        }

        for attempt in range(1, attempts_limit + 1):
            driver = None
            try:
                account.profile.mkdir(parents=True, exist_ok=True)
                core.log(account.name, "Запускаю Chrome...")
                driver = core.launch_driver(account, cfg, driver_path)
                try:
                    driver.maximize_window()
                except Exception:
                    pass

                ok = core.login_flow(driver, account, cfg)
                if not ok:
                    core.log(account.name, "Вход не выполнен.")
                    core.save_debug_artifacts(driver, account)
                    account_result["error"] = "вход не выполнен"
                    
                    if attempt < attempts_limit:
                        core.log(
                            account.name,
                            f"Повторная попытка входа ({attempt + 1}/{attempts_limit})...",
                        )
                        time.sleep(2.0)
                        continue
                    break

                core.log(account.name, "OK: сессия создана/активна.")
                account_result["ok"] = True

                if do_homework:
                    try:
                        account_result["homework"] = homework.run_homework(
                            driver, account, cfg
                        )
                    except Exception as exc:
                        core.log(
                            account.name,
                            f"ОШИБКА домашки: {type(exc).__name__}: {exc}",
                        )
                        account_result["homework"] = {
                            "enabled": True,
                            "homeworks": [],
                            "total": 0,
                            "already_done": 0,
                            "solved_now": 0,
                            "skipped": 0,
                            "errors": [
                                {
                                    "stage": "run_homework",
                                    "error": f"{type(exc).__name__}: {exc}",
                                }
                            ],
                            "points": 0,
                            "max_points": 0,
                            "percent": None,
                        }
                break

            except core.WebDriverException as exc:
                message = str(exc).splitlines()[0]
                core.log(account.name, f"ОШИБКА Chrome/Selenium: {message}")
                account_result["error"] = message
                lowered = str(exc).lower()
                if (
                    "user data directory is already in use" in lowered
                    or "lock" in lowered
                ):
                    core.log(
                        account.name,
                        "Профиль занят другим окном Chrome. "
                        "Закройте его и запустите снова.",
                    )
                    break
            except Exception as exc:
                core.log(
                    account.name,
                    f"ОШИБКА: {type(exc).__name__}: {exc}",
                )
                account_result["error"] = f"{type(exc).__name__}: {exc}"
            finally:
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception:
                        pass

            if attempt < attempts_limit:
                core.log(
                    account.name,
                    f"Повторная попытка входа ({attempt + 1}/{attempts_limit})...",
                )
                time.sleep(2.0)
            else:
                break

        results.append(account_result)

        if number < len(accounts):
            core.log(
                account.name,
                "Браузер закрыт. Перехожу к следующему аккаунту.",
            )
        else:
            core.log(account.name, "Последний аккаунт обработан.")

    _print_summary(results)
    return 0 if all(item.get("ok") for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(run(do_homework=True))
