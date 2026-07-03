#!/usr/bin/env python3
"""检查 MySQL / Redis 连接。"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def check_mysql() -> bool:
    print("=== MySQL ===")
    try:
        import pymysql

        host = os.getenv("MYSQL_HOST")
        port = int(os.getenv("MYSQL_PORT", "3306"))
        user = os.getenv("MYSQL_USER")
        password = os.getenv("MYSQL_PASSWORD")
        database = os.getenv("MYSQL_DATABASE")
        print(f"connecting {user}@{host}:{port}/{database} ...")

        conn = pymysql.connect(
            host=host,
            port=port,
            user=user,
            password=password,
            database=database,
            connect_timeout=10,
            charset="utf8mb4",
        )
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION(), DATABASE(), USER()")
            version, db, db_user = cur.fetchone()
            print(f"OK: version={version}, database={db}, user={db_user}")
            cur.execute("SHOW TABLES")
            tables = cur.fetchall()
            print(f"tables count: {len(tables)}")
        conn.close()
        return True
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


def check_redis() -> bool:
    if os.getenv("CHECK_REDIS", "").lower() not in ("1", "true", "yes"):
        print("\n=== Redis ===")
        print("SKIP: 自动化已禁用直连 Redis，设置 CHECK_REDIS=1 可手动检测")
        return True
    print("\n=== Redis ===")
    try:
        try:
            import redis
        except ImportError:
            import subprocess

            subprocess.check_call([sys.executable, "-m", "pip", "install", "redis", "-q"])
            import redis

        host = os.getenv("REDIS_HOST")
        port = int(os.getenv("REDIS_PORT", "6379"))
        db = int(os.getenv("REDIS_DATABASE", "0"))
        password = os.getenv("REDIS_PASSWORD") or None
        print(f"connecting {host}:{port} db={db} ...")

        client = redis.Redis(
            host=host,
            port=port,
            db=db,
            password=password,
            socket_connect_timeout=10,
            decode_responses=True,
        )
        print(f"PING: {client.ping()}")
        info = client.info("server")
        print(f"redis_version: {info.get('redis_version')}")
        print(f"dbsize: {client.dbsize()}")
        print("OK")
        return True
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}")
        return False


def main() -> None:
    mysql_ok = check_mysql()
    redis_ok = check_redis()
    if not (mysql_ok and redis_ok):
        sys.exit(1)


if __name__ == "__main__":
    main()
