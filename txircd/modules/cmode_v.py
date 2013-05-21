from txircd.modbase import Mode

class VoiceMode(Mode):
	def checkSet(self, user, target, param):
		if param not in self.ircd.users:
			return False
		voicingUser = self.ircd.users[param]
		if target.name not in voicingUser.channels:
			return False
		if "v" in voicingUser.status(target.name):
			return False
		return True
	
	def checkUnset(self, user, target, param):
		if param not in self.ircd.users:
			return False
		devoicingUser = self.ircd.users[param]
		if target.name not in devoicingUser.channels:
			return False
		if "v" not in devoicingUser.status(target.name):
			return False
		return True

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"csv+10": VoiceMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("csv")