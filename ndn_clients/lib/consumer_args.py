from ndn.app import NDNApp
from ndn.types import InterestNack, InterestTimeout, InterestCanceled, ValidationFailure
import argparse

from ndn_utils import get_data

app = NDNApp()


async def main(name, nonce):
    try:
        content = await get_data(app, name, nonce)
        print(content.decode('utf-8') if content else None)
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
    parser = argparse.ArgumentParser()
    parser.add_argument("name", help="Name of the interest")
    parser.add_argument("nonce", help="Nonce of the interest")
    print(parser.parse_args())
    args = parser.parse_args()
    app.run_forever(after_start=main(args.name, args.nonce))