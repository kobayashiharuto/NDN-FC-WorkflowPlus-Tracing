import asyncio
import logging
from ndn.app import NDNApp
from ndn.types import InterestNack, InterestTimeout, InterestCanceled, ValidationFailure
from ndn.encoding import Name, Component, InterestParam

from lib.ndn_utils import get_data


logging.basicConfig(format='[{asctime}]{levelname}:{message}',
                    datefmt='%Y-%m-%d %H:%M:%S',
                    level=logging.INFO,
                    style='{')


app = NDNApp()

async def send_interest_with_sleep(app, name, sleep_time, id):
    await asyncio.sleep(sleep_time)
    print(f'{id}: {sleep_time}秒の待機が終了しました、send_interestを実行します')
    content = await get_data(app, name)
    print(f'{id}: send_interestが完了しました')
    return content

async def main():
    try:
        content = await get_data(app, '/function1/service/(/producer1/data, /producer2/data)')

        print(bytes(content) if content else None)
    except InterestNack as e:
        print(f'Nacked with reason={e.reason}')
    except InterestTimeout:
        print(f'Timeout')
    except InterestCanceled:
        print(f'Canceled')
    except ValidationFailure:
        print(f'Data failed to validate')
    finally:
        app.shutdown()


if __name__ == '__main__':
    app.run_forever(after_start=main())