import re
from contextlib import contextmanager
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session
from app.database.models import Base


def _safe_col(name: str) -> str:
    """カラム名が英数字・アンダースコアのみか検証する（動的SQL生成時のインジェクション対策）"""
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]*', name):
        raise ValueError(f"不正なカラム名が検出されました: {name!r}")
    return name


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

        col_names = [_safe_col(r[1]) for r in rows]
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


def _migrate_registered_date(engine) -> None:
    """members テーブルに registered_date カラムを追加する"""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(members)")).fetchall()]
        if "registered_date" not in cols:
            conn.execute(text("ALTER TABLE members ADD COLUMN registered_date DATE"))
            conn.commit()


def _migrate_mail_addressee_fields(engine) -> None:
    """郵送先宛名を事業所名・所属役職名・氏名の3項目へ移行する。"""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(members)")).fetchall()]
        if not cols:
            return
        for name in ("mail_org_name", "mail_dept_title", "mail_person_name"):
            if name not in cols:
                conn.execute(text(f"ALTER TABLE members ADD COLUMN {name} VARCHAR"))
        # 旧「郵送先宛名」は情報を失わないよう郵送先事業所名に引き継ぐ。
        if "addressee_mail" in cols:
            conn.execute(text("""
                UPDATE members
                SET mail_org_name = addressee_mail
                WHERE (mail_org_name IS NULL OR mail_org_name = '')
                  AND addressee_mail IS NOT NULL AND addressee_mail != ''
            """))
        conn.commit()


def _migrate_staff_signature(engine) -> None:
    """staff テーブルに signature カラムを追加する"""
    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(staff)")).fetchall()]
        if "signature" not in cols:
            conn.execute(text("ALTER TABLE staff ADD COLUMN signature TEXT"))
            conn.commit()


def _migrate_member_email_addresses(engine) -> None:
    """既存の members.email をラベル付き複数メールテーブルの1件目へ移行する。"""
    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO member_email_addresses (member_id, address, label, sort_order)
            SELECT m.id, m.email, '', 1
            FROM members m
            WHERE m.email IS NOT NULL AND TRIM(m.email) != ''
              AND NOT EXISTS (
                  SELECT 1 FROM member_email_addresses e WHERE e.member_id = m.id
              )
        """))
        conn.commit()


def _ensure_indexes(engine) -> None:
    """集計クエリを高速化するインデックスを初回起動時に作成する"""
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_member_changes_member_id"
            " ON member_changes(member_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_activity_logs_member_id"
            " ON activity_logs(member_id)"
        ))
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
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    _migrate(engine)
    _migrate_registered_date(engine)
    _migrate_mail_addressee_fields(engine)
    _migrate_staff_signature(engine)
    _migrate_member_email_addresses(engine)
    _ensure_indexes(engine)
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
