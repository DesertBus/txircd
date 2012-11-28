from txircd.modbase import Mode

class OperMode(Mode):
	def checkSet(self, target, param):
		return False

def Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		return {
			"modes": {
				"uno": OperMode()
			}
		}
	
	def cleanup():
		del self.ircd.user_modes[3]["o"]