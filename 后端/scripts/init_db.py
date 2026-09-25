from kairos.adapters.sqlite import SQLiteStore
from kairos.settings import Settings


def main() -> None:
    store = SQLiteStore(Settings().db_path)
    store.initialize()
    print(f"Initialized SQLite database at {store.database_path}")


if __name__ == "__main__":
    main()
