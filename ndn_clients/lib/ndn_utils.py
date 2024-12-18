from asyncio import subprocess
import asyncio
from typing import Optional
import urllib.parse
from ndn.encoding import Name, FormalName, MetaInfo, BinaryStr
from ndn.app_support.segment_fetcher import segment_fetcher, NonStrictName
from ndn.app import NDNApp
from ndn.types import InterestNack, InterestTimeout, InterestCanceled, ValidationFailure
from ndn.encoding import Name, Component
from ndn.utils import timestamp

SEGMENT_SIZE = 90

def get_original_name(name: FormalName) -> FormalName:
    original_name = ""
    if Component.get_type(name[-1]) == Component.TYPE_SEGMENT:
        original_name = Name.normalize(name[:-1])
    else:
        original_name = Name.normalize(name)
    return original_name

# ()を使う関係上、nameをデコードし、またメタデータを削除する
# Name.to_str(name)でデコードした場合、/A/%28B%29/t=12411 のようになっているため、/A/(〇〇)/t=12411 のようにデコードする
# /A/(〇〇)/t=12411 のようになる構造上、最後の)以降を削除すれば良い
# /A/data などのデータリクエストの場合は、/t=だけ消して、そのまま返す
def decode_and_remove_metadata(name: FormalName) -> str:
    # 名前をデコード
    decoded_name = Name.to_str(name)
    decoded_name = urllib.parse.unquote(decoded_name)
    
    # 最後の ')' の位置を見つける
    end_index = decoded_name.rfind(')')
    if end_index != -1 and len(decoded_name) > end_index + 1 and decoded_name[end_index + 1] == '/':
        # 最後の　)以降の部分を削除
        decoded_name = decoded_name[:end_index + 1]

    # /t= がある場合があるので削除
    end_index = decoded_name.rfind('/t=')
    if end_index != -1:
        decoded_name = decoded_name[:end_index]

    return decoded_name


# name 構造から、function リクエストかを調べる
# /A/(〇〇) のような構造であれば function リクエストなので、/(が存在すれば関数と判断する
# そうでなければ、data リクエストなので、データを返す
def is_function_request(name: FormalName) -> bool:
    decoded_url = decode_and_remove_metadata(name)
    return "/(" in decoded_url

# function リクエストから、第一階層の引数を抽出する
def extract_first_level_args(name: FormalName) -> list[str]:
    decoded_url = decode_and_remove_metadata(name)
    
    def trim(s: str) -> str:
        return s.strip()

    args = []
    if '(' not in decoded_url:
        args.append(trim(decoded_url))
        return args

    # Correctly extract the function name
    end_of_function_name = decoded_url.find('/(')
    start_of_args = end_of_function_name + 2
    args_str = decoded_url[start_of_args:-1]

    start = 0
    bracket_count = 0
    for i, char in enumerate(args_str):
        if char == '(':
            bracket_count += 1
        elif char == ')':
            bracket_count -= 1
        elif char == ',' and bracket_count == 0:
            args.append(trim(args_str[start:i]))
            start = i + 1

    args.append(trim(args_str[start:]))
    return args


async def segment_fetcher_original(app: NDNApp, name: NonStrictName, first_nonce: Optional[str] = None, timeout=4000, retry_times=3,
                          validator=None, must_be_fresh=True):
    async def retry(first, nonce=None):
        nonlocal name
        trial_times = 0
        while True:
            future = app.express_interest(name, validator=validator, can_be_prefix=first,
                                          must_be_fresh=must_be_fresh, lifetime=timeout, nonce=int(nonce) if nonce else None)
            try:
                return await future
            except InterestTimeout:
                trial_times += 1
                if trial_times >= retry_times:
                    raise

    name = Name.normalize(name)
    # First Interest
    name, meta, content = await retry(True, first_nonce)
    # If it's not segmented
    if Component.get_type(name[-1]) != Component.TYPE_SEGMENT:
        yield content
        return
    # If it's segmented
    if Component.to_number(name[-1]) == 0:
        yield content
        if meta.final_block_id == name[-1]:
            return
        seg_no = 1
    else:
        # If it's not segment 0, starting from 0
        seg_no = 0
    # Following Interests
    while True:
        name[-1] = Component.from_segment(seg_no)
        name, meta, content = await retry(False)
        yield content
        if meta.final_block_id == name[-1]:
            return
        seg_no += 1

# interestを送る
async def get_data(app: NDNApp, name: str, nonce: Optional[str] = None) -> Optional[bytes]:
    result = b''

    try:
        async for seg in segment_fetcher_original(app, name, first_nonce=nonce, timeout=20000):
            data = bytes(seg)
            result += data
    except InterestNack as e:
        print(f'!!!ERROR!!!: Nacked with reason={e.reason}')
    except InterestTimeout:
        print(f'!!!ERROR!!!: Timeout')
    except InterestCanceled:
        print(f'!!!ERROR!!!: Canceled')
    except ValidationFailure:
        print(f'!!!ERROR!!!: Data failed to validate')

    return  result
    
# interestを送る
async def send_interest(app: NDNApp, name: str, nonce: Optional[str] = None) -> Optional[tuple[FormalName, MetaInfo, BinaryStr]]:
    try:
        name = Name.from_str(name)
        if nonce:
            nonce = int(nonce)
        else:
            nonce = None
        data_name, meta_info, content = await app.express_interest(
            name, must_be_fresh=True, can_be_prefix=False, lifetime=10000, nonce=nonce)

        return data_name, meta_info, content
    except InterestNack as e:
        print(f'!!!ERROR!!!: Nacked with reason={e.reason}')
    except InterestTimeout:
        print(f'!!!ERROR!!!: Timeout')
    except InterestCanceled:
        print(f'!!!ERROR!!!: Canceled')
    except ValidationFailure:
        print(f'!!!ERROR!!!: Data failed to validate')

# function リクエストから、自分の関数名を取得する
# /A/(/hoge,/B/func(/hoge)) のような構造であれば、/A が関数名になる
def extract_my_function_name(name: FormalName) -> str:
    decoded_url = decode_and_remove_metadata(name)
    end_of_function_name = decoded_url.find('/(')
    return decoded_url[:end_of_function_name]
