import datetime
import subprocess
import re
import time
import mysql.connector
from mysql.connector import Error
from abc import ABC, abstractmethod
from enum import Enum
from ndn.encoding import Name, Component, FormalName
import logging
import urllib.parse
from typing import Optional, Dict, Any

def get_original_name(name: FormalName) -> FormalName:
    original_name = ""
    if Component.get_type(name[-1]) == Component.TYPE_SEGMENT:
        original_name = Name.normalize(name[:-1])
    else:
        original_name = Name.normalize(name)
    return original_name

# ロギングの設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')

# データベース接続情報（必要に応じて変更してください）
DB_CONFIG = {
    'host': 'mysql',
    'user': 'user',
    'password': 'pass',
    'database': 'ndn_logs'
}

# tshark コマンド
TSHARK_CMD = [
    "tshark",
    "-i",
    "any",
    "-l",
    "-q",
    "-X",
    "lua_script:/workspaces/lua/ndn.lua",
    "-V"
]

# 正規表現パターンを定義（パケット情報を抽出するため）
source_ip_pattern = re.compile(r'Source Address: (\d+\.\d+\.\d+\.\d+)')
destination_ip_pattern = re.compile(r'Destination Address: (\d+\.\d+\.\d+\.\d+)')
name_pattern = re.compile(r'Name: (/.+?)(?:,|\s|$)')
nonce_pattern = re.compile(r'Nonce: (\d+)')
interest_lifetime_pattern = re.compile(r'InterestLifetime: (\d+)')
packet_type_pattern = re.compile(r'Named Data Networking \(NDN\), (Interest|Data)')
arrival_time_pattern = re.compile(r'Arrival Time: (.+)')
final_block_id_pattern = re.compile(r'FinalBlockId:\s*50=%([^,\s]+)')

# 無視するルーターの名前一覧
ROUTER_NAMES = ["/ndn/waseda/%C1.Router"]

class DatabaseManager:
    """
    データベースへの接続と操作を管理するクラス。
    """
    INSERT_PACKET_LOG_QUERY = """
    INSERT INTO packet_logs (request_id, name, packet_type, source_ip, destination_ip, node_ip, received_time)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
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
        create_table_query = """
        CREATE TABLE IF NOT EXISTS packet_logs (
            id INT AUTO_INCREMENT PRIMARY KEY,
            request_id VARCHAR(255),
            name VARCHAR(1024),
            packet_type INT,
            source_ip VARCHAR(45),
            destination_ip VARCHAR(45),
            node_ip VARCHAR(45),
            received_time DATETIME(6)
        );
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(create_table_query)
            self.connection.commit()
            logging.info("Table 'packet_logs' is ready.")
        except Error as e:
            logging.error(f"Error creating table: {e}")
            self.connection.rollback()
        finally:
            cursor.close()

    def insert_log(self, log_data: 'LogData') -> None:
        """
        ログデータをデータベースに挿入する。

        Args:
            log_data (LogData): 挿入するログデータ。
        """
        cursor = self.connection.cursor()
        try:
            cursor.execute(self.INSERT_PACKET_LOG_QUERY, log_data.to_tuple())
            self.connection.commit()
            logging.info(f"Packet log inserted: {log_data.to_dict()}")
        except Error as e:
            logging.error(f"Error inserting packet log: {e}")
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

class Packet(ABC):
    """
    パケットの抽象基底クラス。
    """
    def __init__(self, source_ip: str, destination_ip: str, name: str, received_time: Optional[datetime.datetime] = None):
        """
        コンストラクタ。

        Args:
            source_ip (str): 送信元IPアドレス。
            destination_ip (str): 送信先IPアドレス。
            name (str): パケットのNameフィールド。
            received_time (datetime.datetime, optional): パケットの受信時刻。
        """
        self.source_ip = source_ip
        self.destination_ip = destination_ip
        # URLデコードしておく
        self.name = urllib.parse.unquote(name)
        self.received_time = received_time or datetime.datetime.now()

    @abstractmethod
    def process(self) -> None:
        """
        パケットの処理を行う抽象メソッド。
        """
        pass

class InterestPacket(Packet):
    """
    Interestパケットを表すクラス。
    """
    def __init__(self, source_ip: str, destination_ip: str, name: str, nonce: str, received_time: Optional[datetime.datetime] = None):
        """
        コンストラクタ。

        Args:
            source_ip (str): 送信元IPアドレス。
            destination_ip (str): 送信先IPアドレス。
            name (str): パケットのNameフィールド。
            nonce (str): パケットのNonceフィールド。
            received_time (datetime.datetime, optional): パケットの受信時刻。
        """
        super().__init__(source_ip, destination_ip, name, received_time=received_time)
        self.nonce = nonce

    def process(self) -> None:
        """
        Interestパケットの処理を行う。
        """
        logging.debug(f"Processing InterestPacket: {self.__dict__}")

class DataPacket(Packet):
    """
    Dataパケットを表すクラス。
    """
    def __init__(self, source_ip: str, destination_ip: str, name: str, final_block_id: Optional[str] = None, received_time: Optional[datetime.datetime] = None):
        """
        コンストラクタ。

        Args:
            source_ip (str): 送信元IPアドレス。
            destination_ip (str): 送信先IPアドレス。
            name (str): パケットのNameフィールド。
            final_block_id (str, optional): パケットのFinalBlockIdフィールド。
            received_time (datetime.datetime, optional): パケットの受信時刻。
        """
        super().__init__(source_ip, destination_ip, name, received_time=received_time)
        self.final_block_id = final_block_id

    def process(self) -> None:
        """
        Dataパケットの処理を行う。
        """
        logging.debug(f"Processing DataPacket: {self.__dict__}")

class LogData(ABC):
    """
    ログデータの抽象基底クラス。
    """
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """
        ログデータを辞書形式に変換する。

        Returns:
            Dict[str, Any]: ログデータの辞書。
        """
        pass

    @abstractmethod
    def to_tuple(self) -> tuple:
        """
        ログデータをタプル形式に変換する（データベース挿入用）。

        Returns:
            tuple: ログデータのタプル。
        """
        pass

class PacketType(Enum):
    """
    パケットの種類を表す列挙型。
    """
    INTEREST = 0
    DATA = 1

class PacketLogData(LogData):
    """
    パケットのログデータクラス。
    """
    def __init__(self, packet: Packet, packet_type: PacketType, request_id: str, node_ip: str):
        """
        コンストラクタ。

        Args:
            packet (Packet): ログ化するパケット。
            packet_type (PacketType): パケットの種類。
            request_id (str): パケットのリクエストID（Nonce）。
            node_ip (str): 自身のIPアドレス。
        """
        self.request_id: str = request_id
        self.name: str = packet.name
        self.packet_type: PacketType = packet_type
        self.source_ip: str = packet.source_ip
        self.destination_ip: str = packet.destination_ip
        self.received_time: datetime.datetime = packet.received_time
        self.node_ip: str = node_ip

    def to_dict(self) -> Dict[str, Any]:
        """
        ログデータを辞書形式に変換する。

        Returns:
            Dict[str, Any]: ログデータの辞書。
        """
        data = {
            'request_id': self.request_id,
            'name': self.name,
            'packet_type': self.packet_type.value,
            'source_ip': self.source_ip,
            'destination_ip': self.destination_ip,
            'node_ip': self.node_ip,
            'received_time': self.received_time.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3],
        }
        return data

    def to_tuple(self) -> tuple:
        """
        ログデータをタプル形式に変換する。

        Returns:
            tuple: ログデータのタプル。
        """
        return (
            self.request_id,
            self.name,
            self.packet_type.value,
            self.source_ip,
            self.destination_ip,
            self.node_ip,
            self.received_time,
        )

class LogAgent:
    """
    パケットのログを管理するエージェントクラス。
    """
    def __init__(self, db_manager: DatabaseManager):
        """
        コンストラクタ。

        Args:
            db_manager (DatabaseManager): データベースマネージャーのインスタンス。
        """
        self.db_manager = db_manager
        self.incoming_pitl: Dict[str, InterestPacket] = {}
        self.outgoing_pitl: Dict[str, InterestPacket] = {}
        self.my_ip = self._get_my_ip()

    def _get_my_ip(self) -> str:
        """
        自身のIPアドレスを取得する。

        Returns:
            str: 自身のIPアドレス。
        """
        # 自身のIPアドレスを取得
        my_ip = subprocess.run(["hostname", "-I"], stdout=subprocess.PIPE, text=True).stdout.strip()
        my_ip = my_ip.split()[0]  # 複数のIPが返される場合、最初のものを使用
        logging.info(f"My IP address: {my_ip}")
        return my_ip

    def log_interest(self, packet: InterestPacket) -> None:
        """
        Interestパケットのログ処理を行う。
        自身のIPを参照し、Incoming の時と Outgoing の時で分ける。

        Args:
            packet (InterestPacket): 処理するInterestパケット。
        """
        # 自身のIPを参照して方向を判定
        if packet.source_ip == self.my_ip:
            # 自身が送信した Interest（Outgoing）
            self.outgoing_pitl[packet.nonce] = packet
        elif packet.destination_ip == self.my_ip:
            # 自身が受信した Interest（Incoming）
            self.incoming_pitl[packet.nonce] = packet
        else:
            # 関係のないパケット
            return

        # パケットログをデータベースに挿入
        log_data = PacketLogData(packet, PacketType.INTEREST, packet.nonce, self.my_ip)
        self.db_manager.insert_log(log_data)

    def log_data(self, data_packet: DataPacket) -> None:
        """
        Dataパケットのログ処理を行う。

        Args:
            data_packet (DataPacket): 処理するDataパケット。
        """
        # Data が Incoming の場合
        if data_packet.destination_ip == self.my_ip:
            # 対応する Outgoing Interest を検索
            for nonce, interest_packet in list(self.outgoing_pitl.items()):
                if (interest_packet.destination_ip == data_packet.source_ip and
                    interest_packet.name == data_packet.name):
                    # マッチング成功
                    log_data = PacketLogData(data_packet, PacketType.DATA, interest_packet.nonce, self.my_ip)
                    self.db_manager.insert_log(log_data)
                    # 対応した Interest を削除
                    del self.outgoing_pitl[nonce]
                    break
            else:
                logging.warning(f"No matching Outgoing Interest found for Incoming Data packet: {data_packet.name}")
        # Data が Outgoing の場合
        elif data_packet.source_ip == self.my_ip:
            # 対応する Incoming Interest を検索
            for nonce, interest_packet in list(self.incoming_pitl.items()):
                if (interest_packet.source_ip == data_packet.destination_ip and
                    interest_packet.name == data_packet.name):
                    # マッチング成功
                    log_data = PacketLogData(data_packet, PacketType.DATA, interest_packet.nonce, self.my_ip)
                    self.db_manager.insert_log(log_data)
                    # 対応した Interest を削除
                    del self.incoming_pitl[nonce]
                    break
            else:
                logging.warning(f"No matching Incoming Interest found for Outgoing Data packet: {data_packet.name}")
        else:
            # 自ノードに関係ないパケット
            pass

    def close(self) -> None:
        """
        データベース接続を閉じる。
        """
        self.db_manager.close()


def main() -> None:
    """
    メイン関数。tsharkの出力を解析し、パケット情報をデータベースに保存する。
    """
    db_manager = DatabaseManager(DB_CONFIG)
    log_agent = LogAgent(db_manager)

    try:
        # tsharkコマンドを実行し、パケット情報を取得
        with subprocess.Popen(TSHARK_CMD, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) as proc:
            # パケット情報の初期化
            source_ip: Optional[str] = None
            destination_ip: Optional[str] = None
            name: Optional[str] = None
            nonce: Optional[str] = None
            packet_type: Optional[str] = None
            arrival_time: Optional[datetime.datetime] = None
            final_block_id: Optional[str] = None

            for line in proc.stdout:
                # パケットタイプを検出
                packet_type_match = packet_type_pattern.search(line)
                if packet_type_match:
                    packet_type = packet_type_match.group(1)

                # Arrival Time を検出
                arrival_time_match = arrival_time_pattern.search(line)
                if arrival_time_match:
                    arrival_time_str = arrival_time_match.group(1).strip()
                    # タイムゾーンを削除（必要に応じて調整）
                    if 'JST' in arrival_time_str:
                        arrival_time_str = arrival_time_str.replace('JST', '').strip()
                        tzinfo = datetime.timezone(datetime.timedelta(hours=9))  # JSTタイムゾーン
                    else:
                        tzinfo = None
                    # ナノ秒をマイクロ秒に変換
                    time_parts = arrival_time_str.split('.')
                    if len(time_parts) == 2:
                        time_without_frac = time_parts[0]
                        frac_seconds = time_parts[1][:6]  # 最初の6桁をマイクロ秒として使用
                        arrival_time_str = f"{time_without_frac}.{frac_seconds}"
                    else:
                        # フラクショナルセカンドがない場合
                        pass
                    try:
                        arrival_time = datetime.datetime.strptime(arrival_time_str, '%b %d, %Y %H:%M:%S.%f')
                        if tzinfo:
                            arrival_time = arrival_time.replace(tzinfo=tzinfo)
                        else:
                            arrival_time = arrival_time.replace(tzinfo=datetime.timezone.utc)
                        # UTCに変換
                        arrival_time = arrival_time.astimezone(datetime.timezone.utc)
                    except ValueError as e:
                        logging.error(f"Error parsing arrival time: {e}")
                        arrival_time = None

                # 送信元IPを検出
                source_ip_match = source_ip_pattern.search(line)
                if source_ip_match:
                    source_ip = source_ip_match.group(1)

                # 送信先IPを検出
                destination_ip_match = destination_ip_pattern.search(line)
                if destination_ip_match:
                    destination_ip = destination_ip_match.group(1)

                # Nameフィールドを検出
                name_match = name_pattern.search(line)
                if name_match:
                    name = name_match.group(1)

                # FinalBlockIdを検出
                final_block_id_match = final_block_id_pattern.search(line)
                if final_block_id_match:
                    final_block_id = final_block_id_match.group(1)

                # Interestパケットの場合、Nonceを検出
                if packet_type == "Interest":
                    nonce_match = nonce_pattern.search(line)
                    if nonce_match:
                        nonce = nonce_match.group(1)

                # Interestパケットのログを保存する
                if packet_type == "Interest" and all([source_ip, destination_ip, name, nonce, arrival_time]):
                    # 無視するパケットをフィルタリング
                    if "localhop" in name or "localhost" in name:
                        continue

                    if any(router_name in name for router_name in ROUTER_NAMES):
                        continue

                    # Name構造に変換し、セグメントが含まれる場合は処理をスキップ
                    name_structure = Name.from_str(name)
                    if Component.get_type(name_structure[-1]) == Component.TYPE_SEGMENT:
                        continue

                    original_name = Name.to_str(get_original_name(name_structure))

                    # セグメントが無い(つまり最初のパケットの)Interestパケットを処理
                    packet = InterestPacket(source_ip, destination_ip, original_name, nonce, received_time=arrival_time)
                    packet.process()
                    log_agent.log_interest(packet)

                    # 変数をリセット
                    packet_type = source_ip = destination_ip = name = nonce = arrival_time = None

                # Dataパケットのログを保存する
                elif packet_type == "Data" and all([source_ip, destination_ip, name, arrival_time, final_block_id]):
                    # 無視するパケットをフィルタリング
                    if "localhop" in name or "localhost" in name:
                        continue

                    if any(router_name in name for router_name in ROUTER_NAMES):
                        continue

                    # Name構造に変換し、セグメントを解析し、final_block_id が一致していなければ飛ばす
                    name_structure = Name.from_str(name)

                    original_name = Name.to_str(get_original_name(name_structure))

                    if Component.get_type(name_structure[-1]) != Component.TYPE_SEGMENT:
                        continue
                    if Component.to_number(name_structure[-1]) != int(final_block_id):
                        continue

                    # Dataパケットを処理
                    packet = DataPacket(source_ip, destination_ip, original_name, final_block_id=final_block_id, received_time=arrival_time)
                    packet.process()
                    log_agent.log_data(packet)

                    # 変数をリセット
                    packet_type = source_ip = destination_ip = name = arrival_time = final_block_id = None

    except KeyboardInterrupt:
        logging.info("Interrupted by user.")
    except Exception as e:
        logging.error(f"An error occurred: {e}")
    finally:
        # リソースを解放
        log_agent.close()

if __name__ == "__main__":
    main()
