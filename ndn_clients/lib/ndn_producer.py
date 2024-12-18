from time import time
from typing import Callable, Optional
from ndn.app import NDNApp
from ndn.encoding import Name, InterestParam, BinaryStr, FormalName, MetaInfo
import logging
from ndn.encoding import Name, Component

import os

from lib.ndn_utils import SEGMENT_SIZE, get_original_name


logging.basicConfig(format='[{asctime}]{levelname}:{message}',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO,
                    style='{')


class NDNProducer:
    def __init__(self):
        self.app = NDNApp()
        self.segmented_data = {}

    def run(self, prefix: str, data_request_handler: Callable[[str], str]):
        """
        プレフィックスに対してデータハンドラを登録して起動
        Args:
            prefix (str): プレフィックス
            data_request_handler (Callable[[str], str]): データハンドラ (名前) -> データ
        """
        # nlsrc advertise [prefix] というコマンドで prefix を広告
        os.system(f"nlsrc advertise {prefix}")

        @self.app.route(prefix)
        def on_interest(name: FormalName, param: InterestParam, _app_param: Optional[BinaryStr]):
            # nonce を出力する
            print(f"NONCE: {param.nonce}")
            print(f'>> I: {Name.to_str(name)}, {param}')

            original_name = get_original_name(name)

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

        self.app.run_forever()


def on_interest(name: str) -> str:
    print(f"Interest: {name}")
    return "hello"

if __name__ == '__main__':
    producer = NDNProducer()
    producer.run('/nodeX', on_interest)
    