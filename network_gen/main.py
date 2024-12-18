import os
import shutil
import argparse

from utils.read_network_relations_from_csv import read_network_relations_from_csv
from utils.docker_compose_generator import NodeInfoForDockerCompose, docker_compose_generator
from utils.nlsr_config_generator import nlsr_config_generator
from utils.read_node_info_from_csv import read_node_info_from_csv

# ネットワーク関係のCSVファイルのパス
NETWORK_RELATIONS_PATH = './config/network_relations.csv'

# ノード情報のCSVファイルのパス
NODE_INFO_PATH = './config/node_info.csv'

# docker-compose.yml に使う dockerfile のパス
DOCKERFILE_PATH = './config/dockerfile'

# Dockerfileのコピー元パス
DOCKERFILE_ORIGIN_PATH = './config/dockerfile'

# requirements.txt のコピー元パス
REQUIREMENTS_PATH = './config/requirements.txt'

# 生成したファイルを保存するパスたち
GENERATE_DIR = './generated'
DOCKER_COMPOSE_PATH = GENERATE_DIR + '/docker-compose.yml'
NLSR_CONFIG_DIR = GENERATE_DIR + '/nlsr'                          

# ファイルを生成して実行します
def main(no_cache):
    # 生成先のディレクトリを作成、あるいはすでに存在する場合は削除して作り直す
    if os.path.exists(GENERATE_DIR):
        shutil.rmtree(GENERATE_DIR)
    os.makedirs(NLSR_CONFIG_DIR)

    # ネットワーク関係を読み込む
    relations = read_network_relations_from_csv(NETWORK_RELATIONS_PATH)
    print(relations)
    
    # NLSR設定ファイルを生成
    for node, neighbors in relations.items():
        nlsr_config = nlsr_config_generator(my_node_name=node, neighbors=neighbors)
        with open(f'{NLSR_CONFIG_DIR}/{node}.conf', 'w') as f:
            f.write(nlsr_config)
    
    # ノード情報を読み込む
    node_infos = read_node_info_from_csv(NODE_INFO_PATH)
    
    # 情報を加工して Docker Compose ファイルを生成
    node_info_for_docker_compose = []
    for node in relations.keys():
        command = node_infos[node].command

        # もしコマンドが空文字列だった場合、デフォルトのコマンドを設定
        if command == '':
            command = 'tail -f /dev/null'

        node_info_for_docker_compose.append(NodeInfoForDockerCompose(
            node_name=node,
            environments={
                'NLSR_CONFIG_FILE_PATH': f'/workspaces/generated/nlsr/{node}.conf'
            },
            command=f'bash -c " ./shell/restart.sh && ./shell/auto_nlsr.sh 1 && {command}"'
        ))
    
    docker_compose = docker_compose_generator(node_info_for_docker_compose)
    with open(DOCKER_COMPOSE_PATH, 'w') as f:
        f.write(docker_compose)

    # Dockerfile を docker-compose.yml と同じディレクトリにコピー
    shutil.copy(DOCKERFILE_ORIGIN_PATH, GENERATE_DIR)

    # requirements.txt を docker-compose.yml と同じディレクトリにコピー
    shutil.copy(REQUIREMENTS_PATH, GENERATE_DIR)
    
    # 生成結果のログ、ファイル一覧を日本語で表示
    print('生成が完了しました。')
    print('以下のファイルが生成されました。')
    print(f'  - {DOCKER_COMPOSE_PATH}')
    for nlsr_config_file in os.listdir(NLSR_CONFIG_DIR):
        print(f'  - {NLSR_CONFIG_DIR}/{nlsr_config_file}')

    # 生成したディレクトリにて、docker compose up --build を実行
    os.chdir(GENERATE_DIR)
    
    # no_cache フラグに基づいてコマンドを作成
    build_command = 'docker compose build'
    if no_cache:
        build_command += ' --no-cache'
    
    os.system(f'{build_command} && docker compose up')

if __name__ == '__main__':
    # コマンドライン引数をパース
    parser = argparse.ArgumentParser(description='Docker Compose Build and Run Script')
    parser.add_argument('--no-cache', action='store_true', help='Add --no-cache option to docker compose build')
    args = parser.parse_args()

    # main関数に引数を渡して実行
    main(no_cache=args.no_cache)
