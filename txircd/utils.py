# -*- coding: utf-8 -*-
from collections import MutableMapping
from twisted.internet import reactor
import re, datetime

VALID_USERNAME = re.compile(r"[a-zA-Z\[\]\\`_^{}\|][a-zA-Z0-9-\[\]\\`_^{}\|]{0,31}$") # up to 32 char nicks
DURATION_REGEX = re.compile(r"((?P<years>\d+?)y)?((P<weeks>\d+?)w)?((?P<days>\d+?)d)?((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?")

def irc_lower(str):
    return str.lower().replace("[","{").replace("]","}").replace("/","|").replace("~","^")

def now():
    return datetime.datetime.utcnow().replace(microsecond=0)

UNIX_EPOCH = datetime.datetime(1970, 1, 1, 0, 0)
def epoch(utc_datetime):
    delta = utc_datetime - UNIX_EPOCH
    return int(delta.total_seconds())

def chunk_message(msg, chunk_size):
    chunks = []
    msg += "\n"
    while msg:
        index = msg.find("\n",0,chunk_size+1)
        if index < 0:
            index = msg.rfind(" ",0,chunk_size+1)
        if index < 0:
            index = chunk_size
        chunks.append(msg[:index])
        msg = msg[index+1:] if msg[index] in " \n" else msg[index:]
    return chunks

def strip_colors(msg):
    while chr(3) in msg:
        color_pos = msg.index(chr(3))
        strip_length = 1
        color_f = 0
        color_b = 0
        comma = False
        for i in range(color_pos + 1, len(msg) if len(msg) < color_pos + 6 else color_pos + 6):
            if msg[i] == ",":
                if comma or color_f == 0:
                    break
                else:
                    comma = True
            elif msg[i].isdigit():
                if color_b == 2 or (not comma and color_f == 2):
                    break
                elif comma:
                    color_b += 1
                else:
                    color_f += 1
            else:
                break
            strip_length += 1
        msg = msg[:color_pos] + msg[color_pos + strip_length:]
    msg = msg.replace(chr(2), "").replace(chr(29), "").replace(chr(31), "").replace(chr(15), "").replace(chr(22), "") # bold, italic, underline, plain, reverse
    return msg

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
