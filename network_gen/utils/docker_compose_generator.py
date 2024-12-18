from jinja2 import Template

# Docker Compose ファイルのテンプレート
# サービスの部分には、各ノードの情報を入れる
docker_compose_template = Template('''\
version: "3"
                                   
networks:
  tempo_network:
    external: true  
    driver: bridge

services:
  mysql:
    image: mysql:8.0
    container_name: mysql
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: ndn_logs
      MYSQL_USER: user
      MYSQL_PASSWORD: pass
    volumes:
      - ../config/init.sql:/docker-entrypoint-initdb.d/init.sql
    networks:
      - tempo_network
    ports:
      - "3306:3306"  # ホストからアクセスする必要がある場合のみ
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      retries: 5
      start_period: 10s
{{ services }}
''')

# docker compose ファイルにおけるサービス部分単体のテンプレート
# node_name にはノード名、enviroments には環境変数の辞書、command にはコマンドを入れる
service_template = Template('''\
  {{ node_name }}:
    build:
      context: .
    working_dir: /workspaces
    cap_add:
      - NET_RAW
      - NET_ADMIN
    networks:
      - tempo_network
    volumes:
      - ..:/workspaces
    tty: true
    stdin_open: true
    depends_on:
      mysql:
        condition: service_healthy
    command: {{ command }}
    environment:
      {%- for env_name, env_value in enviroments.items() %}
      - {{ env_name }}={{ env_value }}
      {%- endfor -%}
''')


# 以上のような構造の、ノード名、環境変数の辞書とコマンドを持つデータ構造
class NodeInfoForDockerCompose:
    def __init__(self, node_name: str, environments: dict[str, str], command: str):
        self.node_name = node_name
        self.environments = environments
        self.command = command


# ノードの情報を受け取り、Docker Compose の内容の文字列を生成する関数
def docker_compose_generator(node_infos: list[NodeInfoForDockerCompose]) -> str:
    """
    ノードの情報を受け取り、Docker Compose の内容の文字列を生成する関数。

    Args:
        node_infos (list[NodeInfo]): ノードの情報

    Returns:
        str: Docker Compose の内容
    """
    services = ''
    for node_info in node_infos:
        service = service_template.render(
            node_name=node_info.node_name, 
            enviroments=node_info.environments,
            command=node_info.command
        )
        services += service + '\n'
    return docker_compose_template.render(services=services)


if __name__ == '__main__':
    # ノードの情報を作成
    node_infos = [
        NodeInfoForDockerCompose(node_name='ndn-node-1', environments={'FUNCITON_FILE_PATH': '/workspaces/config/function/function-a.py', 'NLSR_CONFIG_FILE_PATH': '/workspaces/generated/nlsr/nlsr-1.conf'}, command='bash -c " ./restart.sh && ./auto_nlsr.sh && tail -f /dev/null"'),
        NodeInfoForDockerCompose(node_name='ndn-node-2', environments={'FUNCITON_FILE_PATH': '/workspaces/config/function/function-a.py', 'NLSR_CONFIG_FILE_PATH': '/workspaces/generated/nlsr/nlsr-2.conf'}, command='bash -c " ./restart.sh && ./auto_nlsr.sh && tail -f /dev/null"'),
        NodeInfoForDockerCompose(node_name='ndn-node-3', environments={'FUNCITON_FILE_PATH': '/workspaces/config/function/function-a.py', 'NLSR_CONFIG_FILE_PATH': '/workspaces/generated/nlsr/nlsr-3.conf'}, command='bash -c " ./restart.sh && ./auto_nlsr.sh && tail -f /dev/null"')
    ]

    # Docker Compose ファイルを生成
    docker_compose = docker_compose_generator(node_infos)
    print(docker_compose)