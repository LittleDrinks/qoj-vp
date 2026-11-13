"""Check the installed CLI using its own cookie jar and contest binding."""
from contextlib import redirect_stdout
import io
from pathlib import Path
import re
import tempfile

from .domain import ApplicationError
from .account import navigation_account
from .judgers.qoj import load_upstream


def check(qoj_path, session, args, *, bind=False):
    client_module, _, cli = load_upstream(qoj_path)
    problem = str(args.get('problem', 'A')).upper()
    language = args.get('language', 'cpp')
    if not re.fullmatch(r'[A-Z][A-Z0-9]{0,9}', problem) or not isinstance(language, str) or not 1 <= len(language) <= 80:
        raise ApplicationError('VALIDATION_ERROR', '选择题号和提交语言。')
    try:
        root = cli.state_dir()
        config = cli.load_config(root)
        if config['host'] != 'https://qoj.ac':
            raise ApplicationError('SUBMITTER_SITE_MISMATCH', '在终端运行 qoj login --url https://qoj.ac 登录本场比赛的站点。')
        client = cli.make_client(root, config['host'])
        account = navigation_account(client.get('/').text)
        if not account:
            raise ApplicationError('SUBMITTER_LOGIN_REQUIRED', '在终端运行 qoj login 登录提交工具，然后重新检查。')
        if account.casefold() != str(session.get('account') or '').casefold():
            raise ApplicationError('SUBMITTER_ACCOUNT_MISMATCH', '提交工具账号为 ' + account + '；请用 qoj login 登录 ' + str(session.get('account')) + '。')
        cid = str(session['contestId'])
        if bind:
            contest = client.contest(cid)
            config['contests'][config['host']] = contest
            cli.save_config(root, config)
            cli.save_cookies(root, client)
        contest = config['contests'].get(config['host'])
        if not contest or str(contest.get('id')) != cid:
            raise ApplicationError('SUBMITTER_CONTEST_REQUIRED', '点击“绑定本场并检查”，或在终端运行 qoj contest ' + cid + '。')
        with tempfile.TemporaryDirectory(prefix='qoj-vp-dry-run-') as directory:
            source = Path(directory) / (problem + '.cpp')
            source.write_text('int main() { return 0; }\n')
            arguments = cli.parser().parse_args(['submit', str(source), '-p', problem, '-l', language, '--dry-run'])
            output = io.StringIO()
            with redirect_stdout(output):
                cli.run_submit(arguments, root, config)
        return {'ready': True, 'account': account, 'contestId': cid, 'problem': problem,
                'language': language, 'output': output.getvalue().replace(str(source), problem + '.cpp')}
    except client_module.QojError as error:
        raise ApplicationError('SUBMITTER_CHECK_FAILED', str(error)) from error
