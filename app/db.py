import psycopg2

from .config import DATABASE_URL


def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("🚨 DATABASE_URL не найден! БД не подключена.")
    return psycopg2.connect(DATABASE_URL)


def init_db():
    if not DATABASE_URL:
        return
    try:
        conn = get_db_connection()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      VARCHAR(255) NOT NULL,
                email         VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                plan          VARCHAR(20)  DEFAULT 'free',
                credits       INTEGER      DEFAULT 5,
                msg_count     INTEGER      DEFAULT 0,
                last_reset    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                plan_expires  TIMESTAMP,
                created_at    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id         SERIAL PRIMARY KEY,
                email      VARCHAR(255) NOT NULL,
                role       VARCHAR(50)  NOT NULL,
                content    TEXT         NOT NULL,
                created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chats (
                id         SERIAL PRIMARY KEY,
                email      VARCHAR(255) NOT NULL,
                title      VARCHAR(255) DEFAULT 'Новый чат',
                created_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS payments (
                id         SERIAL PRIMARY KEY,
                email      VARCHAR(255)   NOT NULL,
                plan       VARCHAR(20)    NOT NULL,
                amount     DECIMAL(10,2)  NOT NULL,
                currency   VARCHAR(10)    DEFAULT 'USD',
                status     VARCHAR(20)    DEFAULT 'pending',
                tx_id      VARCHAR(255),
                created_at TIMESTAMP      DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        migrations = [
            ("users",    "plan",         "VARCHAR(20) DEFAULT 'free'"),
            ("users",    "credits",      "INTEGER DEFAULT 5"),
            ("users",    "msg_count",    "INTEGER DEFAULT 0"),
            ("users",    "last_reset",   "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("users",    "plan_expires", "TIMESTAMP"),
            ("users",    "created_at",   "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("messages", "chat_id",      "INTEGER DEFAULT NULL"),
        ]
        for table, col, col_type in migrations:
            cursor.execute(
                """SELECT column_name FROM information_schema.columns
                   WHERE table_name=%s AND column_name=%s""",
                (table, col)
            )
            if not cursor.fetchone():
                cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}")

        conn.commit()
        conn.close()
        print("✅ БД инициализирована успешно")
    except Exception as e:
        print(f"🚨 Ошибка БД: {e}")
