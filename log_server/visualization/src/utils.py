import datetime
from collections import defaultdict

def get_related_nonces(connection, parent_nonce, chain_dict, visited):
    if parent_nonce in visited:
        return
    visited.add(parent_nonce)

    cursor = connection.cursor()
    query = "SELECT child_nonce FROM request_chain WHERE parent_nonce = %s"
    cursor.execute(query, (parent_nonce,))
    child_nonces = cursor.fetchall()

    for (child_nonce,) in child_nonces:
        chain_dict.setdefault(parent_nonce, []).append(child_nonce)
        get_related_nonces(connection, child_nonce, chain_dict, visited)

    cursor.close()

def get_packet_logs(connection, nonces):
    cursor = connection.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(nonces))
    query = f"""
        SELECT *, node_ip FROM packet_logs
        WHERE request_id IN ({format_strings})
        ORDER BY received_time
    """
    cursor.execute(query, tuple(nonces))
    logs = cursor.fetchall()
    cursor.close()
    return logs

def calculate_node_processing_times(logs):
    """
    各ノードの処理時間を計算します。
    """
    node_times = {}

    # ノードごとにログを整理
    logs_by_node = {}
    for log in logs:
        node_ip = log['node_ip']
        if node_ip not in logs_by_node:
            logs_by_node[node_ip] = []
        logs_by_node[node_ip].append(log)

    # 各ノードの処理時間を計算
    for node_ip, node_logs in logs_by_node.items():
        # 受信時間でソート
        node_logs_sorted = sorted(node_logs, key=lambda x: x['received_time'])
        total_processing_time = datetime.timedelta()
        count = 0
        for i in range(len(node_logs_sorted) - 1):
            current_log = node_logs_sorted[i]
            next_log = node_logs_sorted[i + 1]
            # ノードがパケットを受信してから送信するまでの時間を計算
            if current_log['destination_ip'] == node_ip and next_log['source_ip'] == node_ip:
                processing_time = next_log['received_time'] - current_log['received_time']
                total_processing_time += processing_time
                count += 1

        # 平均処理時間を計算
        if count > 0:
            average_processing_time = total_processing_time / count
            node_times[node_ip] = average_processing_time.total_seconds() * 1000  # ミリ秒に変換
        else:
            node_times[node_ip] = 0.0

    return node_times

def calculate_edge_latencies(logs):
    """
    エッジ間の遅延時間を計算します。
    """
    edge_times = {}

    # パケットごとにログを整理
    packet_logs = defaultdict(list)
    for log in logs:
        key = (log['request_id'], log['packet_type'], log['name'])
        packet_logs[key].append(log)

    # 各パケットの遅延時間を計算
    for key, packets in packet_logs.items():
        # パケットを受信時間でソート
        packets_sorted = sorted(packets, key=lambda x: x['received_time'])
        for i in range(len(packets_sorted) - 1):
            current_log = packets_sorted[i]
            next_log = packets_sorted[i + 1]
            if current_log['source_ip'] == current_log['node_ip'] and next_log['destination_ip'] == next_log['node_ip']:
                latency = (next_log['received_time'] - current_log['received_time']).total_seconds() * 1000  # ミリ秒に変換
                edge_key = (current_log['source_ip'], next_log['destination_ip'], current_log['packet_type'], current_log['request_id'])
                edge_times[edge_key] = latency

    return edge_times


def deduce_roles(logs):
    roles = {}
    ip_stats = {}

    for log in logs:
        packet_type = log['packet_type']
        source_ip = log['source_ip']
        destination_ip = log['destination_ip']
        name = log['name']

        # IPの統計情報を初期化
        for ip in [source_ip, destination_ip]:
            if ip and ip not in ip_stats:
                ip_stats[ip] = {
                    'interest_sent': 0,
                    'interest_received': 0,
                    'data_sent': 0,
                    'data_received': 0,
                    'interest_names_sent': set(),
                    'interest_names_received': set(),
                }

        # 統計情報の更新
        if packet_type == 0:  # Interestパケット
            if source_ip:
                ip_stats[source_ip]['interest_sent'] += 1
                ip_stats[source_ip]['interest_names_sent'].add(name)
            if destination_ip:
                ip_stats[destination_ip]['interest_received'] += 1
                ip_stats[destination_ip]['interest_names_received'].add(name)
        elif packet_type == 1:  # Dataパケット
            if source_ip:
                ip_stats[source_ip]['data_sent'] += 1
            if destination_ip:
                ip_stats[destination_ip]['data_received'] += 1

    # 役割の推測
    for ip, stats in ip_stats.items():
        interest_sent = stats['interest_sent']
        interest_received = stats['interest_received']
        data_sent = stats['data_sent']
        data_received = stats['data_received']
        sent_names = stats['interest_names_sent']
        received_names = stats['interest_names_received']

        # サービスの判定：新しいInterestを送信する（受信したInterestの名前とは異なるInterestを送信する）
        if interest_sent > 0 and interest_received > 0:
            if not sent_names.issubset(received_names):
                role = 'Service'
            else:
                role = 'Router'
        # ルーターの判定：Interestを受信し、同じ名前のInterestを送信する
        elif interest_received > 0 and interest_sent > 0:
            if sent_names == received_names:
                role = 'Router'
            else:
                role = 'Unknown'
        # プロデューサーの判定
        elif interest_received > 0 and data_sent > 0:
            role = 'Producer'
        # コンシューマーの判定
        elif interest_sent > 0 and data_received > 0:
            role = 'Consumer'
        else:
            role = 'Unknown'

        roles[ip] = role

    return roles

def get_service_processing_times(connection, nonces):
    """
    指定されたリクエストID（nonce）に対応するサービスの処理時間を取得します。
    """
    cursor = connection.cursor(dictionary=True)
    format_strings = ','.join(['%s'] * len(nonces))
    query = f"""
        SELECT ip_address, processing_time_ms
        FROM service_logs
        WHERE request_id IN ({format_strings})
    """
    cursor.execute(query, tuple(nonces))
    results = cursor.fetchall()
    cursor.close()

    # IPアドレスをキーとした辞書を作成
    processing_times = {}
    for row in results:
        ip = row['ip_address']
        processing_time = row['processing_time_ms']
        processing_times[ip] = processing_time
    return processing_times

def generate_nodes(roles, node_processing_times, service_processing_times):
    NODES = []
    color_map = {
        'Consumer': 'green',
        'Producer': 'orange',
        'Service': '#F24F4FFF',
        'Router': '#4169e1',
        'Unknown': 'gray'
    }
    icon_map = {
        'Consumer': 'user',
        'Producer': 'database',
        'Service': 'brackets-curly',
        'Router': 'exchange-alt',
        'Unknown': 'question'
    }

    for ip, role in roles.items():
        # サービスノードの場合、サービスの処理時間を優先して表示
        if role == 'Service':
            processing_time = service_processing_times.get(ip)
            if processing_time:
                main_stat = f"{processing_time:.2f} ms"
            else:
                # サービスの処理時間が取得できない場合は、ノードの処理時間を表示
                processing_time = node_processing_times.get(ip, 0.0)
                main_stat = f"{processing_time:.2f} ms" if processing_time > 0 else role
        else:
            # 他のノードの場合、ノードの処理時間を表示
            processing_time = node_processing_times.get(ip, 0.0)
            main_stat = f"{processing_time:.2f} ms" if processing_time > 0 else role

        node = {
            "id": ip,
            "title": f"{role} ({ip})" if role != 'Consumer' else role,
            "mainStat": main_stat,
            "subTitle": main_stat if role != 'Consumer' else '',
            "icon": icon_map.get(role, 'question'),
            "color": color_map.get(role, 'gray')
        }
        NODES.append(node)

    return NODES

def generate_edges(logs, edge_latencies):
    EDGES = []
    idx = 0
    for log in logs:
        source_ip = log['source_ip']
        destination_ip = log['destination_ip']
        packet_type = log['packet_type']
        request_id = log['request_id']

        if source_ip and destination_ip:
            edge_key = (source_ip, destination_ip, packet_type, request_id)
            latency = edge_latencies.get(edge_key, 0.0)
            edge = {
                "id": f"{idx}",
                "source": source_ip,
                "target": destination_ip,
                "mainStat": f"{latency:.2f} ms",
                "secondaryStat": "Interest" if packet_type == 0 else "Data"
            }
            EDGES.append(edge)
            idx += 1

    return EDGES