import sys
import subprocess
import os
import collections
import time
import re
import json
import argparse
import random
from multiprocessing.pool import ThreadPool

parser = argparse.ArgumentParser(description='')
parser.add_argument('--setup', dest='setup', action='store_true')
parser.add_argument('--no-setup', dest='setup', action='store_false')
parser.add_argument('--cid', dest='cid', type=str,
                    help='contract id', default='')
parser.set_defaults(setup=True)

assert sys.version_info.major == 3
assert sys.version_info.minor >= 6

DEFAULT_EXPIRATION = 5
DEFAULT_GASLIMIT = 5000000
DEFAULT_GASPRICE = 100
DEFAULT_NODEIP = '127.0.0.1'

initial_coin_of_bet_user = 5

Account = collections.namedtuple('Account', ['account_name'])
command_prefix = f'iwallet --expiration {DEFAULT_EXPIRATION} --gaslimit {DEFAULT_GASLIMIT} --gasprice {DEFAULT_GASPRICE} '


def log(s):
    print(s)


def check_float_equal(a, b):
    assert abs(a - b) < 1e-8


def call(cmd, verbose=False):
    log('exec ' + cmd)
    ret = subprocess.run(cmd, encoding='utf8', shell=True,
                         stdout=subprocess.PIPE)
    assert not ret.stdout is None
    if verbose:
        print(ret.stdout)
    ret.check_returncode()
    return ret.stdout


def create_account(account_name, initial_ram, initial_gas_pledge, initial_balance):
    call(f'{command_prefix} --account admin account --create {account_name} '
         + f'--initial_ram {initial_ram} --initial_gas_pledge {initial_gas_pledge} --initial_balance {initial_balance}')


def get_balance(account_name):
    cmd = 'iwallet balance ' + account_name
    stdout = call(cmd)
    amount = re.findall('"balance": (\S+),', stdout)[0]
    return float(amount)


def fetch_contract_state(cid, key):
    data = {"id": cid, "key": key}
    cmd = f"curl -s -X POST --data '{json.dumps(data)}' http://{DEFAULT_NODEIP}:30001/getContractStorage"
    stdout = call(cmd)
    json_result = eval(json.loads(stdout)['data'])
    return json_result


def call_contract(caller_name, cid, function_name, function_args, verbose=False):
    cmd = f'{command_prefix} --account {caller_name} call '
    function_args_str = json.dumps(function_args)
    cmd += f' {cid} {function_name} \'{function_args_str}\''
    call(cmd, verbose)


def publish_contract(js_file, js_abi_file, account_name):
    cmd = f'{command_prefix} --account {account_name} compile {js_file} {js_abi_file}'
    stdout = call(cmd)
    contract_id = re.findall(r'The contract id is (\S+)$', stdout)[0]
    return contract_id


def init_account():
    private_key = '2yquS3ySrGWPEKywCPzX4RTJugqRh7kJSo5aehsLYPEWkUxBWA39oMrZ7ZxuM4fgyXYs2cPwh5n8aNNpH5x2VyK1'
    cmd = f'iwallet account --import admin {private_key}'
    call(cmd)


def publish():
    # publish the contract
    create_account('uploader', 50000, 10, 0)
    cid = publish_contract('contract/lucky_bet.js',
                           'contract/lucky_bet.js.abi', 'uploader')
    return cid


def get_bet_users():
    bet_user_num = 10
    bet_users = [
        f'user_{random.randint(0, 1000000)}' for idx in range(bet_user_num)]

    def create_bet_user(user):
        create_account(user, 600, 10, initial_coin_of_bet_user)
    pool = ThreadPool(bet_user_num)
    pool.map(create_bet_user, bet_users)
    return bet_users


def main():
    args = parser.parse_args()
    if args.setup:
        init_account()
        cid = publish()
    elif args.cid == '':
        print("You must provide contract id if no setup is performed")
        return
    else:
        cid = args.cid

    # create ten fake users with IOSTs
    bet_users = get_bet_users()
    bet_user_num = len(bet_users)
    pool = ThreadPool(bet_user_num)

    # bet
    bet_coins = [idx // 2 + 1 for idx in range(bet_user_num)]

    def bet(idx):
        lucky_number = idx
        bet_coin = bet_coins[idx]
        nouce = ''
        args = [bet_users[idx], lucky_number, bet_coin, nouce]
        call_contract(bet_users[idx], cid, 'bet', args, True)
    pool.map(bet, range(bet_user_num))

    # get bet results
    final_balances = pool.map(get_balance, bet_users)
    print('Balance after the bet', final_balances)

    # check result
    round_num = fetch_contract_state(cid, 'round')
    contract_state = fetch_contract_state(cid, f'result{round_num-1}')
    rewards = []
    win_user_num = 0
    for record in contract_state['records']:
        if 'reward' in record:
            win_user_num += 1
            rewards.append(float(record['reward']))
        else:
            rewards.append(0)
    log(f'rewards: {rewards}')
    assert win_user_num == 1
    total_coins_bet = sum(bet_coins)
    check_float_equal(total_coins_bet * 95 // 100, sum(rewards))
    # check balance of each user
    for i in range(10):
        calculated_balance = initial_coin_of_bet_user - \
            bet_coins[i] + rewards[i]
        log(
            f'calculated_balance {calculated_balance} actual_balance {final_balances[i]}')
        check_float_equal(calculated_balance, final_balances[i])
    log('Congratulations! You have just run a smart contract on IOST!')


if __name__ == '__main__':
    main()
