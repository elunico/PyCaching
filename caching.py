import functools
import os
import os.path
import re
import sys
import time
import typing
from threading import RLock
from typing import Dict

import msgpack

# TODO: implement a @caching decorator that automatically caches function calls to the file system
# TODO: add a class method to CacheManager that escapes text to be safely used in the filesystem paths
# TODO: make the commit() method harder to forget

magenta = '\033[95m'
blue = '\033[94m'
green = '\033[92m'
yellow = '\033[93m'
red = '\033[91m'
black = '\033[0m'
bold = '\033[1m'
uline = '\033[4m'

if os.environ.get('DEBUG', False):

    import inspect
    import os.path

    def line():
        return "{}:{}:{}".format(os.path.split(inspect.stack()[2][1])[-1], inspect.stack()[2][2], inspect.stack()[2][3])

    def debug(msg, color=yellow):
        print("{2}DEBUG: {0} {1}{3}".format(line(), msg, color, black))
else:
    def line():
        return ''

    def debug(*args, **kwargs):
        pass


def perror(message):
    print(message, file=sys.stderr)


TimeStamp = float
FileName = str


class CacheManager:
    # TODO: raise more/better exceptions instead of catching and returning random numbers
    # TODO: write documentation
    # TODO: add types
    # TODO: make note that (un)serialization can be customized by overwriting the _serialize and _unserialize methods
    # maybe this should use injection or composition instead?
    def __init__(self, package_name, working_directory='.', perror=perror, automatic=True,
                 atexit=True):
        self._cache_seconds = 60 * 60 * 24
        self._max_cache_size = 1024 * 1024
        self._caching_active = True

        self._working_directory = working_directory
        self._package_name = package_name
        self._cache_path = os.path.join(
            self._working_directory, self._package_name, 'caches')
        self._state_path = os.path.join(
            self._working_directory, self._package_name, 'state')
        self._size_path = os.path.join(
            self._working_directory, self._package_name, 'size')
        self._index_path = os.path.join(
            self._working_directory, self._package_name, 'cache_index')
        self._time_path = os.path.join(
            self._working_directory, self._package_name, 'max_seconds')
        self._last_cache_size = None
        self._perror = perror

        self._cache_lock = RLock()

        self._index = {}

        if automatic:
            self.startup()

        if atexit:
            import atexit as ae
            ae.register(self.commit)

    def _write_setting(self, filename, value):
        with self._cache_lock:
            with open(filename, 'w') as f:
                f.write(str(value))

    @property
    def caching_active(self):
        return self._caching_active

    @caching_active.setter
    def caching_active(self, value: bool):
        self._caching_active = value
        self._write_setting(self._state_path, 'start' if value else 'stop')

    @property
    def max_cache_size(self):
        return self._max_cache_size

    @max_cache_size.setter
    def max_cache_size(self, value: int):
        self._max_cache_size = value
        self._write_setting(self._size_path, value)
        self.prune_max_size()

    @property
    def cache_seconds(self):
        return self._cache_seconds

    @cache_seconds.setter
    def cache_seconds(self, value: int):
        self._cache_seconds = value
        self._write_setting(self._time_path, value)
        self.prune_expired_caches()

    def startup(self):
        with self._cache_lock:

            # create dirs for cache storage
            if not os.path.isdir(self._cache_path):
                os.makedirs(self._cache_path)

            # read in the index or create a blank one if none exists
            if not os.path.exists(self._index_path):
                self._index: Dict[FileName, TimeStamp] = {}
            else:
                with open(self._index_path, 'rb') as f:
                    self._index = self._unserialize(f.read())

            self._read_settings()

    def _read_settings(self):
        # later we will read in the settings from these files
        # if the files are not present we first write defaults
        # this allows defaults to be present and prevents errors on first read
        with self._cache_lock:
            if not os.path.exists(self._state_path):
                with open(self._state_path, 'w') as f:
                    f.write('start')
            if not os.path.exists(self._size_path):
                with open(self._size_path, 'w') as f:
                    f.write('100000000')
            if not os.path.exists(self._time_path):
                with open(self._time_path, 'w') as f:
                    f.write('86400')
            # read in settings
            with open(self._state_path) as f:
                self.caching_active = f.read() == 'start'
            with open(self._size_path) as f:
                self.max_cache_size = int(f.read())
            with open(self._time_path) as f:
                self.cache_seconds = int(f.read())

    @property
    def recent_cache_size(self):
        if self._last_cache_size is None:
            self._last_cache_size = self._retrieve_cache_size()
        return self._last_cache_size

    def _retrieve_cache_size(self):
        with self._cache_lock:
            s = 0
            try:
                for f in os.listdir(self._cache_path):
                    path = os.path.join(self._cache_path, f)
                    if os.path.isfile(path):
                        s += os.path.getsize(path)
            except (IOError, OSError) as e:
                self._perror(
                    "An error occurred while getting cache size: {}".format(e))
                raise  # return -22
            self._last_cache_size = s
            return s

    def _serialize(self, data):
        # use_bin_type tells msgpack to distinguish str and bytes
        with self._cache_lock:
            return msgpack.packb(data, use_bin_type=True)

    def _unserialize(self, data):
        # raw=False tells msgpack to convert str back into str not keep as bytes
        with self._cache_lock:
            return msgpack.unpackb(data, raw=False)

    def _join_cache_path(self, *args):
        """returns the args path joined to cache_path. Used get the path to a cache file
        given the filename only"""
        return os.path.join(self._cache_path, *args)

    # this function removes records that are too old (expired)
    def prune_expired_caches(self):
        with self._cache_lock:
            entries = sorted(list(self._index.items()), key=lambda x: x[1])
            now = time.time()
            # index is sorted by time, oldest times towards 0
            # while the oldest items are older than the MAX
            # remove those items
            if len(entries) > 0 and now - entries[0][1] > self.cache_seconds:
                # only print message if there's items to remove
                debug('Pruning expired cache data. Please wait...', black)
            count = 0
            while len(entries) > 0 and now - entries[0][1] > self.cache_seconds:
                path = self._join_cache_path(entries.pop(0)[0])
                assert '.guppy' in path
                try:
                    os.remove(path)
                    count += 1
                    debug('Removing {} because it is too old'.format(path), magenta)
                except FileNotFoundError:
                    debug('File {} in index but not found on delete. '.format(
                        path), yellow)

            self._index = {k: v for (k, v) in entries}
            if count > 0:
                debug('Removed {} expired cache files'.format(count), green)

    def prune_max_size(self):
        with self._cache_lock:
            # sort by time from lowest (oldest) to highest (newest)
            entries = sorted(list(self._index.items()), key=lambda x: x[1])
            while self._retrieve_cache_size() > self.max_cache_size and len(entries) > 0:
                path = self._join_cache_path(entries.pop(0)[0])
                assert self._package_name in path
                try:
                    os.remove(path)
                except FileNotFoundError:
                    debug('File {} in index but not found on delete. '.format(
                        path), yellow)
                    raise

            self._index = {k: v for (k, v) in entries}

    def cache_item(self, path, data):
        if not self.caching_active:
            perror("Attempt to cache item when caching inactive")
            return None
        with self._cache_lock:
            self._index[path] = time.time()
            with open(self._join_cache_path(path), 'wb') as f:
                num = f.write(self._serialize(data))
            self.prune_max_size()
            return num

    # this function, given the filename of a cache file,
    # returns the data in that file if it exists or None if it does not

    def retrieve_cached_item(self, path):
        if not self.caching_active:
            perror("Attempt to retrieve cached item when caching inactive")
            return None
        with self._cache_lock:
            if os.path.exists(self._join_cache_path(path)):
                with open(self._join_cache_path(path), 'rb') as f:
                    return self._unserialize(f.read())
            return None

    def commit(self):
        """
        THIS FUNCTION MUST BE CALLED BEFORE THE PROGRAM QUITS
        BUT NOT BEFORE ANY FURTHER ACTION IS TAKEN ON THE CACHE
        IT IS CALLED, CURRENTLY RIGHT BEFORE THE PROGRAM EXISTS
        AFTER dispatch() IN guppy.py
        IT WRITES THE INDEX OF THE CACHE OUT AND WITHOUT THE
        CACHE CANNOT PRUNE ITSELF
        """
        with self._cache_lock:
            try:
                with open(self._index_path, 'wb') as f:
                    f.write(self._serialize(self._index))
                return 0
            except (IOError, OSError) as e:
                perror("Error saving cache: {}".format(e))
                return 9

    def clear(self):
        c = 0
        try:
            for file in os.listdir(self._cache_path):
                os.remove(self._join_cache_path(file))
                c += 1
            self._index = {}
        except (OSError, IOError) as e:
            perror('An error occurred while clearing the cache: {}'.format(e))
            return -21
        return c


class CustomCached:
    def __init__(self, file_namer: typing.Callable[[typing.Any], str], cache: CacheManager = None):
        self.file_namer = file_namer
        self.cache = cache

    def __call__(self, fn):
        self.cache = CacheManager(
            fn.__name__) if self.cache is None else self.cache

        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if (cached_value := self.cache.retrieve_cached_item(self.file_namer(*args, **kwargs))) is not None:
                print(cached_value)
                return cached_value
            value = fn(*args, **kwargs)
            path = self.file_namer(*args, **kwargs)
            self.cache.cache_item(path, value)
            return value

        return wrapper


f = re.compile(r'[/\\%?$#@!~`={\]\[{|"\':;<>]')


def cached(fn):
    cache = CacheManager(fn.__name__)

    def file_namer(*args):
        return f.sub('-', '_'.join(args))

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if (cached_value := cache.retrieve_cached_item(file_namer(*args, **kwargs))) is not None:
            print(cached_value)
            return cached_value
        value = fn(*args, **kwargs)
        path = file_namer(*args, **kwargs)
        cache.cache_item(path, value)
        return value

    return wrapper
