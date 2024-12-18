# database.py

import time
import mysql.connector
from mysql.connector import Error

DB_CONFIG = {
    'host': 'mysql',
    'user': 'user',
    'password': 'pass',
    'database': 'ndn_logs'
}

def connect_db():
    """データベース接続を確立する"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"データベース接続エラー: {e}")
        return None
