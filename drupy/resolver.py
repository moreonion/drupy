class Resolver:
    def __init__(self, options):
        self.options = options
        self.readyQueue = []
        self.dependent = {}
        self.dependencies = {}

    def resolve(self, targets):
        """
        Create a sequence of targets to build in order to reach the
        passed-in targets.
        """
        while len(targets) > 0:
            target = targets.pop(0)
            tid = target.__repr__()
            if tid in self.dependencies:
                continue
            deps = target.dependencies()
            ndeps = len(deps)
            self.dependencies[tid] = ndeps
            if ndeps > 0:
                for dep in deps:
                    dep_tid = dep.__repr__()
                    if dep_tid not in self.dependent:
                        self.dependent[dep_tid] = []
                    self.dependent[dep_tid].append(target)
                    targets.append(dep)
            else:
                self.readyQueue.append(target)
        if self.options.debug:
            print(self.readyQueue)
            print(self.dependent)
            print(self.dependencies)

    def execute(self):
        while len(self.readyQueue):
            target = self.readyQueue.pop(0)
            tid = target.__repr__()

            needs_build = (
                not target.already_built()
                or self.options.rebuild
                or (self.options.update and target.updateable())
            )
            if needs_build:
                if self.options.verbose:
                    print("Executing: " + tid)
                if not self.options.dry_run:
                    target.build()
            else:
                if self.options.verbose:
                    print("Skipping: " + tid)

            del self.dependencies[tid]
            if tid not in self.dependent:
                continue
            for dep in self.dependent[tid]:
                dep_tid = dep.__repr__()
                self.dependencies[dep_tid] -= 1
                if self.dependencies[dep_tid] == 0:
                    self.readyQueue.append(dep)
            del self.dependent[tid]


class Target:
    key = None

    def __init__(self, runner):
        self.runner = runner
        self.options = self.runner.options

    def dependencies(self):
        return []

    def already_built(self):
        """Check if the target has been built already"""
        return False

    def updateable(self):
        """Check if the target is updateable"""
        return True

    def build(self):
        """Build the target"""

    def __repr__(self):
        return self.__class__.__name__


class SiteTarget(Target):
    def __init__(self, runner, site):
        Target.__init__(self, runner)
        self.site = site

    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self.site)
