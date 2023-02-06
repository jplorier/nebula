import time
from typing import Any

import asyncpg
from nxtools import slugify

from nebula.db import DB, db
from nebula.enum import ObjectTypeId
from nebula.exceptions import NotFoundException
from nebula.log import log
from nebula.messaging import msg
from nebula.metadata.format import format_meta
from nebula.metadata.normalize import normalize_meta
from nebula.settings import settings


def create_ft_index(meta) -> dict[str, float]:
    ft: dict[str, float] = {}
    if "subclips" in meta:
        weight = 8
        for sc in [k.get("title", "") for k in meta["subclips"]]:
            try:
                for word in slugify(sc, make_set=True, min_length=3):
                    word = str(word)
                    if word not in ft:
                        ft[word] = weight
                    else:
                        ft[word] = max(ft[word], weight)
            except Exception:
                log.error("Unable to slugify subclips data")
    for key in meta:
        if key not in settings.metatypes:
            continue
        if not (weight := settings.metatypes[key].fulltext):
            continue
        try:
            for word in slugify(meta[key], make_set=True, min_length=3):
                if word not in ft:
                    ft[word] = weight
                else:
                    ft[word] = max(ft[word], weight)
        except Exception:
            log.error(f"Unable to slugify key {key} with value {meta[key]}")
    return ft


class BaseObject:
    object_type: str
    meta: dict[str, Any] = {}
    defaults: dict[str, Any] = {}
    db_columns: list[str] = []
    connection: asyncpg.Connection | DB | None = None
    username: str | None = None  # Name of the user operating on the object

    def __init__(self, meta: dict[str, Any] | None = None, **kwargs) -> None:

        if (conn := kwargs.get("connection")) is not None:
            assert isinstance(conn, asyncpg.Connection) or isinstance(conn, DB)
            self.connection = conn
        else:
            self.connection = db

        self.username = kwargs.get("username")

        if meta is None:
            meta = {}
        self.meta = self.defaults | meta

    def __repr__(self) -> str:
        return f"<{self.__str__().capitalize()}>"

    def __str__(self) -> str:
        obid = f"id={self.id or 'UNSAVED'}"
        if self.object_type == "user":
            return f"{self.object_type} {obid} ({self.meta.get('login', 'Anonymous')})"
        elif title := self.meta.get("title"):
            return f"{self.object_type} {obid} ({title})"
        else:
            return f"{self.object_type} {obid}"

    @property
    def id(self) -> int | None:
        id = self.meta.get("id")
        # Handle false and other weird values
        # Yes. It happens.
        if not id:
            return None
        return int(id)

    def show(self, key: str, **kwargs) -> str:
        """Return a formated value of a given key"""
        return format_meta(self, key, **kwargs)

    #
    # Access and update object metadata
    #

    def __getitem__(self, key: str) -> Any:
        value = self.meta.get(key)
        if value is None and key in settings.metatypes:
            default = settings.metatypes[key].default
            return default
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        """Set a metadata value

        Raises ValueError if the provided value is cannot
        be casted to the expected type.
        """
        try:
            value = normalize_meta(key, value)
        except ValueError as e:
            raise ValueError(f"Invalid value for {key}: {value}") from e
        if value is None:
            self.meta.pop(key, None)
        else:
            self.meta[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        if (value := self[key]) is None:
            return default
        return value

    def patch(self, meta: dict[str, Any]) -> None:
        return self.update(meta)

    def update(self, meta: dict[str, Any]) -> None:
        """Update the object with the provided metadata"""
        for key, value in meta.items():
            self[key] = value

    #
    # Factory methods
    # TODO: after upgrading to Python 3.11, use 'self' as a return type
    #

    @classmethod
    async def load(cls, id: int, **kwargs):
        """Load an object from the database"""
        conn = kwargs.get("connection", db)
        res = await conn.fetch(f"SELECT meta FROM {cls.object_type}s WHERE id = $1", id)
        if not res:
            raise NotFoundException
        return cls(meta=res[0]["meta"], **kwargs)
        raise NotFoundException

    @classmethod
    def from_row(cls, row, **kwargs):
        """Return an object from a database row.

        meta is expected to be one of the column of the row.
        Note that no validation is performed.
        Do not use with untrusted data.
        """
        return cls(meta=dict(row["meta"]), **kwargs)

    @classmethod
    def from_meta(cls, meta: dict[str, Any], **kwargs):
        """Return an object from a metadata dict.

        Note that no validation is performed.
        Do not use with untrusted data.
        """
        return cls(meta=meta, **kwargs)

    @classmethod
    def from_untrusted(cls, meta: dict[str, Any], **kwargs):
        """Return an object from a metadata dict.

        Values are normalized and validated.
        """
        res = cls(**kwargs)
        for key, value in meta.items():
            res[key] = value
        return res

    #
    # Object saving
    #

    async def save(self, notify: bool = True, initiator: str = None) -> None:
        assert self.connection is not None
        if isinstance(self.connection, DB):
            pool = await self.connection.pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await self._save()
        elif (
            hasattr(self.connection, "is_in_transaction")
            and self.connection.is_in_transaction()
        ):
            await self._save()
        else:
            async with self.connection.transaction():
                await self._save()
        if notify:
            await msg(
                "objects_changed",
                object_type=self.object_type,
                objects=[self.id],
                initiator=initiator,
            )
        log.info(f"Saved {self}", user=self.username)

    async def _save(self) -> None:
        assert self.connection is not None
        if self.id is None:
            await self._insert()
        else:
            await self.connection.execute(
                "DELETE FROM ft WHERE object_type = $1 AND id = $2",
                ObjectTypeId[self.object_type.upper()].value,
                self.id,
            )
        ft_payloads = [
            (
                self.id,
                ObjectTypeId[self.object_type.upper()].value,
                weight,
                word,
            )
            for word, weight in create_ft_index(self.meta).items()
        ]

        await self.connection.executemany(
            """
            INSERT INTO ft (id, object_type, weight, value)
            VALUES ($1, $2, $3, $4)
            """,
            ft_payloads,
        )
        await self._update()

    async def _insert(self) -> None:
        assert self.connection is not None
        self.meta["ctime"] = self.meta["mtime"] = time.time()
        placeholders = ", ".join(
            ["$" + str(i) for i in range(1, len(self.db_columns) + 2)]
        )
        query = f"""
            INSERT INTO {self.object_type}s ({','.join(self.db_columns)}, meta)
            VALUES ({placeholders}) RETURNING id
            """
        qargs = [self[col] for col in self.db_columns] + [self.meta]
        res = await self.connection.fetch(query, *qargs)
        self.meta["id"] = res[0]["id"]

    async def _update(self) -> None:
        assert self.connection is not None
        self.meta["mtime"] = time.time()
        upcols = ", ".join(
            [col + " = $" + str(i) for i, col in enumerate(self.db_columns, 1)]
        )
        query = f"""
            UPDATE {self.object_type}s
            SET {upcols},
            meta=${len(self.db_columns) + 1}
            WHERE id = ${len(self.db_columns) + 2}
            """

        qargs = [self[col] for col in self.db_columns] + [self.meta, self.id]
        await self.connection.execute(query, *qargs)
