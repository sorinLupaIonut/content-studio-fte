"""The database layer — Decision 3.

    db.apply         applies schema.sql, idempotent
    db.seed          fills `clients` and `posts` from content/
    db.import_books  chunks and embeds the library into documents + embeddings
    db.migrate       one-off maintenance: schema rename, conversation backfill
"""
