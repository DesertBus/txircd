from twisted.words.protocols import irc
from txircd.modbase import Command
from twisted.internet import reactor

class RestartCommand(Command):
	def onUse(self, user, data):
		def restart():
			os.execl(sys.executable, sys.executable, *sys.argv)
		reactor.addSystemEventTrigger("after", "shutdown", restart)
		reactor.stop()
	
	def processParams(self, user, params):
		if user.registered > 0:
			user.sendMessage(irc.ERR_NOTYETREGISTERED, "RESTART", ":You have not registered")
			return {}
		if "o" not in user.mode:
			user.sendMessage(irc.ERR_NOPRIVILEGES, ":Permission denied - You do not have the correct operator privileges")
			return {}
		return {
			"user": user
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn(self):
		return {
			"commands": {
				"RESTART": RestartCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["RESTART"]