import csv

from collections import defaultdict


# ネットワーク関係を読み込む関数
def read_network_relations_from_csv(csv_file: str) -> dict[str, set[str]]:
    """
    CSVファイルからネットワーク関係を読み込み、隣接ノードの集合を持つ辞書を返す関数。

    Args:
        csv_file (str): CSVファイルのパス

    Returns:
        dict: ノード名をキー、隣接ノードの集合を値とする辞書 (例: {'node1': {'node2', 'node3'}, 'node2': {'node1'}, 'node3': {'node1'}})
        
    """
    relations = defaultdict(set)

    with open(csv_file, 'r') as f:
        reader = csv.reader(f)
        next(reader)  # ヘッダー行をスキップ
        for row in reader:
            node1, node2 = row  # 1行に2つのノードがあると仮定
            relations[node1].add(node2)
            relations[node2].add(node1)  # 双方向の関係を考慮

    return relations

if __name__ == '__main__':
    relations = read_network_relations_from_csv('./config/network_relations.csv')
    print(relations)