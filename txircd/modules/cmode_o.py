from twisted.words.protocols import irc
from txircd.modbase import Mode

class OpMode(Mode):
	def checkSet(self, user, target, param):
		if param not in self.ircd.users:
			return False
		oppingUser = self.ircd.users[param]
		if target.name not in oppingUser.channels:
			return False
		if "o" in oppingUser.status(target.name):
			return False
		oppingStatus = oppingUser.status(target.name)
		if user.hasAccess(target.name, "o") and (not oppingStatus or (oppingStatus and user.hasAccess(target.name, oppingStatus[0]))):
			return True
		return False
	
	def checkUnset(self, user, target, param):
		if param not in self.ircd.users:
			return False
		deoppingUser = self.ircd.users[param]
		if target.name not in oppingUser.channels:
			return False
		if "o" not in oppingUser.status(target.name):
			return False
		if user.hasAccess(target.name, "o") and user.hasAccess(target.name, deoppingUser.status(target.name)[0]):
			return True
		return False

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"cso": OpMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("cso")