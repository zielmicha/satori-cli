#!/usr/bin/env python2.7
# coding=utf-8

from setuptools import setup, find_packages
setup(
    name = "satori-cli",
    version = "0.1",
    packages = find_packages(),
    scripts = ['satori.py'],

    install_requires = ['requests', 'pyquery', 'lxml'],

    # metadata for upload to PyPI
    author = "Michał Zielińsi",
    author_email = "michal@zielinscy.org.pl",
    description = "Command line interface for Satori (satori.tcs.uj.edu.pl) ",
    license = "GPLv3",
    keywords = "hello world example examples",
    url = "https://github.com/zielmicha/satori-cli",   # project home page, if any
)
