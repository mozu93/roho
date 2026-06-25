from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from app.database.models import Base


def _migrate(engine) -> None:
    """既存 members テーブルに company_code / is_member を追加し、
    member_number の NOT NULL 制約を除去するマイグレーション。"""
    with engine.connect() as conn:
        rows = conn.execute(text("PRAGMA table_info(members)")).fetchall()
        if not rows:
            return  # テーブルがまだ存在しない

        col_map = {r[1]: {"notnull": r[3]} for r in rows}
        has_company_code = "company_code" in col_map
        has_is_member    = "is_member"    in col_map
        member_no_notnull = col_map.get("member_number", {}).get("notnull", 0) == 1

        # いずれかが欠けていれば全列を含むテーブル再構築で対応
        if has_company_code and has_is_member and not member_no_notnull:
            return  # 最新スキーマ

        col_names = [r[1] for r in rows]
        select_cols = []
        for c in col_names:
            if c == "company_code":
                select_cols.append("company_code")
            elif c == "is_member":
                select_cols.append("is_member")
            else:
                select_cols.append(c)

        conn.execute(text("""
            CREATE TABLE members_new (
                id INTEGER NOT NULL PRIMARY KEY,
                company_code INTEGER UNIQUE,
                member_number VARCHAR UNIQUE,
                is_member INTEGER NOT NULL DEFAULT 1,
                org_name VARCHAR NOT NULL,
                org_kana VARCHAR, dept_title VARCHAR, rep_name VARCHAR, rep_kana VARCHAR,
                email VARCHAR, tel_area VARCHAR, tel VARCHAR, fax_area VARCHAR, fax VARCHAR,
                postal_code VARCHAR, address VARCHAR,
                postal_code_mail VARCHAR, address_mail VARCHAR, addressee_mail VARCHAR,
                label_tag VARCHAR, employment_ins_no VARCHAR, note TEXT,
                is_active INTEGER NOT NULL, withdrawn_at DATE, withdraw_reason TEXT,
                created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
            )
        """))

        existing = ", ".join(c for c in col_names if c not in ("company_code", "is_member"))
        conn.execute(text(f"""
            INSERT INTO members_new (company_code, is_member, {existing})
            SELECT
                COALESCE({"company_code" if "company_code" in col_map else "id"}, id),
                COALESCE({"is_member" if "is_member" in col_map else "1"}, 1),
                {existing}
            FROM members
        """))

        conn.execute(text("DROP TABLE members"))
        conn.execute(text("ALTER TABLE members_new RENAME TO members"))
        conn.commit()


def get_engine(db_path: str):
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_wal(dbapi_conn, _):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA busy_timeout=5000")

    Base.metadata.create_all(engine)
    _migrate(engine)
    return engine


@contextmanager
def get_session(engine):
    with Session(engine) as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
