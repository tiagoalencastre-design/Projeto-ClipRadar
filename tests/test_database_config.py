"""
Testes da configuração de produção do SQLite.

O PROBLEMA ORIGINAL: `sqlite3.connect()` sem nenhum PRAGMA. Com jobs
rodando em threads paralelas, isso produz "database is locked" — e as 12
FOREIGN KEY do esquema eram decorativas, porque o SQLite as ignora por
padrão.
"""
from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from core import database


class _TempDatabase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._patcher = patch.object(database, "DB_PATH", Path(self._tmp.name) / "t.db")
        self._patcher.start()
        database.init_db()

    def tearDown(self):
        self._patcher.stop()
        self._tmp.cleanup()

    def _user(self, email="t@e.com", key="k") -> int:
        with database.get_db() as conn:
            cur = conn.execute(
                """INSERT INTO users (email, username, password_hash, password_salt,
                   storage_key, email_verified, created_at)
                   VALUES (?, 'g', 'h', 's', ?, 1, '2026-01-01T00:00:00')""",
                (email, key),
            )
            conn.commit()
            return cur.lastrowid


class TestPragmas(_TempDatabase):
    def _pragma(self, name: str):
        with database.get_db() as conn:
            return list(conn.execute(f"PRAGMA {name}"))[0][0]

    def test_wal_is_enabled(self):
        """Sem WAL, uma leitura bloqueia a escrita e vice-versa."""
        self.assertEqual(self._pragma("journal_mode"), "wal")

    def test_foreign_keys_are_enforced(self):
        """O SQLite ignora FOREIGN KEY por padrão, mesmo declarada."""
        self.assertEqual(self._pragma("foreign_keys"), 1)

    def test_busy_timeout_is_set(self):
        """Sem espera, concorrência vira 'database is locked' na hora."""
        self.assertGreaterEqual(self._pragma("busy_timeout"), 5000)

    def test_pragmas_apply_to_every_connection(self):
        """foreign_keys não fica salvo no arquivo: precisa ser por conexão."""
        for _ in range(3):
            with database.get_db() as conn:
                self.assertEqual(list(conn.execute("PRAGMA foreign_keys"))[0][0], 1)


class TestForeignKeysActuallyWork(_TempDatabase):
    def test_orphan_row_is_rejected(self):
        """Antes isto passava: dava para criar clipe de um usuário inexistente."""
        with self.assertRaises(sqlite3.IntegrityError):
            with database.get_db() as conn:
                conn.execute(
                    """INSERT INTO clips (user_id, storage_path, created_at)
                       VALUES (99999, 'x.mp4', '2026-01-01')"""
                )
                conn.commit()

    def test_valid_row_is_accepted(self):
        user_id = self._user()
        with database.get_db() as conn:
            conn.execute(
                """INSERT INTO clips (user_id, storage_path, created_at)
                   VALUES (?, 'x.mp4', '2026-01-01')""",
                (user_id,),
            )
            conn.commit()

    def test_existing_database_has_no_violations(self):
        self._user()
        with database.get_db() as conn:
            self.assertEqual(list(conn.execute("PRAGMA foreign_key_check")), [])


class TestConcurrency(_TempDatabase):
    def test_parallel_writes_do_not_lock(self):
        """
        O cenário real: vários jobs gravando progresso ao mesmo tempo.
        Sem WAL e busy_timeout, isso produzia "database is locked".
        """
        user_id = self._user()
        errors: list[str] = []
        barrier = threading.Barrier(10)

        def write(n: int):
            barrier.wait()
            try:
                with database.get_db() as conn:
                    conn.execute(
                        """INSERT INTO clips (user_id, storage_path, created_at)
                           VALUES (?, ?, '2026-01-01')""",
                        (user_id, f"clip_{n}.mp4"),
                    )
                    conn.commit()
            except sqlite3.Error as e:
                errors.append(str(e))

        threads = [threading.Thread(target=write, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], f"escrita concorrente falhou: {errors}")
        with database.get_db() as conn:
            total = list(conn.execute("SELECT COUNT(*) FROM clips"))[0][0]
        self.assertEqual(total, 10)

    def test_reads_are_not_blocked_by_writes(self):
        """É o ganho principal do WAL."""
        user_id = self._user()
        errors: list[str] = []
        stop = threading.Event()

        def writer():
            n = 0
            while not stop.is_set() and n < 40:
                try:
                    with database.get_db() as conn:
                        conn.execute(
                            """INSERT INTO clips (user_id, storage_path, created_at)
                               VALUES (?, ?, '2026-01-01')""",
                            (user_id, f"w_{n}.mp4"),
                        )
                        conn.commit()
                except sqlite3.Error as e:
                    errors.append(f"escrita: {e}")
                n += 1

        def reader():
            for _ in range(40):
                try:
                    with database.get_db() as conn:
                        list(conn.execute("SELECT COUNT(*) FROM clips"))
                except sqlite3.Error as e:
                    errors.append(f"leitura: {e}")

        threads = [threading.Thread(target=writer), threading.Thread(target=reader)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        stop.set()

        self.assertEqual(errors, [], f"leitura e escrita se bloquearam: {errors}")


class TestIndexes(_TempDatabase):
    def _plan(self, sql: str) -> str:
        with database.get_db() as conn:
            return " ".join(r["detail"] for r in conn.execute("EXPLAIN QUERY PLAN " + sql))

    def test_hot_queries_use_an_index(self):
        """
        Cada consulta abaixo existe no código. Índice sem consulta só custa
        espaço; consulta sem índice vira varredura completa quando a tabela
        cresce.
        """
        queries = {
            "vídeos do usuário":
                "SELECT * FROM videos WHERE user_id=1 ORDER BY created_at DESC",
            "vídeo por caminho":
                "SELECT * FROM videos WHERE user_id=1 AND storage_path='x'",
            "jobs do usuário":
                "SELECT * FROM jobs WHERE user_id=1 ORDER BY started_at DESC",
            "jobs órfãos no boot":
                "SELECT id FROM jobs WHERE status IN ('queued','running')",
            "clipes do job":
                "SELECT * FROM clips WHERE job_id='j' ORDER BY created_at",
            "minutos do mês":
                "SELECT SUM(minutes_processed) FROM usage_events WHERE user_id=1",
            "feedback do usuário":
                "SELECT verdict FROM clip_feedback WHERE user_id=1",
        }
        for label, sql in queries.items():
            self.assertIn("INDEX", self._plan(sql).upper(), f"{label}: varredura completa")

    def test_indexes_are_idempotent(self):
        """init_db() roda a cada boot; não pode falhar na segunda vez."""
        database.init_db()
        database.init_db()
        with database.get_db() as conn:
            names = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'")}
        self.assertGreaterEqual(len(names), 10)


if __name__ == "__main__":
    unittest.main()
