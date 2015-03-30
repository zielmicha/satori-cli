#!/usr/bin/env python2.7
# -*- mode: python -*-
import argparse
import getpass
import json
import os
import io
import requests
import webbrowser
import random
import sys
import time
import subprocess

from pyquery import PyQuery as pq
from lxml.html import etree

BASE = 'https://satori.tcs.uj.edu.pl'
LOG_REQUESTS = True

def parse_html(html):
    parser = etree.HTMLParser()
    tree = etree.parse(io.BytesIO(html), parser)
    return tree

class SatoriError(Exception):
    pass

def match_code(query, code):
    query = query.lower()
    code = code.lower()
    return query == code or query + '*' == code

class Cache(object):
    def __init__(self, path):
        self.path = path
        self.data = None

    def load(self):
        if self.data is not None:
            return
        try:
            with open(self.path) as f:
                self.data = json.load(f)
        except IOError:
            self.data = {}

    def save(self):
        suf = '.tmp%d' % random.randrange(10000)
        with open(self.path + suf, 'w') as f:
            json.dump(self.data, f)
        os.rename(self.path + suf, self.path)

    def __setitem__(self, key, value):
        self.load()
        self.data[key] = value
        self.save()

    def __getitem__(self, key):
        self.load()
        return self.data[key]

    def __contains__(self, key):
        self.load()
        return key in self.data

    def get(self, key, default=None):
        self.load()
        return self.data.get(key, default)

def cached(cache_name):
    def wrapper1(func):
        def wrapper(self, *args):
            key = repr(args)
            cache = getattr(self, cache_name)
            if key not in cache:
                cache[key] = func(self, *args)
            return cache[key]

        return wrapper

    return wrapper1

class Session(object):
    def __init__(self, path='~/.config/satori.json',
                 cache_path='~/.cache/satori'):
        self.path = os.path.expanduser(path)
        self.cache_path = os.path.expanduser(cache_path)
        self.settings = {}
        self.match_contest_cache = Cache(self.cache_path + '/match_contest.json')
        self.match_submit_problem_cache = Cache(self.cache_path + '/match_submit_problem.json')
        self.match_problem_cache = Cache(self.cache_path + '/match_problem.json')

    def load(self):
        try:
            with open(self.path, 'r') as f:
                self.settings = json.load(f)
        except IOError:
            pass

    def save(self):
        with open(self.path + '.tmp', 'w') as f:
            json.dump(self.settings, f)
        os.rename(self.path + '.tmp', self.path)

    def login(self, username, password):
        self.settings['username'] = username
        self.settings['password'] = password.encode('hex')

    # HTTP

    def request(self, method, path, parse=True):
        if not 'satori_token' in self.settings:
            self._login()
        if LOG_REQUESTS:
            sys.stderr.write('{} {}...'.format(method, path))
            sys.stderr.flush()
        r = requests.request(method, BASE + path,
                             headers={'Cookie':
                                      'satori_token='
                                      + self.settings['satori_token']})
        if LOG_REQUESTS:
            sys.stderr.write('\b\b\b -> {}\n'.format(r.status_code))
        if parse:
            return pq(r.content)
        else:
            return r.content

    def _login(self):
        resp = requests.post(BASE + '/login',
                             allow_redirects=False,
                             data={
                                 'login': self.settings['username'],
                                 'password': self.settings['password'].decode('hex')})
        if resp.status_code == 302:
            cookie = resp.headers['set-cookie']
            token = cookie.split('=')[1].split(';')[0]
            self.settings['satori_token'] = token
        else:
            raise SatoriError('invalid login')

    # API

    def get_contests(self, other=False):
        resp = self.request('GET', '/contest/select')
        tables = resp.find('.results')
        if not other:
            tables = pq(tables[0])
        for row in tables.find('tr'):
            row = pq(row)
            name = row.find('a.stdlink').text()
            link = row.find('a.stdlink').attr('href')
            if link.startswith('/contest/'):
                id = link.split('/')[2]
                yield name, int(id)

    @cached('match_contest_cache')
    def match_contest(self, query):
        try:
            return int(query)
        except ValueError:
            for name, id in self.get_contests(query):
                if query.lower() in name.lower():
                    return id
            raise SatoriError('no contest %r found' % query)

    def print_contests(self, **kwargs):
        for name, id in self.get_contests(**kwargs):
            print u'{}\t{}'.format(id, name)

    def get_problems(self, contest):
        url = '/contest/%d/problems' % self.match_contest(contest)

        for row in self.request('GET', url).find('.results').find('tr'):
            row = pq(row)
            cols = [ pq(c) for c in row.find('td') ]
            if not cols: continue
            code = cols[0].text().strip()
            name = cols[1].text()
            desc = cols[3].text()
            pdf = cols[2].find('a').attr('href')
            if pdf:
                id = int(pdf.split('/')[3])
            else:
                id = None
            url = cols[1].find('.stdlink')
            if url: url = url.attr('href')
            yield id, pdf, url, code, name, desc

    def print_problems(self, contest):
        for id, pdf, url, code, title, desc in self.get_problems(contest):
            print u'{:<9} {: <5} {: <30} {}' \
                .format(id or '', code, title, desc)


    def get_submit_problems(self, contest):
        url = '/contest/%d/submit' % self.match_contest(contest)
        body = self.request('GET', url)
        opts = body.find('[name=problem]').find('option')
        for opt in opts:
            opt = pq(opt)
            if opt.attr('value'):
                code, name = opt.text().split(':', 1)
                yield int(opt.attr('value')), code, name

    def print_submit_problems(self, contest):
        for id, code, desc in self.get_submit_problems(contest):
            print u'{:<9} {: <5} {}' \
                .format(id or '', code, desc)

    @cached('match_submit_problem_cache')
    def match_submit_problem(self, contest, problem):
        try:
            return int(problem)
        except ValueError:
            pass

        for id, code, desc in self.get_problems(problem):
            if match_code(problem, code):
                return (id, code)
        raise SatoriError('unknown problem %r' % problem)

    @cached('match_problem_cache')
    def match_problem(self, contest, problem):
        try:
            return int(problem)
        except ValueError:
            pass

        for id, pdf, url, code, title, desc in self.get_problems(contest):
            if match_code(problem, code):
                return (id, pdf, url)
        raise SatoriError('unknown problem %r' % problem)

    def cache_write(self, name, data):
        if not os.path.exists(self.cache_path):
            os.mkdir(self.cache_path)

        path = self.cache_path + '/' + name
        with open(path, 'w') as f:
            f.write(data)

        return path

    def get_pdf(self, contest, problem):
        id, pdf, url = self.match_problem(contest, problem)
        data = self.request('GET', pdf, parse=False)
        return self.cache_write('%d.pdf' % id, data)

    def get_status(self, contest, id):
        url = '/contest/%d/results/%d' % (self.match_contest(contest), id)
        body = self.request('GET', url)
        header = body.find('table.results').find('tr')[1]
        header = pq(header).find('td')

        problem = pq(header[2]).text()
        status = pq(header[-1]).text()

        tests = []
        for row in body.find('.mainsphinx table.docutils tr')[1:]:
            row = pq(row)
            cols = map(pq, row.find('td'))
            tests.append((cols[0].text(), cols[1].text()))

        return problem, status, tests

    def print_status(self, contest, id):
        problem, status, tests = self.get_status(contest, id)
        print 'Test report for %s' % problem
        print 'Status:', status
        for name, status in tests:
            print ' - {: <10} {}'.format(name, status)

def notify_status(problem, status):
    subprocess.check_call(['notify-send', 'New status for {}: {}'.format(problem, status)])

def wait(sess, contest, id):
    contest = sess.match_contest(contest)
    last_status = ''
    while True:
        problem, status, tests = sess.get_status(contest, id)
        if status != last_status:
            notify_status(problem, status)
            last_status = status
        if status and status != 'QUE':
            break
        time.sleep(10)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')
    subparsers.add_parser(
        'login',
        help='Set Satori credentials.')

    contests_parser = subparsers.add_parser(
        'contests',
        help='List contests')
    contests_parser.add_argument('--show-other', action='store_true')

    problems_parser = subparsers.add_parser(
        'problems',
        help='List problems.')
    problems_parser.add_argument('--submit',
                                 action='store_true',
                                 help='show submittable problems.')
    problems_parser.add_argument('contest')

    problem_parser = subparsers.add_parser(
        'problem',
        help='Open problem statement.')
    problem_parser.add_argument('contest')
    problem_parser.add_argument('problem')
    problem_parser.add_argument('--pdf', action='store_true',
                                help='Open PDF instead of problem page.')

    status_parser = subparsers.add_parser(
        'status',
        help='Show submit status.')
    status_parser.add_argument('contest')
    status_parser.add_argument('id', type=int)

    wait_parser = subparsers.add_parser(
        'wait',
        help='Wait for submit status change and show notification.')
    wait_parser.add_argument('contest')
    wait_parser.add_argument('id', type=int)

    subparsers.add_parser(
        'clear-cache',
        help='Clear cache.')

    ns = parser.parse_args()
    sess = Session()
    sess.load()

    if ns.command == 'login':
        sess.login(raw_input('Username: '),
                   getpass.getpass('Password: '))
        sess.print_contests()
        sess.save()

    elif ns.command == 'contests':
        sess.print_contests(other=ns.show_other)

    elif ns.command == 'problems':
        if ns.submit:
            sess.print_submit_problems(ns.contest)
        else:
            sess.print_problems(ns.contest)

    elif ns.command == 'problem':
        def open_pdf():
            path = sess.get_pdf(ns.contest, ns.problem)
            webbrowser.open('file://' + path)

        if ns.pdf:
            open_pdf()
        else:
            id, pdf, url = sess.match_problem(ns.contest, ns.problem)
            if not url:
                print 'No HTML for this problem'
                open_pdf()
            else:
                webbrowser.open(BASE + url)

    elif ns.command == 'status':
        sess.print_status(ns.contest, ns.id)

    elif ns.command == 'wait':
        wait(sess, ns.contest, ns.id)

    elif ns.command == 'clear-cache':
        path = os.path.expanduser('~/.cache/satori')
        for file in os.listdir(path):
            os.unlink(path + '/' + file)