# -*- coding: utf-8 -*-
from collections import MutableMapping
from twisted.internet import reactor

def iterate_non_blocking(iterator):
    try:
        iterator.next()
    except StopIteration:
        return
    reactor.callLater(0, iterate_non_blocking, iterator)

def irc_lower(str):
    return str.lower().replace('[','{').replace(']','}').replace('/','|').replace('~','^')

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

    def __getitem__(self, key):
        try:
            return super(DefaultCaseInsensitiveDictionary, self).__getitem__(key)
        except KeyError:
            value = self[key] = self._default_factory(key)
            return value
