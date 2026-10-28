from __future__ import annotations

import sys

import quick_login as core


def ask_after_success(account: core.Account) -> None:
    print("\n" + "-" * 68)
    print(f"Аккаунт «{account.name}»: сессия сохранена в профиле.")
    print(f"Профиль: {account.profile}")
    print("Окно оставлено открытым. Можно проверить, что курсы открылись.")
    print("Нажмите Enter, чтобы закрыть это окно и перейти к следующему аккаунту.")
    print("-" * 68)
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        pass


def ask_after_failure(account: core.Account) -> str:
    print("\n" + "-" * 68)
    print(f"Аккаунт «{account.name}»: вход НЕ выполнен.")
    print("r — повторить этот аккаунт")
    print("s — пропустить и перейти к следующему")
    print("q — завершить настройку")
    print("-" * 68)
    while True:
        try:
            choice = input("Выбор: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "q"
        if choice in ("r", "к", "retry"):
            return "retry"
        if choice in ("s", "ы", "skip"):
            return "skip"
        if choice in ("q", "й", "quit", "exit", "выход"):
            return "quit"
        print("Введите r, s или q.")


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    cfg = core.load_config(core.CONFIG_PATH)
    accounts = core.parse_accounts(cfg)
    if not accounts:
        raise SystemExit(
            "Нет готовых аккаунтов. Заполните email/password в config.json."
        )

    print("=" * 68)
    print("Настройка сессий: аккаунты по очереди, отдельный профиль на каждый")
    print(f"Цель: {cfg['target_url']}")
    print(f"Аккаунтов: {len(accounts)}")
    for number, account in enumerate(accounts, start=1):
        print(f"  {number}. {account.name} <{account.email}>")
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

    results: list[tuple[str, bool]] = []

    for number, account in enumerate(accounts, start=1):
        print("\n" + "=" * 68)
        print(f"Аккаунт {number}/{len(accounts)}: {account.name}")
        print("=" * 68)

        while True:
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
            except core.WebDriverException as exc:
                message = str(exc).splitlines()[0]
                core.log(account.name, f"ОШИБКА Chrome/Selenium: {message}")
                lowered = str(exc).lower()
                if (
                    "user data directory is already in use" in lowered
                    or "lock" in lowered
                ):
                    core.log(
                        account.name,
                        "Закройте предыдущее окно Chrome с этим профилем "
                        "и запустите снова.",
                    )
                ok = False
            except Exception as exc:
                core.log(
                    account.name,
                    f"ОШИБКА: {type(exc).__name__}: {exc}",
                )
                ok = False

            if ok:
                core.log(account.name, "OK: сессия сохранена.")
                results.append((account.name, True))
                ask_after_success(account)
                if driver is not None:
                    driver.quit()
                break

            if driver is not None:
                core.save_debug_artifacts(driver, account)

            choice = ask_after_failure(account)
            if driver is not None:
                try:
                    driver.quit()
                except Exception:
                    pass
            if choice == "retry":
                continue
            results.append((account.name, False))
            if choice == "quit":
                print("\nНастройка прервана пользователем.")
                print_summary(results)
                return 1
            break

    print_summary(results)
    return 0 if all(ok for _name, ok in results) else 1


def print_summary(results: list[tuple[str, bool]]) -> None:
    print("\n" + "=" * 68)
    print("Итог настройки сессий:")
    for name, ok in results:
        print(f"  {'OK ' if ok else 'НЕТ'}  {name}")
    print("=" * 68)
    if any(ok for _name, ok in results):
        print("Теперь можно запускать quick_login.py — окна откроются без входа.")
    if any(not ok for _name, ok in results):
        print("Для неудачных аккаунтов запустите setup_sessions.py ещё раз.")


if __name__ == "__main__":
    raise SystemExit(main())
