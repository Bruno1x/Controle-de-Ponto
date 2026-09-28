from updater import check_and_apply_update
from server import main


if __name__ == "__main__":
    if check_and_apply_update():
        raise SystemExit(0)
    main()
