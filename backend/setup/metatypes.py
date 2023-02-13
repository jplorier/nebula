import json
import os


async def setup_metatypes(meta_types, db):
    languages = ["en", "cs"]

    aliases = {}
    for lang in languages:
        aliases[lang] = {}
        trans_table_fname = os.path.join("schema", f"meta-aliases-{lang}.json")
        adata = json.load(open(trans_table_fname))
        for key, alias, header, description in adata:
            if header is None:
                header = alias
            aliases[lang][key] = [alias, header, description]

    for key, data in meta_types.items():

        meta_type = {}
        meta_type["ns"] = data["ns"]
        meta_type["editable"] = True
        meta_type["class"] = data["type"].value
        meta_type["aliases"] = {}

        for opt in ["cs", "fulltext", "mode", "format", "default"]:
            if opt in data:
                meta_type[opt] = data[opt]

        for lang in languages:
            meta_type["aliases"][lang] = aliases[lang][key]

        await db.execute(
            """
            INSERT INTO meta_types (key, settings) VALUES ($1, $2)
            ON CONFLICT (key) DO UPDATE SET settings=$2
            """,
            key,
            meta_type,
        )

        if data.get("index", False):
            idx_name = "idx_" + key.replace("/", "_")
            await db.execute(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON assets((meta->>'{key}'))",
            )