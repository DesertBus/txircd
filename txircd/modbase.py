# The purpose of this file is to provide base classes with the needed functions
# already defined; this allows us to guarantee that any exceptions raised
# during function calls are a problem with the module and not just that the
# particular function isn't defined.

from txircd.utils import now

class Module(object):
    def hook(self, base):
        self.ircd = base
        return self

class Mode(object):
    def hook(self, base):
        self.ircd = base
        return self
    def checkSet(self, user, target, param):
        return [True, param]
    def checkUnset(self, user, target, param):
        return [True, param]
    def showParam(self, user, target, param):
        return param
    def checkPermission(self, user, cmd, data):
        return data
    def namesListEntry(self, recipient, channel, user, representation):
        return representation

class Command(object):
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