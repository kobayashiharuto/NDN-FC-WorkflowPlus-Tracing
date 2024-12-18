import asyncio
import os
import random
import subprocess
import time
from typing import Callable, Optional, List, Dict, Any
from ndn.app import NDNApp
from ndn.encoding import Name, InterestParam, BinaryStr, FormalName, Component
from ndn.types import InterestNack, InterestTimeout
import logging
import datetime
import mysql.connector
from mysql.connector import Error
import urllib.parse

from lib.ndn_utils import SEGMENT_SIZE, extract_first_level_args, extract_my_function_name, get_data, get_original_name, is_function_request

logging.basicConfig(format='[{asctime}]{levelname}:{message}',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO,
                    style='{')

# データベース接続情報（必要に応じて変更してください）
DB_CONFIG = {
    'host': 'mysql',       # データベースのホスト名（Docker コンテナの場合はサービス名を指定）
    'user': 'user',        # データベースのユーザー名
    'password': 'pass',    # データベースのパスワード
    'database': 'ndn_logs' # 使用するデータベース名
}

class DatabaseManager:
    """
    データベースへの接続と操作を管理するクラス。
    """
    def __init__(self, config: Dict[str, str]):
        """
        コンストラクタ。

        Args:
            config (Dict[str, str]): データベース接続情報。
        """
        self.config = config
        self.connection = self._create_connection()
        self._create_tables()

    def _create_connection(self) -> mysql.connector.connection.MySQLConnection:
        """
        データベースへの接続を確立する。

        Returns:
            MySQLConnection: データベース接続オブジェクト。

        Raises:
            Exception: 接続に失敗した場合。
        """
        try:
            connection = mysql.connector.connect(**self.config)
            logging.info("MySQL database connection established.")
            return connection
        except Error as e:
            logging.error(f"Error connecting to MySQL: {e}")
            raise

    def _create_tables(self) -> None:
        """
        必要なテーブルが存在しない場合は作成する。
        """
        cursor = self.connection.cursor()
        try:
            # request_chain テーブルの作成
            create_request_chain_table = """
            CREATE TABLE IF NOT EXISTS request_chain (
                id INT AUTO_INCREMENT PRIMARY KEY,
                parent_nonce VARCHAR(255),
                child_nonce VARCHAR(255)
            );
            """
            cursor.execute(create_request_chain_table)

            # service_logs テーブルの作成
            create_service_logs_table = """
            CREATE TABLE IF NOT EXISTS service_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                request_id VARCHAR(255),
                name VARCHAR(1024),
                ip_address VARCHAR(45),
                data_size_before INT,
                data_size_after INT,
                start_time DATETIME,
                end_time DATETIME,
                processing_time_ms FLOAT
            );
            """
            cursor.execute(create_service_logs_table)

            self.connection.commit()
            logging.info("Tables 'request_chain' and 'service_logs' are ready.")
        except Error as e:
            logging.error(f"Error creating tables: {e}")
            self.connection.rollback()
        finally:
            cursor.close()

    def insert_request_chain(self, parent_nonce: str, child_nonce: str) -> None:
        """
        RCT（Request Chain Table）にエントリを追加する。

        Args:
            parent_nonce (str): 親の Nonce。
            child_nonce (str): 子の Nonce。
        """
        insert_query = """
        INSERT INTO request_chain (parent_nonce, child_nonce)
        VALUES (%s, %s)
        """
        data = (parent_nonce, child_nonce)
        cursor = self.connection.cursor()
        try:
            cursor.execute(insert_query, data)
            self.connection.commit()
            logging.info(f"RCT entry added: parent_nonce={parent_nonce}, child_nonce={child_nonce}")
        except Error as e:
            logging.error(f"Error inserting RCT entry: {e}")
            self.connection.rollback()
        finally:
            cursor.close()

    def insert_service_log(self, request_id: str, name: str, ip_address: str,
                           data_size_before: int, data_size_after: int,
                           start_time: datetime.datetime, end_time: datetime.datetime, processing_time_ms: float) -> None:
        """
        service_logs テーブルにログエントリを追加する。

        Args:
            request_id (str): 親の Nonce。
            name (str): リクエストの名前。
            ip_address (str): サービスノードのIPアドレス。
            data_size_before (int): 処理前のデータサイズ（バイト）。
            data_size_after (int): 処理後のデータサイズ（バイト）。
            start_time (datetime.datetime): 処理開始時間。
            end_time (datetime.datetime): 処理終了時間。
            processing_time_ms (float): 処理時間（ミリ秒）。
        """
        insert_query = """
        INSERT INTO service_logs (request_id, name, ip_address, data_size_before, data_size_after, start_time, end_time, processing_time_ms)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        name = urllib.parse.unquote(name)
        data = (request_id, name, ip_address, data_size_before, data_size_after, start_time, end_time, processing_time_ms)
        cursor = self.connection.cursor()
        try:
            cursor.execute(insert_query, data)
            self.connection.commit()
            logging.info(f"Service log added for request_id={request_id}")
        except Error as e:
            logging.error(f"Error inserting service log: {e}")
            self.connection.rollback()
        finally:
            cursor.close()

    def close(self) -> None:
        """
        データベース接続を閉じる。
        """
        if self.connection.is_connected():
            self.connection.close()
            logging.info("MySQL database connection closed.")

class NDNFunction:
    """
    NDN 関数ノードを表すクラス。
    """
    def __init__(self):
        self.app = NDNApp()
        self.db_manager = DatabaseManager(DB_CONFIG)
        self.segmented_data = {}

        # IPアドレスの取得
        self.my_ip = self.get_ip_address()
        logging.info(f"My IP address: {self.my_ip}")

    def get_ip_address(self) -> str:
        """
        サービスノードのIPアドレスを取得する。

        Returns:
            str: サービスノードのIPアドレス。
        """
        try:
            result = subprocess.run(["hostname", "-I"], stdout=subprocess.PIPE, text=True, check=True)
            my_ip = result.stdout.strip().split()[0]  # 複数のIPが返される場合、最初のものを使用
            return my_ip
        except subprocess.CalledProcessError as e:
            logging.error(f"Error obtaining IP address: {e}")
            return "Unknown"

    def run(self, prefix: str, function_request_handler: Callable[[str, List[bytes]], bytes], data_request_handler: Callable[[str], str]):
        """
        プレフィックスに対して関数ハンドラとデータハンドラを登録して起動。

        Args:
            prefix (str): プレフィックス。
            function_request_handler (Callable[[str, List[bytes]], bytes]): 関数ハンドラ (関数名, 引数) -> 結果。
            data_request_handler (Callable[[str], str]): データハンドラ (名前) -> データ。
        """

        # プレフィックスを広告
        os.system(f"nlsrc advertise {prefix}")

        @self.app.route(prefix)
        def on_interest(name: FormalName, param: InterestParam, _app_param: Optional[BinaryStr]):
            async def async_on_interest():
                nonce = param.nonce
                if nonce is None:
                    # Nonce がない場合は新しく生成
                    nonce = random.randint(0, 2**32 - 1)
                nonce_str = str(nonce)
                name_str = Name.to_str(name)
                
                original_name = get_original_name(name)

                # function リクエストでない場合は、データリクエストとして処理
                if not is_function_request(original_name):
                    content = data_request_handler(name_str)
                    content = content.encode()

                    # セグメント前のリクエストであれば、データを取得してセグメントに分割して保存しておく
                    if Component.get_type(name[-1]) != Component.TYPE_SEGMENT:
                        # データを取得
                        content = data_request_handler(Name.to_str(name))
                        content = content.encode()

                        # データをセグメントに分割する
                        seg_cnt = (len(content) + SEGMENT_SIZE - 1) // SEGMENT_SIZE

                        # パケット分割の時間を計測
                        packets = [self.app.prepare_data(original_name + [Component.from_segment(i)],
                                                    content[i*SEGMENT_SIZE:(i+1)*SEGMENT_SIZE],
                                                    freshness_period=10000,
                                                    final_block_id=Component.from_segment(seg_cnt - 1))
                                for i in range(seg_cnt)]
                        
                        # セグメントデータを保存
                        self.segmented_data[Name.to_str(original_name)] = packets
                        seg_no = 0
                    else:
                        seg_no = Component.to_number(name[-1])

                    print(f'<< D: {Name.to_str(name)}')

                    # セグメントデータを送信
                    self.app.put_raw_packet(self.segmented_data[Name.to_str(original_name)][seg_no])
                    return
                
                # function リクエストの場合
                # 処理前(セグメント分割前)のリクエストであれば、データを処理してセグメントに分割して保存しておく
                if Component.get_type(name[-1]) != Component.TYPE_SEGMENT:
                    # function リクエストの場合は、まず第一階層の引数を抽出
                    args = extract_first_level_args(name)

                    # 親の Nonce（受信した Interest の Nonce）
                    parent_nonce = nonce_str

                    # リクエスト名を文字列として取得
                    request_name = Name.to_str(name)

                    # それぞれを Interest で並列でリクエストし、データを集める
                    async def fetch_content(arg, parent_nonce):
                        # 子の Nonce を生成
                        child_nonce = random.randint(0, 2**32 - 1)
                        child_nonce_str = str(child_nonce)

                        # RCT に親子の Nonce を記録
                        self.db_manager.insert_request_chain(parent_nonce, child_nonce_str)

                        # Interest を送信
                        try:
                            return await get_data(self.app, arg, child_nonce_str)
                        except InterestNack as e:
                            logging.info(f'Nacked with reason={e.reason}')
                            return None
                        except InterestTimeout:
                            logging.info(f'Timeout for interest {arg}')
                            return None

                    tasks = [fetch_content(arg, parent_nonce) for arg in args]
                    contents = await asyncio.gather(*tasks)

                    logging.info(f"Data collected: {contents}")

                    # 関数名を取得
                    my_function_name = extract_my_function_name(name)

                    logging.info(f"Function name: {my_function_name}")

                    # 処理前のデータサイズを計算
                    data_size_before = sum(len(arg) for arg in contents if arg is not None)

                    # 処理開始時間を記録
                    start_time = datetime.datetime.now()

                    # 関数を実行
                    result = function_request_handler(my_function_name, contents)

                    # 処理終了時間を記録
                    end_time = datetime.datetime.now()

                    # 処理後のデータサイズを計算
                    data_size_after = len(result)

                    # 処理時間を計算（ミリ秒）
                    processing_time_ms = (end_time - start_time).total_seconds() * 1000

                    # service_logs テーブルにログを挿入
                    self.db_manager.insert_service_log(
                        request_id=parent_nonce,
                        name=request_name,
                        ip_address=self.my_ip,
                        data_size_before=data_size_before,
                        data_size_after=data_size_after,
                        start_time=start_time,
                        end_time=end_time,
                        processing_time_ms=processing_time_ms
                    )

                    logging.info(f"Processing result: {result}")

                    # データをセグメントに分割する
                    seg_cnt = (len(result) + SEGMENT_SIZE - 1) // SEGMENT_SIZE

                    print(f'segmentation count: {seg_cnt}')

                    # パケット分割の時間を計測
                    packets = [self.app.prepare_data(original_name + [Component.from_segment(i)],
                                                result[i*SEGMENT_SIZE:(i+1)*SEGMENT_SIZE],
                                                freshness_period=10000,
                                                final_block_id=Component.from_segment(seg_cnt - 1))
                            for i in range(seg_cnt)]
                    
                    # セグメントデータを保存
                    self.segmented_data[Name.to_str(original_name)] = packets
                    seg_no = 0
                else:
                    seg_no = Component.to_number(name[-1])

                # セグメントデータを送信
                self.app.put_raw_packet(self.segmented_data[Name.to_str(original_name)][seg_no])
                return

            # イベントループで実行
            asyncio.create_task(async_on_interest())
        self.app.run_forever()

    def shutdown(self):
        """
        アプリケーションとデータベース接続を閉じる。
        """
        self.app.shutdown()
        self.db_manager.close()

def function_request_handler(name: str, args: List[bytes]) -> bytes:
    """
    関数リクエストを処理するハンドラ。

    Args:
        name (str): 関数名。
        args (List[bytes]): 引数のリスト。

    Returns:
        bytes: 関数の実行結果。
    """
    args_decoded = [arg.decode() for arg in args if arg is not None]
    args_str = ",".join(args_decoded)
    return f"Hello, {name}! Args: {args_str}".encode()

def data_request_handler(name: str) -> str:
    """
    データリクエストを処理するハンドラ。

    Args:
        name (str): データ名。

    Returns:
        str: データの内容。
    """
    logging.info(f"Data requested for: {name}")
    return "Hello, world!"

if __name__ == '__main__':
    try:
        producer = NDNFunction()
        producer.run('/func_nodeX', function_request_handler, data_request_handler)
    except KeyboardInterrupt:
        logging.info("Application interrupted by user.")
    finally:
        producer.shutdown()
