"""Implement a dependency resolver for build targets."""


class Resolver:
    """Dependency resolver for build targets."""

    def __init__(self, options):
        """Create a new resolver."""
        self.options = options
        self.ready_queue = []
        self.dependent = {}
        self.dependencies = {}

    def resolve(self, targets):
        """Create a sequence of targets to build in order to reach the passed-in targets."""
        while len(targets) > 0:
            target = targets.pop(0)
            tid = repr(target)
            if tid in self.dependencies:
                continue
            deps = target.dependencies()
            ndeps = len(deps)
            self.dependencies[tid] = ndeps
            if ndeps > 0:
                for dep in deps:
                    dep_tid = repr(dep)
                    if dep_tid not in self.dependent:
                        self.dependent[dep_tid] = []
                    self.dependent[dep_tid].append(target)
                    targets.append(dep)
            else:
                self.ready_queue.append(target)
        if self.options.debug:
            print(self.ready_queue)
            print(self.dependent)
            print(self.dependencies)

    def execute(self):
        """Build all targets."""
        while self.ready_queue:
            target = self.ready_queue.pop(0)
            tid = repr(target)

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
                dep_tid = repr(dep)
                self.dependencies[dep_tid] -= 1
                if self.dependencies[dep_tid] == 0:
                    self.ready_queue.append(dep)
            del self.dependent[tid]


class Target:
    """Base class for build targets."""

    key = None

    def __init__(self, runner):
        """Create a new target."""
        self.runner = runner
        self.options = self.runner.options

    def dependencies(self):
        """Get the dependencies of this target."""
        return []

    def already_built(self):
        """Check if the target has been built already."""
        return False

    def updateable(self):
        """Check if the target is updateable."""
        return True

    def build(self):
        """Build the target."""

    def __repr__(self):
        """Generate a string representation of this target."""
        return self.__class__.__name__


class SiteTarget(Target):
    """Target for one site in Drupal multi-site tree."""

    def __init__(self, runner, site):
        """Create a new site target."""
        Target.__init__(self, runner)
        self.site = site

    def __repr__(self):
        """Generate a string representation of this target."""
        return f"{self.__class__.__name__}({self.site})"
