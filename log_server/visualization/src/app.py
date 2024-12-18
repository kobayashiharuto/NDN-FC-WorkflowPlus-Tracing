from flask import Flask, jsonify, request
from database import connect_db
from utils import (
    get_related_nonces, get_packet_logs, deduce_roles,
    generate_nodes, generate_edges,
    calculate_node_processing_times, calculate_edge_latencies,
    get_service_processing_times  # 必要な関数をインポート
)

app = Flask(__name__)

@app.route("/nodes", methods=["GET"])
def get_nodes():
    request_id = request.args.get("request_id")
    if not request_id:
        return jsonify({"error": "request_id is required"}), 400

    connection = connect_db()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500

    chain_dict = {}
    visited = set()
    get_related_nonces(connection, request_id, chain_dict, visited)
    all_nonces = visited.union(set(chain_dict.keys()))

    logs = get_packet_logs(connection, list(all_nonces))
    roles = deduce_roles(logs)

    # ノードの処理時間を計算
    node_processing_times = calculate_node_processing_times(logs)

    # サービスの処理時間を取得
    service_processing_times = get_service_processing_times(connection, list(all_nonces))

    # ノードデータを生成
    nodes = generate_nodes(roles, node_processing_times, service_processing_times)

    connection.close()
    return jsonify(nodes)

@app.route("/edges", methods=["GET"])
def get_edges():
    request_id = request.args.get("request_id")
    if not request_id:
        return jsonify({"error": "request_id is required"}), 400

    connection = connect_db()
    if not connection:
        return jsonify({"error": "Database connection failed"}), 500

    chain_dict = {}
    visited = set()
    get_related_nonces(connection, request_id, chain_dict, visited)
    all_nonces = visited.union(set(chain_dict.keys()))

    logs = get_packet_logs(connection, list(all_nonces))

    # 役割の推測（必要であれば）
    roles = deduce_roles(logs)

    # エッジの遅延時間を計算
    edge_latencies = calculate_edge_latencies(logs)

    # エッジデータを生成
    edges = generate_edges(logs, edge_latencies)

    connection.close()
    return jsonify(edges)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
