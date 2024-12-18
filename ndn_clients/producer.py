from time import sleep
from lib.ndn_producer import NDNProducer
import sys

def on_interest(name: str) -> str:
    print(f"Interest: {name}")
    # name のスラッシュをスペースにして返す
    # return name[1:].replace("/", " ")
    return "1helllohelllohelllohelllo2helllohelllohelllohelllo3helllohelllohelllohelllo4helllohelllohelllohelllo5helllohelllohelllohelllo6hhelllohelllohellloelllo7helllohelllohelllohelllo8helllohelllohelllohelllo9!helllohelllohelllohelllohelllohelllohelllo!!!!!"
    # return "Hello, world!!!!!!"

if __name__ == '__main__':
    producer = NDNProducer()
    # ここで引数からprefixを取得する
    if len(sys.argv) < 2:
        print("Usage: python producer.py <prefix>")
        sys.exit(1)
    prefix = sys.argv[1]
    producer.run(prefix, on_interest)