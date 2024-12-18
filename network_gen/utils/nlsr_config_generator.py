import csv

from jinja2 import Template

# NLSR設定ファイルのテンプレート
# neighbor の部分には、隣接ノードのIPアドレスをリストで指定
# my_node_name には自身のノード名を指定
# docker の DNS が解決してくれるので、ノード名を直接指定する
nlsr_template = Template('''\
general {
  network /ndn
  site /waseda
  router /%C1.Router/{{ my_node_name }}
  lsa-refresh-time 1800
  lsa-interest-lifetime 4
  sync-protocol psync
  sync-interest-lifetime 60000
  state-dir /var/lib/nlsr
}
neighbors {
  {%- for neighbor in neighbors %}
  neighbor {
    name /ndn/waseda/%C1.Router/{{ neighbor }}
    face-uri tcp4://{{ neighbor }}
    link-cost 10
  }
  {%- endfor %}
}
fib {
  max-faces-per-prefix 3
  routing-calc-interval 15
}
security {
  validator {
    trust-anchor {
      type any
    }
  }
  prefix-update-validator {
    trust-anchor {
      type any
    }
  }
}
''')

# 隣接ノードの集合を受け取り、NLSR設定を返す
def nlsr_config_generator(my_node_name: str, neighbors: set[str]) -> str:
    """
    隣接ノードの集合を受け取り、NLSR設定の文字列を返す関数。

    Args:
        neighbors (set[str]): 隣接ノードの集合
        my_node_name (str): 自身のノード名

    Returns:
        str: NLSR設定
    """
    return nlsr_template.render(neighbors=neighbors, my_node_name=my_node_name)

if __name__ == '__main__':
    neighbors = {
        'node2',
        'node3'
    }
    print(nlsr_config_generator('node1', neighbors))