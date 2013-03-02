from twisted.words.protocols import irc
from txircd.modbase import Command

class QuitCommand(Command):
	def onUse(self, user, data):
		if user.registered == 0:
			quit_to = set()
			for chan in user.channels.iterkeys():
				cdata = self.ircd.channels[chan]
				self.leave(chan)
				for u in cdata.users:
					quit_to.add(u)
			for u in quit_to:
				u.sendMessage("QUIT", ":Quit: {}".format(reason), to=None, prefix=user.prefix())
			user.sendMessage("ERROR", ":Closing Link {} [{}]".format(user.prefix(), data["reason"]), to=None, prefix=None)
			del self.ircd.users[user.nickname]
		else:
			user.sendMessage("ERROR", ":Closing Link {} [{}]".format(user.hostname, data["reason"]), to=None, prefix=None)
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
	
	def spawn(self):
		return {
			"commands": {
				"QUIT": QuitCommand()
			}
		}
	
	def cleanup(self):
		del self.ircd.commands["QUIT"]