import getpass
import logging
import os
import re
from http.cookiejar import LWPCookieJar
from typing import List, Optional

import requests
from bs4 import BeautifulSoup

from atcodertools.models.contest import Contest
from atcodertools.models.problem import Problem
from atcodertools.models.problem_content import ProblemContent, InputFormatDetectionError, SampleDetectionError


class LoginError(Exception):
    pass


default_cookie_path = os.path.join(
    os.path.expanduser('~/.local/share'), 'atcoder-tools', 'cookie.txt')


def save_cookie(session: requests.Session, cookie_path: Optional[str] = None):
    cookie_path = cookie_path or default_cookie_path
    os.makedirs(os.path.dirname(cookie_path), exist_ok=True)
    session.cookies.save()
    os.chmod(cookie_path, 0o600)


def load_cookie_to(session: requests.Session, cookie_path: Optional[str] = None):
    cookie_path = cookie_path or default_cookie_path
    session.cookies = LWPCookieJar(cookie_path)
    if os.path.exists(cookie_path):
        session.cookies.load()
        return True
    return False


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(
                Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class AtCoderClient(metaclass=Singleton):

    def __init__(self):
        self._session = requests.Session()

    def check_logging_in(self):
        private_url = "https://arc001.contest.atcoder.jp/settings"
        resp = self._request(private_url)
        return resp.url == private_url

    def login(self, username=None, password=None, use_local_session_cache=True):
        if use_local_session_cache:
            load_cookie_to(self._session)
            if self.check_logging_in():
                logging.info(
                    "Successfully Logged in using the previous session cache.")
                logging.info(
                    "If you'd like to invalidate the cache, delete {}.".format(default_cookie_path))

                return

        if username is None:
            username = input('AtCoder username: ')

        if password is None:
            password = getpass.getpass('AtCoder password: ')

        resp = self._request("https://arc001.contest.atcoder.jp/login", data={
            'name': username,
            "password": password
        }, method='POST')

        if resp.text.find("パスワードを忘れた方はこちら") != -1:
            raise LoginError

        if use_local_session_cache:
            save_cookie(self._session)

    def download_problem_list(self, contest: Contest) -> List[Problem]:
        resp = self._request(contest.get_problem_list_url())
        soup = BeautifulSoup(resp.text, "html.parser")
        res = []
        for tag in soup.select('.linkwrapper')[0::2]:
            alphabet = tag.text
            problem_id = tag.get("href").split("/")[-1]
            res.append(Problem(contest, alphabet, problem_id))
        return res

    def download_problem_content(self, problem: Problem) -> ProblemContent:
        resp = self._request(problem.get_url())

        try:
            return ProblemContent.from_html(resp.text)
        except (InputFormatDetectionError, SampleDetectionError) as e:
            raise e

    def download_all_contests(self) -> List[Contest]:
        contest_ids = []
        previous_list = []
        page_num = 1
        while True:
            resp = self._request(
                "https://atcoder.jp/contests/archive?page={}&lang=ja".format(page_num))
            soup = BeautifulSoup(resp.text, "html.parser")
            text = str(soup)
            url_re = re.compile(
                r'"/contests/([A-Za-z0-9\'~+\-_]+)"')
            contest_list = url_re.findall(text)
            contest_list = set(contest_list)
            contest_list.remove("archive")
            contest_list = sorted(list(contest_list))

            if previous_list == contest_list:
                break

            previous_list = contest_list
            contest_ids += contest_list
            page_num += 1
        contest_ids = sorted(contest_ids)
        return [Contest(contest_id) for contest_id in contest_ids]

    def submit_source_code(self, contest: Contest, problem: Problem, lang, source):
        resp = self._request(contest.submission_url())
        soup = BeautifulSoup(resp.text, "html.parser")
        session_id = soup.find("input", attrs={"type": "hidden"}).get("value")
        task_select_area = soup.find(
            'select', attrs={"id": "submit-task-selector"})
        task_field_name = task_select_area.get("name")
        task_number = task_select_area.find(
            "option", text=re.compile('{} -'.format(problem.get_alphabet()))).get("value")

        language_select_area = soup.find(
            'select', attrs={"id": "submit-language-selector-{}".format(task_number)})
        language_field_name = language_select_area.get("name")
        language_number = language_select_area.find(
            "option", text=re.compile(lang)).get("value")
        postdata = {
            "__session": session_id,
            task_field_name: task_number,
            language_field_name: language_number,
            "source_code": source
        }
        self._request(
            contest.get_url(),
            data=postdata,
            method='POST')

    def _request(self, url: str, method='GET', **kwargs):
        if method == 'GET':
            response = self._session.get(url, **kwargs)
        elif method == 'POST':
            response = self._session.post(url, **kwargs)
        else:
            raise NotImplementedError
        response.encoding = response.apparent_encoding
        return response