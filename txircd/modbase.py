# The purpose of this file is to provide base classes with the needed functions
# already defined; this allows us to guarantee that any exceptions raised
# during function calls are a problem with the module and not just that the
# particular function isn't defined.

class Module(object):
	def hook(self, base):
		self.ircd = base
		return self
	def onJoinCheck(self, channel, user, final):
		return "pass"
	def onJoinComplete(self, channel, user):
		pass
	def onMessage(self, msgType, sender, target, message):
		return ["allow"]
	def onPart(self, channel, user, reason):
		pass
	def onTopicChange(self, channel, user, topic):
		pass
	def onConnect(self, connection):
		pass
	def onRegister(self, user):
		return True
	def onQuit(self, user, reason):
		pass
	def onCommandExtra(self, command, params):
		pass
	def onMetadataUpdate(self, user, key, oldvalue, newvalue):
		pass
	def onRecvData(self, data):
		pass
	def onSendData(self, data):
		pass

class Mode(object):
	def hook(self, base):
		self.ircd = base
		return self
	def prefixSymbol(self):
		return None
	def checkSet(self, channel, param):
		return True
	def checkUnset(self, channel, param):
		return True
	def onJoin(self, channel, user, params):
		return "pass"
	def onMessage(self, sender, target, message):
		return ["pass"]
	def onPart(self, channel, user, reason):
		pass
	def onTopicChange(self, channel, user, topic):
		pass
	def commandData(self, command, *args):
		pass

def Command(object):
	def hook(self, base):
		self.ircd = base
		return self
	def onUse(self, user, params):
		pass