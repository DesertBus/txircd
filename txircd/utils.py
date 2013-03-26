# -*- coding: utf-8 -*-
from collections import MutableMapping
from twisted.internet import reactor
from pbkdf2 import PBKDF2
import re, datetime, hashlib, sys
from base64 import b64encode, b64decode

VALID_NICKNAME = re.compile(r"[a-zA-Z\[\]\\`_^{}\|][a-zA-Z0-9-\[\]\\`_^{}\|]{0,31}$") # up to 32 char nicks
DURATION_REGEX = re.compile(r"((?P<years>\d+?)y)?((?P<weeks>\d+?)w)?((?P<days>\d+?)d)?((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?")

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

def has_CTCP(msg):
	if chr(1) not in msg:
		return False
	findpos = msg.find(chr(1))
	in_action = False
	while findpos > -1:
		if in_action or (msg[findpos+1:findpos+7] == "ACTION" and len(msg) > findpos + 7 and msg[findpos+7] == " "):
			in_action = not in_action
			findpos = msg.find(chr(1), findpos + 1)
		else:
			return True
	return False
	
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
		"md5": hashlib.md5,
		"sha1": hashlib.sha1,
		"sha224": hashlib.sha224,
		"sha256": hashlib.sha256,
		"sha384": hashlib.sha384,
		"sha512": hashlib.sha512,
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