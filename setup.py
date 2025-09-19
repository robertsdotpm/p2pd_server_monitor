# Python version 3.5 and up.
from setuptools import setup, find_packages
from codecs import open
from os import path
import sys


here = path.abspath(path.dirname(__file__))

# Get the long description from the README file
with open(path.join(here, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()

install_reqs = ["fastapi"]

setup(
    version='1.0.0',
    name='p2pd_server_monitor',
    description='monitor stun and other servers',
    keywords=('wewlad'),
    long_description_content_type="text/markdown",
    long_description=long_description,
    url='http://github.com/robertsdotpm/p2pd-server-monitor',
    author='Matthew Roberts',
    author_email='matthew@roberts.pm',
    license='public domain',
    package_dir={"": "."},
    packages=find_packages(),
    package_data={'p2pd': ['p2pd_server_monitor/monitor.sqlite3']},
    include_package_data=True,
    install_requires=install_reqs,
    classifiers=[
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3'
    ],
)
