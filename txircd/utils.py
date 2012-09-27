# -*- coding: utf-8 -*-
from collections import MutableMapping
from twisted.internet import reactor
import re, datetime

VALID_USERNAME = re.compile(r"[a-zA-Z\[\]\\`_^{}\|][a-zA-Z0-9-\[\]\\`_^{}\|]{3,31}$") # 4-32 char nicks

def irc_lower(str):
    return str.lower().replace('[','{').replace(']','}').replace('/','|').replace('~','^')

def now():
    return datetime.datetime.utcnow().replace(microsecond=0)

UNIX_EPOCH = datetime.datetime(1970, 1, 1, 0, 0)
def epoch(utc_datetime):
  delta = utc_datetime - UNIX_EPOCH
  return int(delta.total_seconds())
  
class CaseInsensitiveDictionary(MutableMapping):
    def __init__(self):
        self._data = {}

    def __repr__(self):
        return repr(self._data)

    def __delitem__(self, key):
        try:
            del self._data[irc_lower(key)]
        except KeyError:
            raise KeyError(key)

    def __getitem__(self, key):
        try:
            return self._data[irc_lower(key)]
        except KeyError:
            raise KeyError(key)

    def __iter__(self):
        return iter(self._data)

    def __len__(self):
        return len(self._data)

    def __setitem__(self, key, value):
        self._data[irc_lower(key)] = value


class DefaultCaseInsensitiveDictionary(CaseInsensitiveDictionary):
    def __init__(self, default_factory):
        self._default_factory = default_factory
        super(DefaultCaseInsensitiveDictionary, self).__init__()

    def __contains__(self, key):
        try:
            super(DefaultCaseInsensitiveDictionary, self).__getitem__(key)
        except KeyError:
            return False
        return True

    def __getitem__(self, key):
        try:
            return super(DefaultCaseInsensitiveDictionary, self).__getitem__(key)
        except KeyError:
            value = self[key] = self._default_factory(key)
            return value
