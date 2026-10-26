"""Public test harness for third-party storage-backend implementers.

Export point for contract test base classes that third-party backends
(Postgres, Redis, S3, Notion, Firestore, …) inherit to validate their
impl matches the ABC's behavioral contract. Same suite the SDK's own
shipped impls (SQLite, Drive) run against.

Example:

    from openbench.testing import MemoryStoreContract
    from my_company.stores import MyPostgresMemoryStore

    class TestMyPostgresStore(MemoryStoreContract):
        def make_store(self):
            return MyPostgresMemoryStore(conn=test_db_conn)

        def cleanup_store(self, store):
            store._conn.execute("TRUNCATE messages")

    # pytest picks up the inherited test methods automatically.

The contract suite is versioned alongside the ABCs it validates;
signatures added in a minor version ship alongside matching contract
tests so impl authors can track compliance.
"""

from openbench.testing.memory_store_contract import MemoryStoreContract

__all__ = ["MemoryStoreContract"]
