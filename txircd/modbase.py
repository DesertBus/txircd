# The purpose of this file is to provide base classes with the needed functions
# already defined; this allows us to guarantee that any exceptions raised
# during function calls are a problem with the module and not just that the
# particular function isn't defined.

class Module(object):
	def hook(self, base):
		self.ircd = base
		return self

class Mode(object):
	def hook(self, base):
		self.ircd = base
		return self
	def checkSet(self, target, param):
		return True
	def checkUnset(self, target, param):
		return True
	def onJoin(self, channel, user, params):
		return "pass"
	def checkPermission(self, user, cmd, data):
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
	def onUse(self, user, data):
		pass
	def processParams(self, user, params):
		return {
			"user": user,
			"params": params
		}
	def updateActivity(self, user):
		user.lastactivity = now()