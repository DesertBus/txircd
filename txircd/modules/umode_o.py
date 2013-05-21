from txircd.modbase import Mode

class OperMode(Mode):
	def checkSet(self, target, param):
		return False # Should only be set by the OPER command; hence, reject any normal setting of the mode

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"modes": {
				"uno": OperMode()
			}
		}
	
	def cleanup(self):
		self.ircd.removeMode("uno")