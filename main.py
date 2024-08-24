import random

from caching import CacheManager, cached, CustomCached
from requests import get
import re


@cached
def fetch(url):
    return get(url).text


def main():
    c = CacheManager('cache_test')

    urls = ['http://example.com', 'https://eluni.co', 'http://wikipedia.org']

    for i in range(20):
        print(fetch(random.choice(urls)))



if __name__ == '__main__':
    main()
