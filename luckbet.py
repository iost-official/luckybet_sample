import sys
import subprocess
import os
import collections
import time
import re
import json

assert sys.version_info.major == 3
assert sys.version_info.minor >= 6

DEFAULT_EXPIRATION = 5
DEFAULT_GASLIMIT = 100000  # (0.001 iost)
DEFAULT_NODEIP = '127.0.0.1'

Account = collections.namedtuple('Account', ['nickname', 'account_name'])


def log(s):
    print(s)


def check_float_equal(a, b):
    assert abs(a - b) < 1e-8


def call(cmd):
    log('exec ' + cmd)
    if sys.platform == 'darwin':
        # It is a workaround for a bug(feature?) of macOS.
        IOST_REPO_PATH = '/Users/zhangzhuo/go-workspace/src/github.com/iost-official/go-iost'
        DYLD_LIBRARY_PATH = os.environ.get(
            'DYLD_LIBRARY_PATH') + f':{IOST_REPO_PATH}/vm/v8vm/v8/libv8/_darwin_amd64/'
        cmd = 'DYLD_LIBRARY_PATH=' + DYLD_LIBRARY_PATH + ' ' + cmd
    ret = subprocess.run(['bash', '-c', cmd], encoding='utf8',
                         stdout=subprocess.PIPE, check=True)
    assert not ret.stdout is None
    return ret.stdout


def create_account(nickname):
    stdout = call('iwallet account -n ' + nickname)
    account_name = re.findall('IOST\S+', stdout)[0]
    return Account(nickname, account_name)


def get_balance(account_name):
    cmd = 'iwallet balance ' + account_name
    stdout = call(cmd)
    amount = re.findall('(\S+) iost', stdout)[0]
    return float(stdout.split()[0])


def check_tx(txid):
    log(f'checking transaction {txid}')
    cmd = f'curl -s -X GET http://{DEFAULT_NODEIP}:30001/getTxReceiptByTxHash/{txid}'
    stdout = call(cmd)
    print(f'output {stdout}')
    result = json.loads(stdout)
    assert result['txReceiptRaw']['succActionNum'] == 1
    return result


def fetch_contract_state(cid, key):
    cmd = f'curl -s -X GET http://{DEFAULT_NODEIP}:30001/getState/{cid}-{key}'
    stdout = call(cmd)
    json_result = eval(json.loads(stdout)['value'][1:])
    return json_result


def call_contract(cid, function_name, function_args, key=None):
    cmd = f'iwallet call --expiration {DEFAULT_EXPIRATION}'
    if not key is None:
        cmd += f' -k {key}'
    function_args_str = json.dumps(function_args)
    cmd += f' -l {DEFAULT_GASLIMIT} {cid} {function_name} \'{function_args_str}\''
    stdout = call(cmd)
    txid = re.findall(r'the transaction hash is: (\S+)', stdout)[0]
    log(f'after call_contract, txid is {txid}')
    time.sleep(DEFAULT_EXPIRATION)
    return check_tx(txid)


def transfer_from_initial(account_name, amount):
    INITIAL_ACCOUNT = 'IOSTfQFocqDn7VrKV7vvPqhAQGyeFU9XMYo5SNn5yQbdbzC75wM7C'
    INITIAL_KEY = '1rANSfcRzr4HkhbUFZ7L1Zp69JZZHiDDq5v7dNSbbEqeU4jxy3fszV4HGiaLQEyqVpS1dKT9g7zCVRxBVzuiUzB'
    cid = 'iost.system'
    function_name = 'Transfer'
    function_args = [INITIAL_ACCOUNT, account_name, amount]
    key = f'<(echo {INITIAL_KEY})'
    call_contract(cid, function_name, function_args, key)
    new_balance = get_balance(account_name)
    assert new_balance >= amount
    log(f'{account_name}: {new_balance} (after transfer {amount} iost in)')


def publish_contract(js_file, js_abi_file, nickname):
    cmd = f'iwallet compile -e {DEFAULT_EXPIRATION} -l {DEFAULT_GASLIMIT} -p 1 -k ~/.iwallet/{nickname}_ed25519 {js_file} {js_abi_file}'
    stdout = call(cmd)
    txid = re.findall(r'the transaction hash is: (\S+)', stdout)[0]
    log(f'after publish_contract, txid is {txid}')
    time.sleep(DEFAULT_EXPIRATION)
    check_tx(txid)
    contract_id = 'Contract' + txid
    return contract_id


def main():
    # publish the contract
    contract_uploader = create_account('uploader')
    transfer_from_initial(contract_uploader.account_name, 100)
    cid = publish_contract('contract/lucky_bet.js',
                           'contract/lucky_bet.js.abi', 'uploader')

    bet_users = []
    # create ten fake users
    for i in range(1, 11):
        nickname = f'user_{i}'
        bet_users.append(create_account(nickname))
    # give coins for the bet game to each user
    initial_coins = 100
    for account in bet_users:
        transfer_from_initial(account.account_name, initial_coins)
    # bet
    gas_used = []
    bet_coins = []
    for idx, account in enumerate(bet_users):
        lucky_number = idx
        bet_coin = idx // 2 + 1
        bet_coins.append(bet_coin)
        nouce = idx + 1
        args = [account.account_name, lucky_number,
                bet_coin * 100000000, nouce]
        result = call_contract(
            cid, 'bet', args, key=f'~/.iwallet/{account.nickname}_ed25519')
        gas_used.append(float(result['txReceiptRaw']['gasUsage']) / 1e8)
    # get bet results
    print('Balance after the bet')
    final_balances = []
    for account in bet_users:
        balance = get_balance(account.account_name)
        final_balances.append(balance)
        print(f'{account.nickname}: {balance}')
    # check result
    contract_state = fetch_contract_state(cid, 'result1')
    rewards = []
    win_user_num = 0
    for record in contract_state['records']:
        if 'reward' in record:
            win_user_num += 1
            rewards.append(float(record['reward']) / 1e8)
        else:
            rewards.append(0)
    log(f'rewards: {rewards}')
    assert win_user_num == 1
    total_coins_bet = sum(bet_coins)
    check_float_equal(total_coins_bet * 0.95, sum(rewards))
    # check balance of each user
    for i in range(10):
        calculated_balance = initial_coins - \
            bet_coins[i] - gas_used[i] + rewards[i]
        log(
            f'calculated_balance {calculated_balance} actual_balance {final_balances[i]}')
        check_float_equal(calculated_balance, final_balances[i])
    log('Congratulations! You have just run a smart contract on IOST!')


main()
