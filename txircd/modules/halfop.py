from txircd.modbase import Mode

class HalfopMode(Mode):
    def checkSet(self, user, target, param):
        if param not in self.ircd.users:
            return [False, param]
        oppingUser = self.ircd.users[param]
        if target.name not in oppingUser.channels:
            return [False, param]
        if "h" in oppingUser.status(target.name):
            return [False, param]
        oppingStatus = oppingUser.status(target.name)
        if user.hasAccess(target.name, "o") and (not oppingStatus or (oppingStatus and user.hasAccess(target.name, oppingStatus[0]))):
            return [True, param]
        return [False, param]
    
    def checkUnset(self, user, target, param):
        if param not in self.ircd.users:
            return [False, param]
        deoppingUser = self.ircd.users[param]
        if target.name not in deoppingUser.channels:
            return [False, param]
        if "h" not in deoppingUser.status(target.name):
            return [False, param]
        if user.hasAccess(target.name, "h") and user == deoppingUser:
            return [True, param]
        if user.hasAccess(target.name, "o") and user.hasAccess(target.name, deoppingUser.status(target.name)[0]):
            return [True, param]
        return [False, param]

class Spawner(object):
    def __init__(self, ircd):
        self.ircd = ircd
    
    def spawn(self):
        return {
            "modes": {
                "csh%50": HalfopMode()
            }
        }
    
    def cleanup(self):
        self.ircd.removeMode("csh")