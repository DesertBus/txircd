from txircd.utils import crypt
import sys

if len(sys.argv) < 2:
    print "Usage: python passcrypt.py password"
    sys.exit(0)
print crypt(sys.argv[1])