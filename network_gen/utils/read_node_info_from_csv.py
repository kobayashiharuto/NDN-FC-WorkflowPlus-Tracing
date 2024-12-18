import csv

from collections import defaultdict

class NodeInfo:
    def __init__(self, node_name: str, command: str):
        self.node_name = node_name
        self.command = command

# ノードの情報をCSVファイルから読み込む関数
def read_node_info_from_csv(csv_file: str) -> dict[str, NodeInfo]:
    """
    CSVファイルからノードの情報を読み込み、ノード名をキー、NodeInfo オブジェクトを値とする辞書を返す関数。

    Args:
        csv_file (str): CSVファイルのパス

    Returns:
        dict: ノード名をキー、NodeInfo オブジェクトを値とする辞書
        
    """
    node_infos = {}

    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # ヘッダー行をスキップ
        for row in reader:
            node_name, command = row 
            node_infos[node_name] = NodeInfo(node_name=node_name, command=command)

    return node_infos