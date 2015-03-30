#!/usr/bin/env python2.7
# -*- mode: python -*-
import argparse
import getpass
import json
import os
import io
import requests
import tempfile
import webbrowser

from pyquery import PyQuery as pq
from lxml.html import etree

BASE = 'https://satori.tcs.uj.edu.pl'

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

class Session(object):
    def __init__(self, path='~/.config/satori.json',
                 cache_path='~/.cache/satori'):
        self.path = os.path.expanduser(path)
        self.cache_path = os.path.expanduser(cache_path)
        self.settings = {}

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
        r = requests.request(method, BASE + path,
                             headers={'Cookie':
                                      'satori_token='
                                      + self.settings['satori_token']})
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

    def match_submit_problem(self, contest, problem):
        try:
            return int(problem)
        except ValueError:
            pass

        for id, code, desc in self.get_problems(problem):
            if match_code(problem, code):
                return (id, code)
        raise SatoriError('unknown problem %r' % problem)

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
