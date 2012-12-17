from twisted.words.protocols import irc
from txircd.modbase import Command

class QuitCommand(Command):
	def onUse(self, user, data):
		quit_to = set()
		for chan in user.channels.iterkeys():
			cdata = self.ircd.channels[chan]
			self.leave(chan)
			for u in cdata.users:
				quit_to.add(u)
		for u in quit_to:
			u.sendMessage("QUIT", ":{}".format(reason), to=None, prefix=user.prefix())
		user.sendMessage("ERROR", ":Closing Link {} [{}]".format(user.prefix(), reason), to=None, prefix=None)
		del self.ircd.users[user.nickname]
		user.socket.transport.loseConnection()
	
	def processParams(self, user, params):
		reason = params[0] if params and params[0] else "Client exited"
		return {
			"user": user,
			"reason": reason
		}

class Spawner(object):
	def __init__(self, ircd):
		self.ircd = ircd
	
	def spawn():
		return {
			"commands": {
				"QUIT": QuitCommand()
			}
		}
	
	def cleanup():
		del self.ircd.commands["QUIT"]