from base64 import b64encode, b64decode
from collections import MutableMapping
from Crypto.Hash import MD5, SHA, SHA224, SHA256, SHA384, SHA512
from pbkdf2 import PBKDF2
from struct import pack
from random import randint
import re, datetime, sys

VALID_NICKNAME = re.compile(r"[a-zA-Z\[\]\\`_^{}\|][a-zA-Z0-9-\[\]\\`_^{}\|]{0,31}$") # up to 32 char nicks
DURATION_REGEX = re.compile(r"((?P<years>\d+?)y)?((?P<weeks>\d+?)w)?((?P<days>\d+?)d)?((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?")
IPV4_MAPPED_ADDR = re.compile(r"^::ffff:((\d{1,3}\.){3}\d{1,3})$")

def irc_lower(str):
    return str.lower().replace("[","{").replace("]","}").replace("/","|").replace("~","^")

def now():
    return datetime.datetime.utcnow().replace(microsecond=0)

UNIX_EPOCH = datetime.datetime(1970, 1, 1, 0, 0)
def epoch(utc_datetime):
    delta = utc_datetime - UNIX_EPOCH
    return int(delta.total_seconds())

time_lengths = {
    "years": 31557600, # 365.25 days to avoid leap year nonsense
    "weeks": 604800,
    "days": 86400,
    "hours": 3600,
    "minutes": 60,
    "seconds": 1
}
def parse_duration(duration_string):
    """
    Parses a string duration given in 1y2w3d4h5m6s format
    returning the total number of seconds
    """
    try: # attempt to parse as a number of seconds if we get just a number before we go through the parsing process
        return int(duration_string)
    except ValueError:
        pass
    timeparts = DURATION_REGEX.match(duration_string).groupdict()

    duration = 0
    for unit, amount in timeparts.iteritems():
        if amount is not None:
            try:
                duration += int(amount) * time_lengths[unit]
            except ValueError:
                pass
    return duration

def build_duration(duration_int):
    timeparts = {}
    for name in ["years","weeks","days","hours","minutes","seconds"]:
        timeparts[name] = duration_int / time_lengths[name]
        duration_int -= timeparts[name] * time_lengths[name]
    return "{years}y{weeks}w{days}d{hours}h{minutes}m{seconds}s".format(**timeparts)

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

def escapeEndpoint(desc):
    return desc.replace("\\", "\\\\").replace(":", "\\:").replace("=", "\\=")

def resolveEndpointDescription(desc):
    result = []
    current = []
    depth = 0
    desc = iter(desc)
    for letter in desc:
        if letter == "\\":
            nextchar = desc.next()
            if nextchar in "{}":
                current.append(nextchar)
            else:
                current.extend((letter, nextchar))
        elif letter == "{":
            if depth == 0:
                result.append("".join(current))
                current = []
            else:
                current.append(letter)
            depth += 1
        elif letter == "}":
            depth -= 1
            if depth == 0:
                result.append(escapeEndpoint(resolveEndpointDescription("".join(current))))
                current = []
            else:
                current.append(letter)
        else:
            current.append(letter)
    if depth != 0:
        raise ValueError ("Malformed endpoint description; braces do not match")
    result.append("".join(current))
    return "".join(result)

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

# Duplicate PBKDF2

# Python 2.1 thru 3.2 compatibility
if sys.version_info[0] == 2:
    def isunicode(s):
        return isinstance(s, unicode)
    def isbytes(s):
        return isinstance(s, str)
    def b(s):
        return s
else:
    def isunicode(s):
        return isinstance(s, str)
    def isbytes(s):
        return isinstance(s, bytes)
    def b(s):
        return s.encode("latin-1")

def crypt(word, salt=None, iterations=1000, algorithm="sha256", bytes=24):
    """PBKDF2-based unix crypt(3) replacement.

    The number of iterations specified in the salt overrides the 'iterations'
    parameter.
    """
    
    # Reserve algorithms
    algos = {
        "md5": MD5,
        "sha1": SHA,
        "sha224": SHA224,
        "sha256": SHA256,
        "sha384": SHA384,
        "sha512": SHA512
    }
    
    # Generate a (pseudo-)random salt if the user hasn't provided one.
    if salt is None:
        salt = _makesalt()

    # salt must be a string or the us-ascii subset of unicode
    if isunicode(salt):
        salt = salt.encode('us-ascii').decode('us-ascii')
    elif isbytes(salt):
        salt = salt.decode('us-ascii')
    else:
        raise TypeError("salt must be a string")

    # word must be a string or unicode (in the latter case, we convert to UTF-8)
    if isunicode(word):
        word = word.encode("UTF-8")
    elif not isbytes(word):
        raise TypeError("word must be a string or unicode")

    # Try to extract the real salt and iteration count from the salt
    if ":" in salt:
        (algorithm, iterations, salt, oldhash) = salt.split(":")
        if iterations != "":
            iterations = int(iterations)
            if iterations < 1:
                raise ValueError("Invalid salt")
        bytes = len(b64decode(oldhash))

    # Make sure the salt matches the allowed character set
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789+/="
    for ch in salt:
        if ch not in allowed:
            raise ValueError("Illegal character {!r} in salt".format(ch))
    
    if algorithm not in algos:
        raise ValueError("Invalid algorithm: {}".format(algorithm))

    hash = b64encode(PBKDF2(word, salt, iterations, algos[algorithm]).read(bytes))
    return "{}:{!s}:{}:{}".format(algorithm, iterations, salt, hash)

def _makesalt():
    """Return a 48-bit pseudorandom salt for crypt().

    This function is not suitable for generating cryptographic secrets.
    """
    return b64encode(b("").join([pack("@H", randint(0, 0xffff)) for i in range(3)]))